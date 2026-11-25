# 独立音频读取实测（2026-11-26）

最后一批横向能力：把公开音频文件当正文读，而不是当网页二进制解码。

## 实现

| 环节 | 复用的东西 |
| --- | --- |
| 下载 | `article_fetcher._fetch_binary_payload` → 现有安全传输（DNS/IP 校验、重定向校验、4 MB 解压上限） |
| 转码 | 本机 FFmpeg，裁到指定时间窗，16 kHz 单声道 WAV |
| 识别 | `video_read._transcribe_media` → 本机 SenseVoice，`--language auto` |
| 输出 | `method=audio_asr`，每行 `[mm:ss] 文本`，`transcript/segments/content` |
| 证据 | 结果保留原始 `url`、`final_url` 与每行 `start/end` |
| 缓存 | 按 URL + 起始秒 + 时长缓存转写，重复读取不重新识别 |

入口：`web_read(mode="audio")`；`mode="auto"` 下 URL 路径以
`.mp3/.m4a/.m4b/.aac/.wav/.flac/.ogg/.oga/.opus` 结尾时自动走音频读取。
视频链路不受影响，`_transcribe_media` 默认语言仍是 `zh`。

## 实测样本

| 样本 | 来源 | 结果 | 耗时 |
| --- | --- | --- | --- |
| 中文讲话 | 本机 TTS（Microsoft Huihui），两句研究相关表述 | `audio_asr`，逐字正确 | 2.7 s |
| 英文讲话 | `voiptroubleshooter.com` 公开 8 kHz WAV | `audio_asr`，2 段、408 字 | 12.5 s（含下载） |
| 多人对话 | 本机 TTS 两音色、中英交替三句 | `audio_asr`，中英都转出，按序 | 2.6 s |
| 纯音乐 | `download.samplelib.com` 3 秒 MP3 | `audio_no_speech` | 5.5 s |
| 超限文件 | 8.4 MB MP3 | `audio_too_large` | 7.1 s |
| 长音频 · 短预算 | 约 4 分钟中文语音、240 秒窗口、8 秒读取预算 | `audio_timeout` | 7.2 s |
| 长音频 · 足预算 | 同一文件、120 秒预算 | `audio_asr`，12 段 | 12.1 s |

中文样本原文与转写一致：

```
人工智能正在改变我们获取信息的方式。研究一个问题时，先找到可靠的资料，再核对不同来源之间是否有矛盾。
```

对话转写保留了两段语言：

```
我觉得这个结论还需要更多证据。I agree, but the sample size is still small，那就先标出不确定的地方，不要急着下结论。
```

## 失败语义

| 情况 | error_code |
| --- | --- |
| SenseVoice 或 ASR 环境缺失 | `audio_asr_unavailable` |
| FFmpeg 缺失 | `audio_ffmpeg_unavailable` |
| 服务器返回 HTML（登录页/落地页） | `audio_not_media` |
| 下载超过 4 MB | `audio_too_large` |
| 纯音乐、静音、噪声 | `audio_no_speech` |
| 识别或转码没有在读取预算内完成 | `audio_timeout` |
| 私有地址/DNS 失败 | `audio_blocked` |
| 识别进程失败 | `audio_asr_failed` |

SenseVoice 在音乐上常吐一个孤立标点；这种行按“无语音”处理，
不当作转写结果发布。

## 边界

- 4 MB 是现有传输的解压上限：128 kbps MP3 约 4 分钟。更长音频需要
  显式 `start_seconds` 分段，或先拿到现成文字稿。
- 约 4 分钟音频的识别本身约 12 秒。语义研究链固定 8 秒读取上限，因此它会以
  `audio_timeout` 失败；这是预算边界，不是模型或转写错误。放长音频需要更大的
  读取预算或更短的 `audio_seconds`。
- 不做说话人分离、情绪分析、音乐识别；多人对话只保证按时间顺序转写。
- 已有文字稿优先：播客 RSS 读取会直接给出 `transcript=` 链接，
  读 `.vtt/.srt` 比重新转写更准，也省时间。
- 不自动发现页面里的音频播放器；只读调用方给出的音频 URL。
- 本机直连 `upload.wikimedia.org` 被重置（代理可用），因此中文与对话
  样本用本机 TTS 生成后走同一条裁切 + 识别链路；URL 下载这一跳用
  公开英文 WAV 单独验证。两类证据都在本文件中写明，不混为一谈。
- 全程没有调用付费模型。
