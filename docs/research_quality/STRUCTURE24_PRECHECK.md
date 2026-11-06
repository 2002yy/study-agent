# structure + 24 零费用预检（阶段 A）

> 对象：`docs/research_quality/answer_ab` 的 20 轮归档答案；
> 费用：0；重现：`PYTHONPATH=. python tools/structure24_precheck.py`；
> 实验专用构建器 `src/web/research/fact_units.py`，**未接入生产入口**。

## 1. 结论

- 24 单元预算下可进入：**13 / 20**；被拒 7 轮（全部是单元预算，非静默截断）。
- 单元到原文的映射：**178 通过 / 0 失败**。
- 被丢弃的序号标题：0 个（全部记录在 `dropped`，可复查）。
- 被接受答案的单元合计 178，对应 A2 候选 534。

> 与上一轮探针的差别：那个探针把 52 个标题当作“结构”丢弃；本次构建器**默认保留所有标题**（只丢纯序号），接受数仍是 13/20。也就是说，丢掉标题并没有换来更多覆盖，反而丢了内容。

## 2. 单轮预算（按 24 单元推导，不是 20 轮合计）

| 项目 | 单轮上限 |
| --- | ---: |
| 事实单元 | 24 |
| A2 候选（每单元 3） | 72 |
| Binder 输出记录 | 24 |
| 按 150 字符估算输出 | 3600 |
| 分段 prompt 上限 | 16000 |

> 20 轮语料中的合计值（504 条候选等）只用于估算总成本，不能当作单轮上限。

## 3. 单元构成（全部 20 轮）

| 类型 | 数量 |
| --- | ---: |
| prose | 229 |
| list_item | 121 |
| heading | 54 |
| table_row | 50 |
| code | 18 |
| table_header | 10 |

## 4. 仍超过 32 单元的答案：多出来的是什么

共 7 轮。它们不是被某个上限挡住，而是确实产生了更多候选单元：

| 文件 | 查询 | 单元 | 构成 |
| --- | --- | ---: | --- |
| ddg_first_20261030T012604.json | PostgreSQL VACUUM FULL 区 | 44 | code:1，heading:5，list_item:6，prose:24，table_header:1，table_row:7 |
| ddg_first_20261030T013119.json | 星铁 千冶·刃 遗器 推荐 黄泉队 | 37 | heading:5，list_item:14，prose:13，table_header:1，table_row:4 |
| ddg_first_20261030T013119.json | FastAPI 依赖注入 数据库 会话 SQLA | 38 | code:6，heading:6，list_item:3，prose:17，table_header:1，table_row:5 |
| ddg_first_20261030T013119.json | astral-sh uv pip depende | 50 | code:1，heading:6，list_item:9，prose:31，table_header:1，table_row:2 |
| fallback_20261030T012542.json | PostgreSQL VACUUM FULL 区 | 53 | heading:5，list_item:18，prose:22，table_header:1，table_row:7 |
| fallback_20261030T012907.json | FastAPI 依赖注入 数据库 会话 SQLA | 43 | code:6，heading:10，list_item:3，prose:18，table_header:1，table_row:5 |
| fallback_20261030T012907.json | SQLite WAL mode advantag | 39 | code:2，heading:5，prose:18，table_header:2，table_row:12 |

合计构成：prose:143，list_item:53，heading:42，table_row:42，code:16，table_header:8。

代码块按整块计为一个单元后仍偏多的部分，主要来自列表项与散文句；也就是说，超过 32 的答案里有相当比例是**结构性枚举**，未必等于同等数量的独立事实——这正是下一步要测量的对象。


## 5. 逐轮明细

| 文件 | 查询 | 状态 | 单元 | 丢标题 | prompt | 候选预算 | 映射失败 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| ddg_first_20261030T012604.json | PostgreSQL VACUUM FULL | 拒绝（unit_budget_exceeded） | 44 | 0 | 2042 | 72 | 0 |
| ddg_first_20261030T013119.json | 星铁 千冶·刃 遗器 推荐 黄泉队 | 拒绝（unit_budget_exceeded） | 37 | 0 | 1312 | 72 | 0 |
| ddg_first_20261030T013119.json | FastAPI 依赖注入 数据库 会话 SQ | 拒绝（unit_budget_exceeded） | 38 | 0 | 3022 | 72 | 0 |
| ddg_first_20261030T013119.json | vLLM GitHub repository | 接受 | 12 | 0 | 588 | 72 | 0 |
| ddg_first_20261030T013119.json | astral-sh uv pip depen | 拒绝（unit_budget_exceeded） | 50 | 0 | 2523 | 72 | 0 |
| ddg_first_20261030T013119.json | Node.js current LTS ve | 接受 | 9 | 0 | 615 | 72 | 0 |
| ddg_first_20261030T013119.json | PostgreSQL latest majo | 接受 | 14 | 0 | 865 | 72 | 0 |
| ddg_first_20261030T013119.json | 2025 诺贝尔物理学奖 获奖者 | 接受 | 13 | 0 | 672 | 72 | 0 |
| ddg_first_20261030T013119.json | SQLite WAL mode advant | 接受 | 23 | 0 | 1431 | 72 | 0 |
| fallback_20261030T012449.json | PostgreSQL VACUUM FULL | 接受 | 2 | 0 | 63 | 72 | 0 |
| fallback_20261030T012542.json | PostgreSQL VACUUM FULL | 拒绝（unit_budget_exceeded） | 53 | 0 | 2453 | 72 | 0 |
| fallback_20261030T012907.json | 星铁 千冶·刃 遗器 推荐 黄泉队 | 接受 | 23 | 0 | 862 | 72 | 0 |
| fallback_20261030T012907.json | FastAPI 依赖注入 数据库 会话 SQ | 拒绝（unit_budget_exceeded） | 43 | 0 | 3146 | 72 | 0 |
| fallback_20261030T012907.json | vLLM GitHub repository | 接受 | 13 | 0 | 730 | 72 | 0 |
| fallback_20261030T012907.json | astral-sh uv pip depen | 接受 | 23 | 0 | 1387 | 72 | 0 |
| fallback_20261030T012907.json | Node.js current LTS ve | 接受 | 18 | 0 | 867 | 72 | 0 |
| fallback_20261030T012907.json | PostgreSQL latest majo | 接受 | 12 | 0 | 665 | 72 | 0 |
| fallback_20261030T012907.json | 黑神话悟空 开发商 游戏科学 总部 | 接受 | 4 | 0 | 157 | 72 | 0 |
| fallback_20261030T012907.json | 2025 诺贝尔物理学奖 获奖者 | 接受 | 12 | 0 | 637 | 72 | 0 |
| fallback_20261030T012907.json | SQLite WAL mode advant | 拒绝（unit_budget_exceeded） | 39 | 0 | 1891 | 72 | 0 |

## 6. 阶段 B 的入口条件（本次未执行）

- 本预检只证明“单元可构建、可映射、预算可提前拒绝”，不证明模型能完成绑定；
- 阶段 B 需要先确定模型、单价、单轮输出上限与硬性费用闸门，再选 4 轮代表性答案（普通长文 / 表格密集 / 代码密集 / 含结论标题）；
- 单轮预估输出按 24 条记录、约 3600 字符估算，实际 token 需按模型分词换算，不能直接等同；
- 验收仍看：输出完整率、映射正确率、无依据支持 0、表头语义保留、标题事实不丢、截断 0 且不被当成功、超预算必须拒绝。
