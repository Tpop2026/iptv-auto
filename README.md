# iptv-auto

[![Update playlists](https://github.com/pq0000/iptv-auto/actions/workflows/update.yml/badge.svg)](https://github.com/pq0000/iptv-auto/actions/workflows/update.yml)
[![Discover & prune](https://github.com/pq0000/iptv-auto/actions/workflows/maintenance.yml/badge.svg)](https://github.com/pq0000/iptv-auto/actions/workflows/maintenance.yml)
![Last commit](https://img.shields.io/github/last-commit/pq0000/iptv-auto)
![License](https://img.shields.io/github/license/pq0000/iptv-auto)

自动聚合公开 IPTV 直播源，生成可直接订阅的 **M3U / TXT / JSON** 文件。  
GitHub Actions **每天北京时间 16:00** 自动抓取、去重、归一并提交更新；流水线失败会**自动开 issue、恢复后自动关闭**，无需人工值守。

## 订阅地址

| 文件 | 地址 |
|---|---|
| 全量 M3U | `https://raw.githubusercontent.com/pq0000/iptv-auto/main/output/index.m3u` |
| 全量 TXT | `https://raw.githubusercontent.com/pq0000/iptv-auto/main/output/list.txt` |
| 全量 JSON | `https://raw.githubusercontent.com/pq0000/iptv-auto/main/output/channels.json` |
| **精选分组列表 M3U**（Guovin 同款） | `https://raw.githubusercontent.com/pq0000/iptv-auto/main/output/favorites.m3u` |
| **精选分组列表 TXT** | `https://raw.githubusercontent.com/pq0000/iptv-auto/main/output/favorites.txt` |
| 央视频道 | `https://raw.githubusercontent.com/pq0000/iptv-auto/main/output/categories/cctv.m3u`（同名 `.txt`） |
| 卫视频道 | `https://raw.githubusercontent.com/pq0000/iptv-auto/main/output/categories/weishi.m3u` |
| 体育频道 | `https://raw.githubusercontent.com/pq0000/iptv-auto/main/output/categories/tiyu.m3u` |
| 广播频道 | `https://raw.githubusercontent.com/pq0000/iptv-auto/main/output/categories/radio.m3u` |
| 港澳台频道 | `https://raw.githubusercontent.com/pq0000/iptv-auto/main/output/categories/hkmotw.m3u` |
| 海外频道 | `https://raw.githubusercontent.com/pq0000/iptv-auto/main/output/categories/overseas.m3u` |

支持 VLC、TiviMate、TVBox、DIYP、APTV 等任意 M3U/TXT 播放器。

> 关于网页播放器：曾实现并试发布过纯静态 HTML5 播放器（GitHub Pages），实测发现 HTTPS 页面无法播放占多数的 `http://` 国内源（浏览器混合内容限制，Service Worker 代理同样被拦截），点播成功率过低，故按约定移除——浏览器端限制是平台层面的，静态托管无解。列表浏览与播放请使用本地播放器。

## 国内加速订阅

GitHub raw 链接在国内经常不稳定，可改用以下实测可用的加速地址（2026-09-27 验证；第三方服务可用性可能变化，失效请反馈）：

**方式一：ghproxy.net 前缀（任意文件通用）**

在完整 raw 链接前直接加 `https://ghproxy.net/`：

| 文件 | 加速地址 |
|---|---|
| 全量 M3U | `https://ghproxy.net/https://raw.githubusercontent.com/pq0000/iptv-auto/main/output/index.m3u` |
| 全量 TXT | `https://ghproxy.net/https://raw.githubusercontent.com/pq0000/iptv-auto/main/output/list.txt` |

> 分类文件同理：把 `output/index.m3u` 换成 `output/categories/cctv.m3u` 等，前缀不变。

**方式二：jsDelivr CDN（含国内节点）**

| 文件 | 加速地址 |
|---|---|
| 全量 M3U | `https://cdn.jsdelivr.net/gh/pq0000/iptv-auto@main/output/index.m3u` |
| 全量 TXT（国内节点，推荐） | `https://quantil.jsdelivr.net/gh/pq0000/iptv-auto@main/output/list.txt` |

> jsDelivr 写法：`https://<节点>/gh/仓库所有者/仓库名@分支/路径`，分支固定为 `main`。精选列表同理：把路径换成 `output/favorites.m3u`（或 ghproxy 前缀版 `https://ghproxy.net/https://raw.githubusercontent.com/pq0000/iptv-auto/main/output/favorites.m3u`）。

## 精选列表（favorites.txt）

`favorites.txt` 是个人频道模板（沿用 Guovin demo.txt 格式）：`分组名,#genre#` 下按行列出频道名。每次抓取会按模板筛选并分组输出 `favorites.m3u` / `favorites.txt`，同名线路**全部保留、无上限**（由播放器自动换线）。改模板推送到 `main` 即生效。

## EPG 节目单接口

生成的所有 M3U 头部已自动内置下列 EPG 地址（TiviMate、TVBox 等支持 `x-tvg-url` 的播放器会自动加载）。如播放器需要手动填写 EPG/XMLTV 地址，可直接使用：

| 接口 | 地址 | 说明 |
|---|---|---|
| epg.pw | `https://epg.pw/xmltv/epg.xml` | 国际 + 国内频道，覆盖面广 |
| zhi35 | `https://live.zhi35.com/epg.xml.gz` | 国内央视/卫视为主，gzip 压缩 |

- 两者均为**第三方公共服务**，可用性、频道匹配率以提供方实况为准；
- 需要完全自建 EPG（自选频道、定时抓取生成 XMLTV）可使用 [iptv-org/epg](https://github.com/iptv-org/epg) 工具。

## 工作流程

1. 定时（每天北京时间 16:00）+ 手动触发 + 源配置变更时运行，先跑单元测试（`scripts/test_fetch.py`）再抓取；
2. 按 `sources.json` 抓取上游播放列表（失败的源跳过并记录在日志）；
3. URL 级去重（忽略大小写、去跟踪参数）+ **同名频道最多保留 3 条线路**（保留互备，去掉冗余）；
4. 统一电视台名称：`CCTV1综合`/`中央1台`/`央视一套` → `CCTV-1 综合`，卫视、凤凰、CGTN 等同步归一；画质标记仅保留 `(4K)`/`(8K)`（`高清`/`标清` 等直接去掉，播放器按线路实际质量播放）；
5. 生成全量与分类文件：M3U 头部自带 **EPG 节目单指针**（epg.pw + zhi35），分类文件 `group-title` 统一为 央视/卫视/体育/广播/港澳台/海外，另输出机器友好的 `channels.json`；
6. 默认**不做测活**（如需可选 404 过滤：环境变量 `IPTV_CHECK_STREAMS=1`）；有变化则由 `github-actions[bot]` 自动提交。

流水线任何一步失败会自动创建/追加 issue「⚠️ 自动化流水线失败」，下次运行恢复后自动关闭——通常只需在 GitHub 通知里瞄一眼。

## 添加 / 管理源

编辑 [`sources.json`](sources.json)：

```json
{ "name": "示例", "url": "https://example.com/list.m3u", "format": "m3u", "enabled": true }
```

- `format`: `m3u` 或 `txt`；
- `enabled`: 设为 `false` 可临时停用。

改完推送到 `main` 会立即触发一次更新。

## 自动化维护（无需人工参与）

由 `.github/workflows/maintenance.yml` 每周一自动执行（也可手动 dispatch）：

**发现新源**
- 用 GitHub 搜索近 30 天有推送的 `topic:iptv` / `topic:m3u` / IPTV 命名仓库（按星排序）
- 读取其 README 提取 `.m3u`/`.txt` 播放列表直链
- 试抓验证：能解析出 ≥100 条频道才收录，每个仓库最多取 1 条，总源数封顶 40 个

**清理失效源（硬移除，原因写入 commit message）**
- 连续 7 天没有一次抓取成功（依据 `state.json`）
- 最近一次抓取结果不足 10 条频道
- 上游为 GitHub raw 且仓库超过 **30 天**没有推送，或已删除

每次抓取运行都会维护 `state.json`（各源最近成功日期/频道数/连续失败次数；**按天粒度且仅在状态变化时写入**，避免无意义的提交噪音），维护工作流据此判定。

## 本地运行

```bash
python scripts/test_fetch.py   # 单元测试
python scripts/fetch.py        # 抓取生成（可选 IPTV_CHECK_STREAMS=1 开启404过滤）
```

无第三方依赖（纯标准库）。国内网络抓取 GitHub raw 源时可设置代理环境变量。

## 开源与致谢

- 本仓库以 [Unlicense](LICENSE) 发布（公共领域授权）：脚本与生成的列表均可自由使用、修改、分发，无需署名、无需开源衍生作品；
- 欢迎社区贡献：新增上游源（改 `sources.json`）、完善分类/名称归一规则（`scripts/fetch.py`）、修复问题，直接提 Issue 或 PR 即可，所有变更都会经自动测试后合入；
- 致谢上游聚合项目（列表数据全部来自这些社区的开放成果，排名不分先后）：[iptv-org/iptv](https://github.com/iptv-org/iptv)、[fanmingming/live](https://github.com/fanmingming/live)、[vbskycn/iptv](https://github.com/vbskycn/iptv)、[zhi35/iptv](https://github.com/zhi35/iptv)、[CCSH/IPTV](https://github.com/CCSH/IPTV)、[Guovin/iptv-api](https://github.com/Guovin/iptv-api)、[YanG-1989/m3u](https://github.com/YanG-1989/m3u)、[YueChan/Live](https://github.com/YueChan/Live)、[Free-TV/IPTV](https://github.com/Free-TV/IPTV)、[qwerttvv/Beijing-IPTV](https://github.com/qwerttvv/Beijing-IPTV) 等；
- EPG 节目单数据来自 [epg.pw](https://epg.pw) 与 [zhi35/iptv](https://github.com/zhi35/iptv)，本仓库仅引用其公开地址。

## 免责声明

本仓库不存储任何视频文件，仅整理公开可访问的流媒体链接。部分上游的流地址带时效参数，静态列表存放过久可能自然失效，**有效性以播放器实际播放为准**（播放器会自动跳过无法播放的线路）。EPG 节目单接口由上述第三方提供，本仓库不拥有其数据，准确性与可用性请以提供方为准，如有问题请联系对应提供方。链路质量取决于上游，仅供学习与个人使用；请遵守当地法律法规，勿用于商业用途。代码以 [Unlicense](LICENSE) 公共领域许可发布，使用本仓库即表示自行承担上述风险。
