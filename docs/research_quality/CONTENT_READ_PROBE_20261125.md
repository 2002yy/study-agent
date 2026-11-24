# 社区与视频内容读取探测（2026-11-25）

> 免费实测，已登录 Edge，每站 1 次。目的不是证明“能打开”，而是区分
> **正文读取成功** 与 **完整讨论读取成功**，为下一批实现定边界。

## 社区页面

| 平台 | 正文 | 讨论信号（DOM 计数） | 分页 | 结论 |
| --- | ---: | --- | ---: | --- |
| 米游社 | 2165 字 | comment 20 / 其他回复容器 485 | 2 | 正文可读；评论在 DOM 里，但需要专门抽取与展开 |
| 知乎 | 17091 字 | 回答 16 | 2 | 问题 + 多回答可读；评论默认未展开 |
| NGA | 3349 字（`read_browse`） | 回复 14 | 0 | 先落广告跳转页，跟进一次后主楼 + 回复可读 |
| 贴吧 | 1483 字 | comment 66 / 回复容器 33 | 1 | 正文可读；楼中楼未验证 |
| V2EX | 12659 字 | 回复 104 | 0 | 主楼 + 整帖回复可读 |
| Reddit | 4726 字 | comment 106 / 回复容器 54 | 0 | 帖子 + 评论可读 |
| 小红书 | — | — | — | 入口链接落到 `/404/sec_...`，未拿到笔记；需登录态与专用入口，本轮未验证 |

## 视频

| 项 | B站 | YouTube |
| --- | --- | --- |
| 公开字幕 | 只有 `danmaku`（XML）；无 CC | `yt-dlp --list-subs` 90 s 超时，未验证 |
| 高清 | 1080P60 需大会员/登录 | — |
| 音频 | `bestaudio` 直链可取（无需登录） | — |
| 评论 | 公开 API 可取：首屏 20 条中返回 3 条，`total=3733` | — |

本机可用媒体能力：

- `ffmpeg` / `ffprobe`：`D:\ffmpeg\ffmpeg-master-latest-win64-gpl\bin\`
- `yt-dlp`：PATH 可用
- `whisper.cpp`：`D:\whisper-cpp\whisper-cli.exe`；`ggml-large-v3-turbo.bin` 1.55 GB、`ggml-small.en.bin` 465 MB
- SenseVoice int8 ONNX：`D:\video\asset_library\models\sensevoice\model.int8.onnx`（228 MB）

## 结论（下一批依据）

1. **正文**：7 个平台中 5 个可直接读到；NGA 需要一次站内跳转跟进（已实现），小红书需要登录入口。
2. **讨论**：评论/回答/回复确实在 DOM 中，但每个平台的容器、展开与分页不同。不做“最长容器就是正文”的统一猜测，按平台抽取，且必须区分“读到正文”与“读完整讨论”。
3. **视频**：公开字幕不可依赖（B站只有弹幕，YouTube 本次不可达）。可靠路线是 `yt-dlp` 取音频 → `ffmpeg` 转码 → `whisper.cpp`/SenseVoice 本地转写；评论走平台公开 API 并限制页数；关键帧后续用 `ffmpeg` 抽取。
4. **边界**：不绕过登录、验证码或付费墙；正文读取失败必须把登录墙、验证墙、超时、无正文分开返回。

## 本轮代码对应

- `src/web/browse_read.py`：严格最终 URL、失败原因分类、一次广告跳转跟进、按给定预算执行（不再抬高到 2 秒）
- `GeneralWebGateway.read(mode=...)`：`auto` / `http` / `browse`；`browser_first` 读取也不再先走 HTTP
- `web_read` 模型工具：新增 `mode` 参数
