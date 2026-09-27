# iptv-auto

自动聚合公开 IPTV 直播源，生成可直接订阅的 **M3U / TXT** 文件。  
GitHub Actions 每 6 小时自动抓取、去重并提交更新（不测活，抓到什么给什么）。

## 订阅地址

| 文件 | 地址 |
|---|---|
| 全量 M3U | `https://raw.githubusercontent.com/pq0000/iptv-auto/main/output/index.m3u` |
| 全量 TXT | `https://raw.githubusercontent.com/pq0000/iptv-auto/main/output/list.txt` |
| 央视频道 | `https://raw.githubusercontent.com/pq0000/iptv-auto/main/output/categories/cctv.m3u`（同名 `.txt`） |
| 卫视频道 | `https://raw.githubusercontent.com/pq0000/iptv-auto/main/output/categories/weishi.m3u` |
| 体育频道 | `https://raw.githubusercontent.com/pq0000/iptv-auto/main/output/categories/tiyu.m3u` |
| 港澳台频道 | `https://raw.githubusercontent.com/pq0000/iptv-auto/main/output/categories/hkmotw.m3u` |
| 海外频道 | `https://raw.githubusercontent.com/pq0000/iptv-auto/main/output/categories/overseas.m3u` |

支持 VLC、TiviMate、TVBox、DIYP、APTV 等任意 M3U/TXT 播放器。

## 工作流程

1. 定时（每 6 小时）+ 手动触发 + 源配置变更时运行；
2. 按 `sources.json` 抓取上游播放列表（失败的源跳过并记录在日志）；
3. 按频道流地址去重，不做测活（播放器自行容错）；
4. 统一电视台名称：CCTV / 央视 / 中央 → `CCTV-1 综合` 式标准台名，卫视、凤凰、CGTN 等同步归一，画质标记规范为 `(高清)`/`(4K)`/`(8K)`/`(标清)`；
5. 按频道名分类，生成全量与分类的 m3u/txt；
6. 有变化则由 `github-actions[bot]` 自动提交。

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

每次抓取运行都会更新 `state.json`（各源最近成功时间/频道数/连续失败次数），维护工作流据此判定。

## 本地运行

```bash
python scripts/fetch.py
```

无第三方依赖（纯标准库）。国内网络抓取 GitHub raw 源时可设置代理环境变量。

## 免责声明

本仓库不存储任何视频文件，仅整理公开可访问的流媒体链接。链路质量取决于上游，仅供学习与个人使用；请遵守当地法律法规，勿用于商业用途。
