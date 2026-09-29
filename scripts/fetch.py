#!/usr/bin/env python3
"""Aggregate public IPTV playlists into m3u/txt outputs.

Usage: python scripts/fetch.py
Reads sources.json, fetches upstream playlists, dedupes channels
(by URL key, max MAX_PER_NAME lines per channel name), normalizes
names, then writes:
  output/index.m3u / output/list.txt / output/channels.json
  output/categories/<cat>.m3u / <cat>.txt
  output/favorites.m3u / output/favorites.txt   (favorites.txt 模板分组, 线路无上限)

Env: IPTV_CHECK_STREAMS=1 — opt-in 404/410 filter on final lines
     (default off: fetch only, players tolerate dead links).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES_FILE = ROOT / "sources.json"
STATE_FILE = ROOT / "state.json"
FAVORITES_FILE = ROOT / "favorites.txt"
OUT_DIR = ROOT / "output"
CAT_DIR = OUT_DIR / "categories"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 iptv-auto/1.0"
)
FETCH_TIMEOUT = 25
MAX_BYTES = 60 * 1024 * 1024
MAX_PER_NAME = 3
EPG_URLS = ",".join(
    [
        "https://epg.pw/xmltv/epg.xml",
        "https://live.zhi35.com/epg.xml.gz",
    ]
)
M3U_HEADER = f'#EXTM3U x-tvg-url="{EPG_URLS}"'

CATEGORIES: dict[str, re.Pattern[str]] = {
    "cctv": re.compile(r"CCTV|央视|CGTN|中央电视", re.I),
    "weishi": re.compile(r"卫视"),
    "tiyu": re.compile(
        r"体育|足球|篮球|高尔夫|网球|赛车|\bF1\b|风云|劲爆|Sport|ESPN|SSU|CCTV-?5",
        re.I,
    ),
    "radio": re.compile(r"电台|广播|\bRadio\b|\bFM\s?\d", re.I),
    "hkmotw": re.compile(
        r"凤凰|TVB|翡翠|明珠|无线电视|HOY|RTHK|港台|NOW\s?TV|ViuTV|Viu\b"
        r"|台视|中视|华视|民视|公视|东森|三立|中天|非凡|超视|纬来|莲卫"
        r"|香港|澳门|台湾",
        re.I,
    ),
}
CAT_LABELS = {
    "cctv": "央视",
    "weishi": "卫视",
    "tiyu": "体育",
    "radio": "广播",
    "hkmotw": "港澳台",
    "overseas": "海外",
}
CJK_RE = re.compile(r"[\u4e00-\u9fff]")

CCTV_OFFICIAL = {
    1: "综合",
    2: "财经",
    3: "综艺",
    4: "中文国际",
    5: "体育",
    6: "电影",
    7: "国防军事",
    8: "电视剧",
    9: "纪录",
    10: "科教",
    11: "戏曲",
    12: "社会与法",
    13: "新闻",
    14: "少儿",
    15: "音乐",
    16: "奥林匹克",
    17: "农业农村",
}
CCTV_CN_NUM = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8,
    "九": 9, "十": 10, "十一": 11, "十二": 12, "十三": 13, "十四": 14,
    "十五": 15, "十六": 16, "十七": 17,
}
# (priority, tokens, suffix label) — higher priority wins when several appear
QUALITY_TOKENS = [
    (4, ["8K"], "(8K)"),
    (3, ["4K", "UHD"], "(4K)"),
    (2, ["FHD", "1080P", "1080i", "高清", "超清", "全高清"], "(高清)"),
    (1, ["HD", "720P", "720i"], "(高清)"),
    (0, ["标清", "SD", "600P", "600p", "480P", "480p", "360P", "360p"], "(标清)"),
]


def _strip_quality(name: str) -> tuple[str, str]:
    best_priority = -1
    suffix = ""
    for priority, tokens, label in QUALITY_TOKENS:
        for tok in tokens:
            if tok in name:
                if priority > best_priority:
                    best_priority = priority
                    suffix = label
                name = name.replace(tok, "")
    return name, suffix


def _trim_junk(name: str) -> str:
    name = re.sub(r"^[^0-9A-Za-z\u4e00-\u9fff]+", "", name)
    name = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff+%]+$", "", name)
    return name.strip()


_REGION_RE = re.compile(
    r"(亚洲|欧洲|美洲|亚太|Asia|Europe|Americas?)(?![A-Za-z])", re.I
)
_REGION_MAP = {"asia": "亚洲", "europe": "欧洲", "americas": "美洲", "america": "美洲"}


def _drop_brackets(name: str) -> str:
    """Remove [tag] / (tag) leftovers but keep region words (CCTV-4 feeds)."""

    def repl(m: re.Match) -> str:
        inner = m.group(0)[1:-1]
        region = _REGION_RE.search(inner)
        return f" {region.group(1)}" if region else " "

    return re.sub(r"\[[^\]]*\]|\([^)]*\)|\{[^}]*\}", repl, name)


def _cctv_name(num: int, plus: bool, rest: str) -> str | None:
    if plus and num == 5:
        return "CCTV-5+ 体育赛事"
    if num == 4:
        region = _REGION_RE.search(rest)
        base = "CCTV-4 中文国际"
        if region:
            tok = region.group(1)
            return f"{base}({_REGION_MAP.get(tok.lower(), tok)})"
        return base
    if num in CCTV_OFFICIAL:
        return f"CCTV-{num} {CCTV_OFFICIAL[num]}"
    return None


def _canonical_base(name: str) -> str:
    m = re.match(
        r"^(?:CCTV|央视|中央广播电视总台|中央电视台|中央电视|中央)"
        r"\s*[-–—_\s]*(\d{1,2})\s*(\+)?",
        name,
        re.I,
    )
    if m:
        out = _cctv_name(int(m.group(1)), bool(m.group(2)), name[m.end():])
        if out:
            return out

    m = re.match(
        r"^(?:央视|中央广播电视总台|中央电视台|中央电视|中央)"
        r"\s*([一二三四五六七八九十]{1,3})\s*[套台期]?\s*(\+)?",
        name,
    )
    if m and m.group(1) in CCTV_CN_NUM:
        out = _cctv_name(CCTV_CN_NUM[m.group(1)], bool(m.group(2)), name[m.end():])
        if out:
            return out

    if re.match(r"^CGTN[\s\-]*(?:英语|英文|English|中文)?$", name, re.I):
        return "CGTN"

    if name.startswith("凤凰") and "资讯" in name:
        return "凤凰资讯台"
    m = re.match(r"^凤凰卫?视?(?:中文)?\s*(欧洲|美洲|香港)?\s*(?:台)?$", name)
    if m:
        region = m.group(1)
        return f"凤凰卫视({region}台)" if region else "凤凰卫视"

    m = re.match(r"^(?:BRTV|BTV)?\s*([一-龥]{2,4})\s*卫视\s*(?:台|频道)?$", name)
    if m:
        return f"{m.group(1)}卫视"
    return name


def normalize_name(raw: str) -> str:
    """Unify channel names to a canonical form, e.g. CCTV1综合 / 中央1台
    -> \"CCTV-1 综合\". Quality markers are dropped except (4K)/(8K),
    which denote a genuinely different feed tier worth keeping."""
    s = unicodedata.normalize("NFKC", raw or "").strip()
    if not s:
        return "Unknown"
    if re.match(r"^(?:CCTV|中央广播电视总台|中央电视台|中央电视|中央|央视)[\s\-–—_]*4[Kk]", s):
        return "CCTV-4K"
    if re.match(r"^(?:CCTV|中央广播电视总台|中央电视台|中央电视|中央|央视)[\s\-–—_]*8[Kk]", s):
        return "CCTV-8K"
    s = re.sub(r"[\u200b-\u200f\ufeff]", "", s)
    s, quality = _strip_quality(s)
    s = _drop_brackets(s)
    s = re.sub(r"[\[\]{}]", " ", s)  # orphan brackets from unbalanced tags
    s = _trim_junk(s)
    s = re.sub(r"\s+", " ", s)
    if not s:
        return "Unknown"
    quality = quality if quality in ("(4K)", "(8K)") else ""
    return _canonical_base(s) + quality


def http_get(url: str, timeout: int = FETCH_TIMEOUT, max_bytes: int = MAX_BYTES) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"response too large (> {max_bytes} bytes): {url}")
    return data


def fetch_source(url: str) -> bytes:
    last_err: Exception | None = None
    for attempt, delay in ((1, 0), (2, 2), (3, 5)):
        if delay:
            time.sleep(delay)
        try:
            return http_get(url)
        except Exception as exc:  # noqa: BLE001 - retry any fetch failure
            last_err = exc
    raise RuntimeError(f"fetch failed: {url} ({last_err})")


def _attrs(line: str) -> dict[str, str]:
    return dict(re.findall(r'([\w-]+)="([^"]*)"', line))


def parse_m3u(text: str) -> list[dict]:
    channels: list[dict] = []
    pending: dict | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            info = _attrs(line)
            name = line.rsplit(",", 1)[-1].strip() if "," in line else "Unknown"
            pending = {
                "name": name or "Unknown",
                "logo": info.get("tvg-logo", ""),
                "group": info.get("group-title", ""),
                "tvg_id": info.get("tvg-id", ""),
            }
        elif line.startswith("#"):
            continue
        elif pending is not None and re.match(r"^[a-z][\w+.-]*://", line, re.I):
            pending["url"] = line
            channels.append(pending)
            pending = None
    return channels


def parse_txt(text: str) -> list[dict]:
    channels: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.search(r"[,|\t]\s*((?:https?|rtmp|rtsp|rtp)://\S+)", line, re.I)
        if m:
            name = line[: m.start()].strip() or m.group(1)
            url = m.group(1)
        elif re.match(r"^[a-z][\w+.-]*://", line, re.I):
            name, url = line, line
        else:
            continue
        channels.append({"name": name, "logo": "", "group": "", "tvg_id": "", "url": url})
    return channels


def parse_playlist(text: str, fmt: str) -> list[dict]:
    if fmt == "txt":
        return parse_txt(text)
    return parse_m3u(text)


def categorize(name: str) -> list[str]:
    cats = [cat for cat, pat in CATEGORIES.items() if pat.search(name)]
    if not cats and not CJK_RE.search(name):
        cats.append("overseas")
    return cats


_TRACKING_RE = re.compile(r"^(utm_|fbclid=|gclid=|spm=|ref=)", re.I)


def url_key(url: str) -> str:
    """Dedup key: case-normalized host, no fragment, no tracking params.

    Keeps http/https and other params untouched — signed stream URLs must
    never be rewritten, only compared.
    """
    u = url.strip().split("#", 1)[0]
    m = re.match(r"^([a-zA-Z][\w+.-]*://)([^/?#]+)(.*)$", u)
    if m:
        u = m.group(1).lower() + m.group(2).lower() + m.group(3)
    if "?" in u:
        base, query = u.split("?", 1)
        kept = [p for p in query.split("&") if p and not _TRACKING_RE.match(p)]
        u = base + ("?" + "&".join(kept) if kept else "")
    return u


def _write(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_outputs(channels: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CAT_DIR.mkdir(parents=True, exist_ok=True)

    lines_m3u = [M3U_HEADER]
    lines_txt: list[str] = []
    by_cat: dict[str, list[dict]] = {cat: [] for cat in (*CATEGORIES, "overseas")}

    for ch in channels:
        logo = f' tvg-logo="{ch["logo"]}"' if ch["logo"] else ""
        group = f' group-title="{ch["group"]}"' if ch["group"] else ""
        tvg_id = f' tvg-id="{ch["tvg_id"]}"' if ch["tvg_id"] else ""
        lines_m3u.append(f"#EXTINF:-1{tvg_id}{logo}{group},{ch['name']}")
        lines_m3u.append(ch["url"])
        lines_txt.append(f'{ch["name"]},{ch["url"]}')
        for cat in categorize(ch["name"]):
            by_cat[cat].append(ch)

    _write(OUT_DIR / "index.m3u", lines_m3u)
    _write(OUT_DIR / "list.txt", lines_txt)

    payload = [
        {
            "name": ch["name"],
            "url": ch["url"],
            "logo": ch["logo"],
            "group": ch["group"],
            "tvg_id": ch["tvg_id"],
            "categories": categorize(ch["name"]),
        }
        for ch in channels
    ]
    (OUT_DIR / "channels.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    for cat, items in by_cat.items():
        if not items:
            continue
        label = CAT_LABELS.get(cat, cat)
        m3u = [M3U_HEADER]
        txt: list[str] = []
        for ch in items:
            logo = f' tvg-logo="{ch["logo"]}"' if ch["logo"] else ""
            m3u.append(f'#EXTINF:-1{logo} group-title="{label}",{ch["name"]}')
            m3u.append(ch["url"])
            txt.append(f'{ch["name"]},{ch["url"]}')
        _write(CAT_DIR / f"{cat}.m3u", m3u)
        _write(CAT_DIR / f"{cat}.txt", txt)


# 模板名 -> 我方标准名的特殊映射（通用规则覆盖不了的少数派）
FAVORITE_ALIASES = {
    "凤凰中文": ["凤凰卫视", "凤凰台", "凤凰卫视中文台"],
    "凤凰资讯": ["凤凰资讯台"],
    "凤凰香港": ["凤凰卫视(香港台)"],
    "CHC高清电影": ["CHC电影"],
    "NewTV精品记录": ["精品纪录"],
    "新闻综合频道": ["新闻综合", "苏州新闻综合"],
    "社会经济频道": ["苏州社会经济"],
    "文化生活频道": ["苏州文化生活"],
    "电影娱乐频道": ["苏州电影娱乐"],
    "生活资讯频道": ["苏州生活资讯"],
}


def favorite_match(template_name: str, channel_name: str) -> bool:
    if channel_name == template_name:
        return True
    if channel_name in FAVORITE_ALIASES.get(template_name, ()):
        return True
    if channel_name.startswith(template_name + " ") or channel_name.startswith(template_name + "("):
        return True
    if template_name.startswith("NewTV") and channel_name == template_name[5:]:
        return True
    core_t = re.sub(r"(台|频道)$", "", template_name)
    core_n = re.sub(r"(台|频道)$", "", channel_name)
    if core_t == core_n:
        return True
    if template_name.startswith("NewTV") and channel_name == core_t[5:]:
        return True
    return False


def load_favorites() -> list[tuple[str, list[str]]]:
    groups: list[tuple[str, list[str]]] = []
    cat = ""
    names: list[str] = []
    if not FAVORITES_FILE.exists():
        return groups
    for raw in FAVORITES_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ",#genre#" in line:
            if names and cat:
                groups.append((cat, names))
            cat = line.split(",")[0].strip()
            names = []
        else:
            names.append(line)
    if names and cat:
        groups.append((cat, names))
    return groups


def write_favorites(channels: list[dict]) -> None:
    """按 favorites.txt 模板输出分组精选列表；同名线路全部保留（无上限）。"""
    groups = load_favorites()
    if not groups:
        return
    stamp = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
    m3u = [M3U_HEADER, "🕘️更新时间,#genre#", f"{stamp} UTC+8,https://github.com/pq0000/iptv-auto"]
    txt = ["🕘️更新时间,#genre#", f"{stamp} UTC+8,https://github.com/pq0000/iptv-auto"]
    matched_names = set()
    for cat, tnames in groups:
        m3u.append(f"{cat},#genre#")
        txt.append(f"{cat},#genre#")
        for t in tnames:
            for ch in channels:
                if not favorite_match(t, ch["name"]):
                    continue
                matched_names.add(t)
                logo = f' tvg-logo="{ch["logo"]}"' if ch["logo"] else ""
                tvg_id = f' tvg-id="{ch["tvg_id"]}"' if ch["tvg_id"] else ""
                m3u.append(f'#EXTINF:-1{tvg_id}{logo} group-title="{cat}",{t}')
                m3u.append(ch["url"])
                txt.append(f"{t},{ch['url']}")
    _write(OUT_DIR / "favorites.m3u", m3u)
    _write(OUT_DIR / "favorites.txt", txt)
    print(f"favorites: {sum(len(n) for _, n in groups)} 个模板频道, 命中 {len(matched_names)} 个")


def stream_alive(url: str) -> bool:
    """Conservative liveness probe: drop only clear 404/410 answers.

    A HEAD 404 is reconfirmed with a ranged GET (some servers mis-answer
    HEAD). Timeouts / 403 / 5xx keep the link — unreachable from this
    vantage point is not proof of death.
    """
    headers = {"User-Agent": UA, "Range": "bytes=0-0"}
    try:
        req = urllib.request.Request(url, method="HEAD", headers=headers)
        with urllib.request.urlopen(req, timeout=6):
            return True
    except urllib.error.HTTPError as exc:
        if exc.code not in (404, 410):
            return True
    except Exception:  # noqa: BLE001
        return True
    try:
        req = urllib.request.Request(url, method="GET", headers=headers)
        with urllib.request.urlopen(req, timeout=6):
            return True
    except urllib.error.HTTPError as exc:
        return exc.code not in (404, 410)
    except Exception:  # noqa: BLE001
        return True


def filter_dead(channels: list[dict]) -> list[dict]:
    import concurrent.futures

    dead: set[str] = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=48) as pool:
        futures = {pool.submit(stream_alive, ch["url"]): ch["url"] for ch in channels}
        for fut in concurrent.futures.as_completed(futures):
            if not fut.result():
                dead.add(futures[fut])
    kept = [ch for ch in channels if ch["url"] not in dead]
    print(f"stream check: {len(channels)} probed, {len(dead)} dropped")
    return kept


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _update_state(sources: list[dict], status: dict[str, dict]) -> None:
    """Persist per-source fetch health for the maintenance script.

    last_ok is day-granular (UTC date) and entries are only rewritten on
    meaningful transitions (first success of a new day, failure streak
    change, recovery). This keeps state.json diffs rare so the bot does
    not commit on every 6-hour run.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    state = _load_json(STATE_FILE)
    changed = False
    for src in sources:
        url = src["url"]
        prev = state.get(url, {})
        res = status.get(url)
        if res and res["ok"]:
            if prev.get("last_ok") == today and int(prev.get("fail_streak") or 0) == 0:
                continue  # already recorded today, nothing new
            state[url] = {
                "last_ok": today,
                "last_count": res["count"],
                "fail_streak": 0,
            }
            changed = True
        else:
            entry = {
                "last_ok": prev.get("last_ok"),
                "last_count": prev.get("last_count", 0),
                "fail_streak": int(prev.get("fail_streak", 0)) + 1,
            }
            if res:
                entry["last_error"] = res["error"][:300]
            state[url] = entry
            changed = True
    known = {s["url"] for s in sources}
    pruned = {u: v for u, v in state.items() if u in known}
    if len(pruned) != len(state):
        changed = True
    if not changed:
        return
    STATE_FILE.write_text(
        json.dumps(pruned, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    cfg = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    sources = [s for s in cfg.get("sources", []) if s.get("enabled", True)]
    merged: list[dict] = []
    seen_urls: set[str] = set()
    summary: list[str] = []
    status: dict[str, dict] = {}
    renamed = 0
    total_parsed = 0

    for src in sources:
        name, url, fmt = src["name"], src["url"], src.get("format", "m3u")
        try:
            raw = fetch_source(url)
            text = raw.decode("utf-8", errors="replace")
            channels = parse_playlist(text, fmt)
        except Exception as exc:  # noqa: BLE001
            status[url] = {"ok": False, "count": 0, "error": str(exc)}
            summary.append(f"[FAIL] {name}: {exc}")
            print(f"[FAIL] {name}: {exc}", file=sys.stderr)
            continue

        status[url] = {"ok": True, "count": len(channels), "error": ""}
        total_parsed += len(channels)
        for ch in channels:
            new_name = normalize_name(ch["name"])
            if new_name != ch["name"]:
                renamed += 1
            ch["name"] = new_name

        added = 0
        for ch in channels:
            key = url_key(ch["url"])
            if not key or key in seen_urls:
                continue
            seen_urls.add(key)
            merged.append(ch)
            added += 1
        summary.append(f"[ OK ] {name}: fetched={len(channels)} added={added}")

    _update_state(sources, status)

    if not merged:
        print("no channels collected, aborting", file=sys.stderr)
        return 1

    # cap redundant mirrors: keep the first MAX_PER_NAME lines per name
    per_name: dict[str, int] = {}
    final: list[dict] = []
    for ch in merged:
        seen = per_name.get(ch["name"], 0)
        if seen >= MAX_PER_NAME:
            continue
        per_name[ch["name"]] = seen + 1
        final.append(ch)
    capped = len(merged) - len(final)

    # safety guard: never overwrite with a drastically shrunken list
    # (protects against a big upstream source silently failing)
    prev_file = OUT_DIR / "list.txt"
    if prev_file.exists():
        with prev_file.open(encoding="utf-8") as fh:
            prev_lines = sum(1 for line in fh if line.strip())
        if prev_lines and len(final) < prev_lines // 2:
            print(
                f"FATAL: output would shrink {prev_lines} -> {len(final)} (>50%); "
                "a major source likely failed — refusing to overwrite",
                file=sys.stderr,
            )
            return 2

    if os.environ.get("IPTV_CHECK_STREAMS") == "1":
        final = filter_dead(final)

    write_outputs(final)
    write_favorites(merged)  # 精选列表不设线路上限，按模板分组
    cat_counts = {}
    for ch in final:
        for cat in categorize(ch["name"]):
            cat_counts[cat] = cat_counts.get(cat, 0) + 1

    print("=== summary ===")
    for line in summary:
        print(line)
    print(f"total channels: {len(final)} (url-dupes removed {total_parsed - len(merged)}, name-cap removed {capped})")
    print(f"unique names: {len(per_name)}")
    print(f"names normalized: {renamed}")
    print(f"categories: {json.dumps(cat_counts, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
