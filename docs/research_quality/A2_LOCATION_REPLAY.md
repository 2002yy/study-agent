# A2 定位回放（零成本）

> 数据：`docs/research_quality/answer_ab` 已归档的真实 A/B 运行（20 轮、两臂）；
> 对象：答案实际看到的 `source_block` 正文 + 该答案本身；
> 费用：0（无任何模型调用）；
> 重现：`PYTHONPATH=. python tools/a2_location_replay.py`。

## 1. 这个数字是什么，不是什么

- 是：**答案自己陈述的 claim，能否在它当时看到的上下文里定位到一段原文。**
- 不是：支持判断准确率（A3 才做），也不是对整页正文的召回（块是展示口径）。
- 因此它是 A2 的**下限**：定位不到的 claim，A3 连判断的机会都没有。

## 2. 生产分段（binder 真实调用方式）

| 指标 | 值 |
| --- | ---: |
| 回放轮次 | 20 |
| **整段无 claim 的答案**（分段预算溢出） | **13** |
| 参与定位的 claim | 64 |
| 至少定位到 1 段 | 41（64.1%） |
| 候选总数 / 每条已定位平均 | 94 / 2.29 |
| 含数字 claim / 已定位 | 32 / 28（87.5%） |
| 其中候选含全部数字 | 19（59.4%） |
| 默认单批预算下被饿死的 claim | 0 |

## 3. 分块回放（去掉 16 段上限，测定位器本身）

| 指标 | 值 |
| --- | ---: |
| 有 claim 的轮次 | 20 / 20 |
| claim 总数 | 488 |
| 至少定位到 1 段 | 279（57.2%） |
| 候选总数 / 每条已定位平均 | 655 / 2.35 |
| 含数字 claim / 已定位 | 82 / 63（76.8%） |
| 其中候选含全部数字 | 41（50.0%） |
| 默认单批预算下被饿死的 claim | 116 |

漏检原因（分块口径）：`no_overlap` 121，`weak_overlap` 88

## 4. 分臂（分块口径）

| 臂 | claim | 已定位 | 可定位率 | 候选/已定位 |
| --- | ---: | ---: | ---: | ---: |
| ddg_first | 245 | 179 | 73.1% | 2.39 |
| fallback | 243 | 100 | 41.2% | 2.27 |

## 5. 逐轮（分块口径）

| 文件 | 臂 | 查询 | claim | 已定位 | 候选 | 漏检原因 |
| --- | --- | --- | ---: | ---: | ---: | --- |
| ddg_first_20261030T012604.json | ddg_first | PostgreSQL VACUUM FULL 区别  | 33 | 28 | 66 | no_overlap:2，weak_overlap:3 |
| ddg_first_20261030T013119.json | ddg_first | 星铁 千冶·刃 遗器 推荐 黄泉队 | 28 | 7 | 10 | no_overlap:10，weak_overlap:11 |
| ddg_first_20261030T013119.json | ddg_first | FastAPI 依赖注入 数据库 会话 SQLAlc | 72 | 68 | 160 | no_overlap:2，weak_overlap:2 |
| ddg_first_20261030T013119.json | ddg_first | vLLM GitHub repository lat | 6 | 5 | 13 | no_overlap:1 |
| ddg_first_20261030T013119.json | ddg_first | astral-sh uv pip dependenc | 43 | 28 | 73 | no_overlap:13，weak_overlap:2 |
| ddg_first_20261030T013119.json | ddg_first | Node.js current LTS versio | 9 | 9 | 16 | - |
| ddg_first_20261030T013119.json | ddg_first | PostgreSQL latest major ve | 15 | 12 | 30 | weak_overlap:3 |
| ddg_first_20261030T013119.json | ddg_first | 2025 诺贝尔物理学奖 获奖者 | 14 | 1 | 1 | no_overlap:11，weak_overlap:2 |
| ddg_first_20261030T013119.json | ddg_first | SQLite WAL mode advantages | 25 | 21 | 59 | no_overlap:2，weak_overlap:2 |
| fallback_20261030T012449.json | fallback | PostgreSQL VACUUM FULL 区别  | 2 | 0 | 0 | weak_overlap:2 |
| fallback_20261030T012542.json | fallback | PostgreSQL VACUUM FULL 区别  | 37 | 14 | 27 | no_overlap:7，weak_overlap:16 |
| fallback_20261030T012907.json | fallback | 星铁 千冶·刃 遗器 推荐 黄泉队 | 22 | 4 | 5 | no_overlap:10，weak_overlap:8 |
| fallback_20261030T012907.json | fallback | FastAPI 依赖注入 数据库 会话 SQLAlc | 75 | 35 | 93 | no_overlap:25，weak_overlap:15 |
| fallback_20261030T012907.json | fallback | vLLM GitHub repository lat | 13 | 12 | 31 | weak_overlap:1 |
| fallback_20261030T012907.json | fallback | astral-sh uv pip dependenc | 23 | 6 | 13 | no_overlap:12，weak_overlap:5 |
| fallback_20261030T012907.json | fallback | Node.js current LTS versio | 20 | 13 | 26 | no_overlap:1，weak_overlap:6 |
| fallback_20261030T012907.json | fallback | PostgreSQL latest major ve | 12 | 5 | 10 | no_overlap:2，weak_overlap:5 |
| fallback_20261030T012907.json | fallback | 黑神话悟空 开发商 游戏科学 总部 | 4 | 1 | 1 | no_overlap:3 |
| fallback_20261030T012907.json | fallback | 2025 诺贝尔物理学奖 获奖者 | 15 | 2 | 3 | no_overlap:13 |
| fallback_20261030T012907.json | fallback | SQLite WAL mode advantages | 20 | 8 | 18 | no_overlap:7，weak_overlap:5 |

## 6. 抽样（人工判断用）

| claim | 定位到的原文片段 | 来源 | 候选数 |
| --- | --- | --- | ---: |
| **普通 VACUUM 是"把死元组占的格子标记为可复用"，VACUUM FULL 是"把活数据抄到新表里，扔掉旧… | 在PostgreSQL（包括Supabase）中，VACUUM 和VACUUM FULL 的区别主要体现在空间回收… | postgresql中执行VACUUM和执行VACUUM full有什么区别 - 掘金 | 3 |
| 先说明一点：检索回来的资料全是“星”字的字典解释，跟星铁无关，所以下面基于游戏机制本身作答，不引用那些来源。 | 星 结构上下结构 五笔JTGF 仓颉AHQM 郑码KMC 五行金 四角60105 电码2502 区位1488 统一… | 《星》的拼音,星字的意思、组词、部首、笔画、笔顺 - 汉语查 | 3 |
| 先给结构：这套东西本质上是**三层职责分离**，很多人搞混是因为把其中两层当成了一层。 | 所以今天这篇就从“为什么需要会话工厂”开始，把这套东西一步步搭出来，顺带把我踩过的坑都写清楚。 | FastAPI项目SQLAlchemy会话工厂搭建与依赖注入实战指南-CSDN博客 | 2 |
| vLLM 仓库当前最新 release 是 **v0.32.0**，发布于 2026-10-18 。 | - v0.32.0 (v0.32.0) published 2026-10-18 | Releases · vllm-project/vllm - GitHub | 3 |
| 先把这个问题拆成三层，因为"benchmark"这个词在 uv 语境里指两个不同的东西，混在一起看会失真。 | All benchmarks were computed on macOS using Python 3.12.4… | uv/BENCHMARKS.md at main · astral-sh/uv · GitHub | 3 |
| 当前 Node.js 的 **Active LTS 是 24.x**，具体最新版本为 **24.11.0**，代号… | Node.js 24.11.0 (LTS) Richard Lau This release marks the … | Node.js — Node.js 24.11.0 (LTS) | 3 |
| PostgreSQL 的最新大版本情况，按"已发布"和"即将发布"分开看： | Below is the complete archive of release notes for every … | Release Notes - PostgreSQL | 3 |
| 2025 年诺贝尔物理学奖授予： | 获奖年份: 全部 2026 (10) 2025 (14) 2024 (11) 2023 (11) 2022 (12… | 2025年诺贝尔奖得主 — 完整名单 | 1 |
| 先说一句本质：WAL 把「回滚日志」换成了「先写日志、后回填」，代价是多了一个 checkpoint 阶段和两个附… | The default method by which SQLite implements atomic comm… | Write-Ahead Logging - SQLite | 3 |
| PostgreSQL 用 MVCC：`UPDATE`/`DELETE` 不真的删数据，只把旧版本行标记为死元组（d… | - 多版本并发控制：PostgreSQL使用多版本并发控制（MVCC，Multiversion concurren… | PostgreSQL 教程 \| 菜鸟教程 | 3 |
| 你问的“千冶·刃”在《崩坏：星穹铁道》里并不存在这个角色名——最接近的是**刃（Blade）**，而“千冶”可能是… | 许多小行星，由于自身的质量比较小，导致自身引力比较小，而且星体一般是由比较坚硬的固体岩石构成的，很难在自身引力的作… | 《星》的拼音,星字的意思、组词、部首、笔画、笔顺 - 汉语查 | 1 |
| 先把这三个词放进同一个结构里，它们不是并列关系，而是**一条链**： | 」 FastAPI 迷你纪录片¶ 在 2025 年末发布了一部 FastAPI 迷你纪录片，你可以在线观看： Ty… | FastAPI - FastAPI | 1 |
| 根据检索到的信息，vLLM 最新发布版本是 **v0.32.0**。 | The High-Throughput and Memory-Efficient inference and se… | vLLM | 3 |
| 先说明一点：这次检索到的结果全部指向 `astral.fan`（一个游戏联机软件），和你要问的 Astral 公司… | AstralGame\|游戏联机 Skip to content NEW Astral Game 已上线，前往 n… | Astral | 3 |
| Node.js 当前的 LTS 版本是 **24.x**（代号 "Krypton"），具体为 **24.11.1*… | node-js 下载：https://nodejs.org/en/download/ 一般会选择在 LTS 下进行… | Node.js 与 npm 的安装与配置（详细教程）_npm安装-CSDN博客 | 3 |
| **PostgreSQL 19 是最新的大版本，目前处于 RC 阶段（RC 1，2026-10-15 发布），尚未… | 2026-10-15 - PostgreSQL 19 Rc 1 Released! | PostgreSQL: The world's most advanced open source database | 3 |
| 需要说明：本轮检索到的网页结果与问题无关（返回的是纯黑壁纸页面），以上为常识性回答。 | 选择更多颜色 下载纯色壁纸 \| 黑色 \| 名称 \| 颜色代码 \| \|---\|---\|---\| \|… | 纯黑图片背景 - 黑色全屏，壁纸下载，屏幕测试 | 1 |
| 2025 年诺贝尔物理学奖授予 **John Clarke、Michel H. | 2025年日历全年完整图_带农历节假日放假安排_高清可打印免费下载 - 知之日历 公历 · 农历 · 节气 · 节… | 2025年日历全年完整图_带农历节假日放假安排_高清可打印 ... | 1 |
| 一句话本质：**WAL 把"写操作要改主数据库文件"变成"写操作只追加到日志"，读写不再互相阻塞——代价是多出几个… | SQLite JDBC Driver: - SQLite JDBC，由 Taro L. Saito 开发的，是一个… | SQLite 教程 \| 菜鸟教程 | 3 |

## 7. 本轮测出的两个结构性问题

1. **分段上限吞掉整段答案**：13 / 20 轮答案的原始分段数超过 binder 的 16 段上限，`accepted=false`，因此这些回答在现有链路上拿不到任何 claim 级绑定；A2/A3 对它们完全没有输入。这是既有 binder 行为，不是 A2 的缺陷。
2. **单批预算必须随 claim 数走**：把上限固定在 12 时，同一份回放里生产口径 20 / 64 条、分块口径 283 / 488 条 claim 因 `total_cap_reached` 从未被尝试——长答案的尾部等于没做分析。默认值已改为 `16 x 3 = 48`（binder 分段上限 × 每事实候选数），改后生产口径被饿死 0 条；分块口径仍有 116 条，属于超出 binder 上限的场景，不是生产路径。

## 8. 已知局限

1. 正文是渲染后的 `source_block`（展示口径），比读取记录短，数字偏保守；
2. claim 来自答案分段，不是人工标注的事实清单，长段落算一条；
3. 候选“相关”不等于“支持”，本表不做任何支持判断；
4. 抽样里可见噪声（如诺贝尔奖 claim 命中日历页），这正是 A3 必须存在的理由；
5. 同义改写与跨语言 claim 的漏检如实计入 `no_overlap` / `weak_overlap`。
