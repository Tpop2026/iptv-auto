#!/usr/bin/env python3
"""Aggregate public IPTV playlists into m3u/txt outputs.

Usage: python scripts/fetch.py
Reads sources.json, fetches upstream playlists, dedupes channels,
then writes:
  output/index.m3u
  output/list.txt
  output/categories/<cat>.m3u / <cat>.txt
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES_FILE = ROOT / "sources.json"
OUT_DIR = ROOT / "output"
CAT_DIR = OUT_DIR / "categories"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 iptv-auto/1.0"
)
FETCH_TIMEOUT = 25
MAX_BYTES = 60 * 1024 * 1024

CATEGORIES: dict[str, re.Pattern[str]] = {
    "cctv": re.compile(r"CCTV|央视|CGTN|中央电视", re.I),
    "weishi": re.compile(r"卫视"),
    "tiyu": re.compile(
        r"体育|足球|篮球|高尔夫|网球|赛车|\bF1\b|风云|劲爆|Sport|ESPN|SSU|CCTV-?5",
        re.I,
    ),
    "hkmotw": re.compile(
        r"凤凰|TVB|翡翠|明珠|无线电视|HOY|RTHK|港台|NOW\s?TV|ViuTV|Viu\b"
        r"|台视|中视|华视|民视|公视|东森|三立|中天|非凡|超视|纬来|莲卫"
        r"|香港|澳门|台湾",
        re.I,
    ),
}
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


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
    for attempt in (1, 2):
        try:
            return http_get(url)
        except Exception as exc:  # noqa: BLE001 - retry any fetch failure
            last_err = exc
            if attempt == 1:
                time.sleep(2)
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


def _write(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_outputs(channels: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CAT_DIR.mkdir(parents=True, exist_ok=True)

    lines_m3u = ["#EXTM3U"]
    lines_txt: list[str] = []
    by_cat: dict[str, list[dict]] = {cat: [] for cat in (*CATEGORIES, "overseas")}

    for ch in channels:
        logo = f' tvg-logo="{ch["logo"]}"' if ch["logo"] else ""
        group = f' group-title="{ch["group"]}"' if ch["group"] else ""
        tvg_id = f' tvg-id="{ch["tvg_id"]}"' if ch["tvg_id"] else ""
        lines_m3u.append(f'#EXTINF:-1{tvg_id}{logo}{group},{ch["name"]}')
        lines_m3u.append(ch["url"])
        lines_txt.append(f'{ch["name"]},{ch["url"]}')
        for cat in categorize(ch["name"]):
            by_cat[cat].append(ch)

    _write(OUT_DIR / "index.m3u", lines_m3u)
    _write(OUT_DIR / "list.txt", lines_txt)

    for cat, items in by_cat.items():
        if not items:
            continue
        m3u = ["#EXTM3U"]
        txt: list[str] = []
        for ch in items:
            group = f' group-title="{ch["group"]}"' if ch["group"] else ""
            logo = f' tvg-logo="{ch["logo"]}"' if ch["logo"] else ""
            m3u.append(f"#EXTINF:-1{logo}{group},{ch['name']}")
            m3u.append(ch["url"])
            txt.append(f'{ch["name"]},{ch["url"]}')
        _write(CAT_DIR / f"{cat}.m3u", m3u)
        _write(CAT_DIR / f"{cat}.txt", txt)


def main() -> int:
    cfg = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    sources = [s for s in cfg.get("sources", []) if s.get("enabled", True)]
    merged: list[dict] = []
    seen_urls: set[str] = set()
    summary: list[str] = []

    for src in sources:
        name, url, fmt = src["name"], src["url"], src.get("format", "m3u")
        try:
            raw = fetch_source(url)
            text = raw.decode("utf-8", errors="replace")
            channels = parse_playlist(text, fmt)
        except Exception as exc:  # noqa: BLE001
            summary.append(f"[FAIL] {name}: {exc}")
            print(f"[FAIL] {name}: {exc}", file=sys.stderr)
            continue

        added = 0
        for ch in channels:
            key = ch["url"].strip()
            if not key or key in seen_urls:
                continue
            seen_urls.add(key)
            merged.append(ch)
            added += 1
        summary.append(f"[ OK ] {name}: fetched={len(channels)} added={added}")

    if not merged:
        print("no channels collected, aborting", file=sys.stderr)
        return 1

    write_outputs(merged)
    cat_counts = {}
    for ch in merged:
        for cat in categorize(ch["name"]):
            cat_counts[cat] = cat_counts.get(cat, 0) + 1

    print("=== summary ===")
    for line in summary:
        print(line)
    print(f"total channels: {len(merged)}")
    print(f"categories: {json.dumps(cat_counts, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
