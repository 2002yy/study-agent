# B站语音转写实测：SenseVoice vs whisper.cpp（2026-11-25）

> 免费实测，各 60 秒片段，同一台机器。目的不是做评测框架，而是给本机选一个默认引擎，
> 并确认“先把视频读成带时间戳的文字”这条路可行。

## 样本

| 类别 | BV | 片段 | 下载 |
| --- | --- | ---: | ---: |
| 游戏攻略 | `BV1Va4y167wd`（原神配队思路） | 60 s / 2.5 MB | 3.5 s |
| 技术教程 | `BV1rpWjevEip`（Python 教程） | 60 s / 2.4 MB | 76.2 s |
| 硬件评测 | — | — | B站搜索 API 412，未跑 |

## 耗时

| 引擎 | 游戏 60 s | 技术 60 s | 相对实时 |
| --- | ---: | ---: | ---: |
| SenseVoice（sherpa-onnx int8） | 3.5 s | 2.6 s | 约 0.05× |
| whisper.cpp large-v3-turbo | 40.0 s | 40.1 s | 约 0.67× |

SenseVoice 快约 10 倍；两者都输出时间戳（SenseVoice 20 s 分段，whisper 逐句）。

## 关键术语人工核对

没有标准转写稿，以下按上下文可确认的正确写法逐项对照（“部分”指被截断或只对一半）。

| 期望 | SenseVoice | whisper.cpp |
| --- | --- | --- |
| 原神 | 元神 ✗ | 原神 ✓ |
| 配队 | 配对 ✗ | 配对 ✗ |
| 圣遗物 | 圣遗物 ✓ | 剩一物 ✗ |
| 叠个甲 | 叠个甲 ✓ | 叠个假 ✗ |
| 各司其职 | 各司其职 ✓ | 各施其职 ✗ |
| Python | 拍损 ✗ | 拍损 ✗ |
| YouTube | youtu（截断）✗ | YouTube ✓ |
| 一劳永逸 | 一劳永逸 ✓ | 一老永逸 ✗ |
| 滥竽充数 | 滥竽充（截断）部分 | 烂鱼充数 ✗ |
| 审时度势 | 审时多势 ✗ | 审时多事 ✗ |

粗略计分：SenseVoice 4.5/10，whisper 4/10。**没有明显赢家**；两者都会把
“配队”听成“配对”、把 “Python” 听成“拍损”。这说明领域词表校正比换引擎更关键。

## 结论

1. **默认 SenseVoice**：快 10 倍，中文游戏术语更好；适合“先转写、再让模型判断相关性”。
2. **whisper large-v3-turbo 作为精读可选**：英文产品名/型号更稳（YouTube），但慢。
3. 数字、型号、技能名不能只靠 ASR 原样输出；后续加一层领域词表后校正（原神角色/配队、Python、显卡型号）。
4. 硬件评测样本未跑通（B站搜索 API 412），下一轮补；不影响当前结论。

## 复现

- 片段：`yt-dlp --download-sections "*0-60" -f "bv*[height<=480]+ba"`
- SenseVoice：`D:\video\tools\envs\asr\Scripts\python.exe asr_sensevoice.py --video clip.mp4 --out-dir out`
- whisper：`D:\whisper-cpp\whisper-cli.exe -m ggml-large-v3-turbo.bin -f audio.wav -l zh -otxt`
- 原始报告：`C:\Users\Zhang\AppData\Local\Temp\opencode\video-probe2\report.json`（临时文件）
