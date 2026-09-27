# iptv-auto

自动聚合公开 IPTV 直播源，生成可直接订阅的 **M3U / TXT** 文件。  
GitHub Actions 每 6 小时自动抓取、去重、剔除明显失效链接并提交更新。

## 订阅地址

将 `USER` 替换为仓库所有者用户名：

| 文件 | 地址 |
|---|---|
| 全量 M3U | `https://raw.githubusercontent.com/USER/iptv-auto/main/output/index.m3u` |
| 全量 TXT | `https://raw.githubusercontent.com/USER/iptv-auto/main/output/list.txt` |
| 央视频道 | `.../output/categories/cctv.m3u`（同名 `.txt`） |
| 卫视频道 | `.../output/categories/weishi.m3u` |
| 体育频道 | `.../output/categories/tiyu.m3u` |
| 港澳台频道 | `.../output/categories/hkmotw.m3u` |
| 海外频道 | `.../output/categories/overseas.m3u` |

支持 VLC、TiviMate、TVBox、DIYP、APTV 等任意 M3U/TXT 播放器。

## 工作流程

1. 定时（每 6 小时）+ 手动触发 + 源配置变更时运行；
2. 按 `sources.json` 抓取上游播放列表（失败的源跳过并记录在日志）；
3. 对上游源做 HTTP 状态校验，按 URL 去重；
4. 对体积较小的源逐条校验流地址，**仅剔除明确返回 404/410 的链接**（超时/403 等无法证明失效的保留）；
5. 按频道名分类，生成全量与分类的 m3u/txt；
6. 有变化则由 `github-actions[bot]` 自动提交。

## 添加 / 管理源

编辑 [`sources.json`](sources.json)：

```json
{ "name": "示例", "url": "https://example.com/list.m3u", "format": "m3u", "check_streams": true, "enabled": true }
```

- `check_streams`: 是否逐条校验该源的流地址（超大源建议 `false`，如 iptv-org）；
- `enabled`: 设为 `false` 可临时停用。

改完推送到 `main` 会立即触发一次更新。

## 本地运行

```bash
python scripts/fetch.py
```

无第三方依赖（纯标准库）。国内网络抓取 GitHub raw 源时可设置代理环境变量。

## 免责声明

本仓库不存储任何视频文件，仅整理公开可访问的流媒体链接。链路质量取决于上游，仅供学习与个人使用；请遵守当地法律法规，勿用于商业用途。
