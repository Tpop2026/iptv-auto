#!/usr/bin/env python3
"""Self-tests for fetch.py. Run: python scripts/test_fetch.py"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch as F
from fetch import (
    CAT_LABELS,
    MAX_PER_NAME,
    M3U_HEADER,
    categorize,
    favorite_match,
    normalize_name,
    parse_m3u,
    parse_txt,
    url_key,
)

failures: list[str] = []


def check(label: str, got, want) -> None:
    if got != want:
        failures.append(f"{label}: got {got!r}, want {want!r}")


# --- normalize_name -------------------------------------------------------
check("cctv", normalize_name("CCTV1综合"), "CCTV-1 综合")
check("cctv-hd-dropped", normalize_name("CCTV-1综合高清"), "CCTV-1 综合")
check("cctv-4k-kept", normalize_name("CCTV16 4K"), "CCTV-16 奥林匹克(4K)")
check("cctv-cn-numeral", normalize_name("央视一套"), "CCTV-1 综合")
check("cctv5-plus", normalize_name("CCTV5+体育赛事"), "CCTV-5+ 体育赛事")
check("cctv4-region", normalize_name("CCTV4欧洲"), "CCTV-4 中文国际(欧洲)")
check("cctv-unknown", normalize_name("CCTV18"), "CCTV18")
check("cctv4k-early", normalize_name("CCTV4K"), "CCTV-4K")
check("weishi-hd", normalize_name("湖南卫视HD"), "湖南卫视")
check("weishi-4k", normalize_name("湖南卫视4K"), "湖南卫视(4K)")
check("weishi-space", normalize_name("湖南 卫视"), "湖南卫视")
check("brtv", normalize_name("BRTV北京卫视"), "北京卫视")
check("fenghuang", normalize_name("凤凰卫视中文台"), "凤凰卫视")
check("fenghuang-info", normalize_name("凤凰卫视资讯台"), "凤凰资讯台")
check("cgtn", normalize_name("CGTN English"), "CGTN")
check("junk-emoji", normalize_name("  \U0001f4fa CCTV-13新闻 "), "CCTV-13 新闻")

# --- parsers --------------------------------------------------------------
m3u = parse_m3u('#EXTM3U\n#EXTINF:-1 tvg-id="x" group-title="G",A台\nhttp://a/x\n')
check("parse-m3u", (m3u[0]["name"], m3u[0]["url"], m3u[0]["tvg_id"]), ("A台", "http://a/x", "x"))
txt = parse_txt("B台,http://b/y\nhttp://c/z\n")
check("parse-txt", (txt[0]["name"], txt[1]["name"]), ("B台", "http://c/z"))

# --- categorize -----------------------------------------------------------
check("cat-cctv", "cctv" in categorize("CCTV-1 综合"), True)
check("cat-weishi", "weishi" in categorize("湖南卫视"), True)
check("cat-radio", "radio" in categorize("上海电台"), True)
check("cat-overseas", categorize("BBC One"), ["overseas"])
check("labels", set(CAT_LABELS) >= {"cctv", "weishi", "tiyu", "radio", "hkmotw", "overseas"}, True)

# --- url_key --------------------------------------------------------------
check("url-host-case", url_key("HTTP://Example.com/A?b=2"), "http://example.com/A?b=2")
check("url-fragment", url_key("http://a/x#t=1"), "http://a/x")
check("url-tracking", url_key("http://a/x?utm_source=s&sign=1"), "http://a/x?sign=1")
check("url-keep-sign", url_key("http://a/x?sign=1") != url_key("http://a/x?sign=2"), True)

# --- favorite_match -------------------------------------------------------
check("fav-cctv", favorite_match("CCTV-1", "CCTV-1 综合"), True)
check("fav-cctv-no-prefix", favorite_match("CCTV-1", "CCTV-12社会与法"), False)
check("fav-5plus", favorite_match("CCTV-5+", "CCTV-5+ 体育赛事"), True)
check("fav-weishi-q", favorite_match("湖南卫视", "湖南卫视(4K)"), True)
check("fav-fh-cn", favorite_match("凤凰中文", "凤凰卫视"), True)
check("fav-fh-info", favorite_match("凤凰资讯", "凤凰资讯台"), True)
check("fav-fh-hk", favorite_match("凤凰香港", "凤凰卫视(香港台)"), True)
check("fav-newtv", favorite_match("NewTV爱情喜剧", "爱情喜剧"), True)
check("fav-chc", favorite_match("CHC高清电影", "CHC电影"), True)
check("fav-suzhou", favorite_match("社会经济频道", "苏州社会经济"), True)
check("fav-record", favorite_match("NewTV精品记录", "精品纪录"), True)
check("fav-neg", favorite_match("湖南卫视", "浙江卫视"), False)

# --- constants ------------------------------------------------------------
check("cap", MAX_PER_NAME, 3)
check("epg-header", 'x-tvg-url="' in M3U_HEADER and "epg.pw" in M3U_HEADER, True)

# --- write_outputs --------------------------------------------------------
tmp = Path(tempfile.mkdtemp())
F.OUT_DIR = tmp
F.CAT_DIR = tmp / "categories"
F.write_outputs(
    [
        {"name": "CCTV-1 综合", "url": "http://x/1", "logo": "", "group": "G", "tvg_id": ""},
        {"name": "湖南卫视", "url": "http://x/2", "logo": "", "group": "", "tvg_id": ""},
    ]
)
idx = (tmp / "index.m3u").read_text(encoding="utf-8")
check("out-header", idx.splitlines()[0], M3U_HEADER)
check("out-json", (tmp / "channels.json").exists(), True)
cat_m3u = (tmp / "categories" / "cctv.m3u").read_text(encoding="utf-8")
check("out-cat-group", 'group-title="央视"' in cat_m3u, True)

# --- state noise reduction ------------------------------------------------
F.STATE_FILE = tmp / "state.json"
src = [{"name": "n", "url": "http://s/1"}]
ok = {"http://s/1": {"ok": True, "count": 100, "error": ""}}
F._update_state(src, ok)
first = F.STATE_FILE.read_text(encoding="utf-8")
check("state-date-format", len(first.split('"last_ok": "')[1][:10]), 10)
F._update_state(src, ok)
check("state-noop-same-day", F.STATE_FILE.read_text(encoding="utf-8"), first)
F._update_state(src, {"http://s/1": {"ok": False, "count": 0, "error": "boom"}})
fail_state = F.STATE_FILE.read_text(encoding="utf-8")
check("state-fail-streak", '"fail_streak": 1' in fail_state, True)
F._update_state(src, ok)
recovered = F.STATE_FILE.read_text(encoding="utf-8")
check("state-recover-reset", '"fail_streak": 0' in recovered, True)

if failures:
    print("FAILED:")
    for line in failures:
        print(" -", line)
    raise SystemExit(1)
print("all tests passed")
