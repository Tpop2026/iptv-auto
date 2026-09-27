#!/usr/bin/env python3
"""Weekly maintenance: discover new upstream sources and prune stale ones.

Run: python scripts/maintenance.py
Env: GITHUB_TOKEN (or GH_TOKEN) — required for discovery and repo-staleness
     checks; without it those steps are skipped.

Prune rules (entries are removed from sources.json hard):
  - no successful fetch for more than NO_SUCCESS_DAYS days (state.json)
  - last successful fetch yielded fewer than MIN_LAST_COUNT channels
  - upstream is raw.githubusercontent.com and the repo was last pushed
    more than STALE_REPO_DAYS days ago, or no longer exists (404)

Discovery rules:
  - search GitHub for recently pushed topic:iptv / topic:m3u / IPTV-named repos
  - extract playlist URLs (.m3u/.txt) from their README
  - probe each candidate by fetching: keep only if it parses to at least
    MIN_CHANNELS channels; at most one accepted candidate per repo
  - never exceed MAX_SOURCES entries
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch import UA, fetch_source, parse_m3u, parse_txt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SOURCES_FILE = ROOT / "sources.json"
STATE_FILE = ROOT / "state.json"

TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
OWN_REPO = os.environ.get("GITHUB_REPOSITORY") or "pq0000/iptv-auto"

NO_SUCCESS_DAYS = 7
STALE_REPO_DAYS = 30
MIN_LAST_COUNT = 10
MIN_CHANNELS = 100
MAX_SOURCES = 40
MAX_REPOS_PROBED = 30
MAX_URLS_PER_REPO = 2

URL_RE = re.compile(r'https?://[^\s<>"\'\)\]]+', re.I)
PLAYLIST_RE = re.compile(r"\.(m3u|m3u8|txt)(\?|$)", re.I)
RAW_REPO_RE = re.compile(
    r"^https?://raw\.githubusercontent\.com/([^/]+)/([^/]+)/", re.I
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _days_since(iso: str) -> float:
    ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (_now() - ts).total_seconds() / 86400


def gh_get(path: str, accept: str = "application/vnd.github+json") -> bytes | None:
    """GET api.github.com path. None on any failure (rate limit, network...)."""
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "User-Agent": UA,
            "Accept": accept,
            "Authorization": f"Bearer {TOKEN}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return resp.read()
    except Exception as exc:  # noqa: BLE001
        print(f"  gh_get failed {path}: {exc}", file=sys.stderr)
        return None


def gh_get_json(path: str) -> dict | None:
    raw = gh_get(path)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def search_repos(query: str) -> list[dict]:
    q = urllib.parse.quote(query)
    data = gh_get_json(f"/search/repositories?q={q}&sort=stars&order=desc&per_page=30")
    if not data:
        return []
    return data.get("items") or []


def get_readme(full_name: str) -> str | None:
    raw = gh_get(f"/repos/{full_name}/readme", accept="application/vnd.github.raw")
    if raw is None:
        return None
    return raw.decode("utf-8", errors="replace")


def repo_pushed_at(full_name: str) -> tuple[str, str | None]:
    """('ok', iso) / ('missing', None) / ('unknown', None) on API failure."""
    data = gh_get_json(f"/repos/{full_name}")
    if data is None:
        return "unknown", None
    if data.get("message") == "Not Found":
        return "missing", None
    pushed = data.get("pushed_at")
    return ("ok", pushed) if pushed else ("unknown", None)


def extract_candidate_urls(text: str) -> list[str]:
    found: list[str] = []
    for u in URL_RE.findall(text):
        u = u.rstrip(".,;:)")
        if not PLAYLIST_RE.search(u):
            continue
        if u not in found:
            found.append(u)
    return found


def probe(url: str) -> tuple[str, int] | None:
    """Fetch a candidate playlist. Returns (format, channel_count) or None."""
    try:
        raw = fetch_source(url)
    except Exception as exc:  # noqa: BLE001
        print(f"  probe failed {url}: {exc}", file=sys.stderr)
        return None
    text = raw.decode("utf-8", errors="replace")
    primary = "txt" if re.search(r"\.txt(\?|$)", url, re.I) else "m3u"
    parsers = {
        "txt": parse_txt,
        "m3u": parse_m3u,
    }
    secondary = "m3u" if primary == "txt" else "txt"
    n1 = len(parsers[primary](text))
    if n1 >= MIN_CHANNELS:
        return primary, n1
    n2 = len(parsers[secondary](text))
    if n2 >= MIN_CHANNELS:
        return secondary, n2
    return None


def load_sources() -> list[dict]:
    return json.loads(SOURCES_FILE.read_text(encoding="utf-8")).get("sources", [])


def save_sources(sources: list[dict]) -> None:
    SOURCES_FILE.write_text(
        json.dumps({"sources": sources}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def prune(sources: list[dict], state: dict) -> tuple[list[dict], list[str]]:
    kept: list[dict] = []
    removed: list[str] = []
    for src in sources:
        url = src["url"]
        reason = None

        st = state.get(url)
        if st and st.get("last_ok"):
            age = _days_since(st["last_ok"])
            if age > NO_SUCCESS_DAYS:
                reason = f"no successful fetch for {int(age)}d"
            elif int(st.get("last_count") or 0) < MIN_LAST_COUNT:
                reason = f"last fetch only {st.get('last_count')} channels"
        elif st is not None and not st.get("last_ok"):
            if int(st.get("fail_streak") or 0) >= NO_SUCCESS_DAYS * 6:
                reason = f"failing for {st['fail_streak']} consecutive runs"

        if reason is None:
            m = RAW_REPO_RE.match(url)
            if m and TOKEN:
                full = f"{m.group(1)}/{m.group(2)}"
                state_flag, pushed = repo_pushed_at(full)
                if state_flag == "missing":
                    reason = f"upstream repo {full} is gone"
                elif state_flag == "ok" and pushed and _days_since(pushed) > STALE_REPO_DAYS:
                    reason = f"upstream repo {full} stale {int(_days_since(pushed))}d"
                elif state_flag == "unknown":
                    print(f"  skip staleness check for {full} (API unavailable)")

        if reason:
            removed.append(f"{src['name']} ({url}) -> {reason}")
        else:
            kept.append(src)
    return kept, removed


def discover(sources: list[dict]) -> list[dict]:
    if not TOKEN:
        print("discovery skipped: no GITHUB_TOKEN")
        return sources
    if len(sources) >= MAX_SOURCES:
        print(f"discovery skipped: already at {MAX_SOURCES} sources")
        return sources

    cutoff = (_now() - timedelta(days=STALE_REPO_DAYS)).date().isoformat()
    queries = [
        f"topic:iptv fork:false pushed:>={cutoff}",
        f"topic:m3u fork:false pushed:>={cutoff}",
        f"IPTV in:name fork:false pushed:>={cutoff}",
    ]

    existing_urls = {s["url"] for s in sources}
    existing_repos: set[str] = set()
    for s in sources:
        m = RAW_REPO_RE.match(s["url"])
        if m:
            existing_repos.add(f"{m.group(1)}/{m.group(2)}".lower())

    candidates: dict[str, int] = {}
    for q in queries:
        for item in search_repos(q):
            full = item.get("full_name") or ""
            if not full or full.lower() == OWN_REPO.lower():
                continue
            if full.lower() in existing_repos:
                continue
            candidates.setdefault(full, int(item.get("stargazers_count") or 0))

    ranked = sorted(candidates, key=lambda r: -candidates[r])[:MAX_REPOS_PROBED]
    print(f"discovery: {len(ranked)} candidate repos")

    added_sources = list(sources)
    added_urls = {s["url"] for s in added_sources}
    for full in ranked:
        if len(added_sources) >= MAX_SOURCES:
            print(f"discovery: reached cap {MAX_SOURCES}")
            break
        readme = get_readme(full)
        if not readme:
            continue
        for url in extract_candidate_urls(readme)[:MAX_URLS_PER_REPO]:
            if url in added_urls:
                continue
            res = probe(url)
            if not res:
                continue
            fmt, count = res
            added_sources.append(
                {"name": full, "url": url, "format": fmt, "enabled": True}
            )
            added_urls.add(url)
            print(f"  + added {full} -> {url} ({fmt}, {count} channels)")
            break
    return added_sources


def main() -> int:
    sources = load_sources()
    state = load_state()

    kept, removed = prune(sources, state)
    print(f"prune: {len(sources)} -> {len(kept)}")
    for line in removed:
        print(f"  - removed {line}")

    final = discover(kept)

    save_sources(final)
    known = {s["url"] for s in final}
    new_state = {u: v for u, v in state.items() if u in known}
    STATE_FILE.write_text(
        json.dumps(new_state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(f"sources: {len(sources)} -> {len(final)} (removed {len(removed)})")
    if removed:
        print("REMOVED:")
        for line in removed:
            print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
