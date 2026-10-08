# RP-1：FastAPI 精确版本读取与发布日期绑定

2026-10-09；branch `codex/reading-notebook-ui`，base `97e0b4f6`。
本批只有来源适配、确定性负控、固定两样本资格与交接；不关闭 RP-1 / R6。
最终 head、clean、完整测试结果见 Git 与外部 closeout-state.json。

## 原始证据与首次断点

先读取真实官方 HTML，再修改适配器。原始 1,555,889 bytes 的解码/transport
SHA256 均为 `06f924667f2ebd1d8b25310d76c46a03eb2c8d19e05fbed176b0df8f226f9aab`。
官方 article 内各有唯一 h2：

| 样本 | 原始标题 | 原始 anchor |
| --- | --- | --- |
| 原 S5 | 0.136.0 (2026-04-16) | 01360-2026-04-16 |
| 原 N3 | 0.115.0 (2024-09-17) | 01150-2024-09-17 |

S5 的旧 1,055 字正文存在版本/日期，但没有可采用的日期字段关系；N3 的旧正文
只含近期目录，遗漏旧版本。完整 HTML 有旧版本，不能归因于来源不存在。
另一断点：Lookup 取得原 PyPI 元数据便停止；包上传时间仍不是发布日期。
首次未设置浏览器 User-Agent 的只读请求为 HTTP 403；改用现有通用正文读取器的
Mozilla/5.0 后取得原文。只为此官方页面使用该已有传输方式，不做权限或策略豁免。

## 冻结的来源合同及实现

只有单一、精确三段版本且明确询问发布日期时，官方计划将版本定向视图排在
PyPI 之前；没有版本、版本家族、预发布/扩展后缀不生成该日期视图。
旧 PyPI/通用 release-notes 地址仍在 registry，兼容已有 handoff，不自动补旧记录。

`?version=0.115.0` 是本地 reader selector，**不是官网日期 API**。
实际 HTTP 读取仍是原官方 release-notes URL，严格检查最终地址未变化；
保留 10 秒单次读取、2 MB 原 transport 上限、原压缩处理和归一正文字符上限。
返回定向视图地址，source_binding 保留真实 heading anchor 的 record_url。

新 `fastapi_release` 适配器只在原可信 native 读取边界执行：

- 精确官方 host/path/selector、唯一 Release Notes - FastAPI title、唯一 article/h1；
- article 直属唯一目标 h2；不采用 TOC、正文相似字符串、相邻版本或子标题；
- 标题完整匹配 `精确版本 (ISO日期)`，日期日历合法且原 anchor 一致；
- 重复目标标题、冲突日期、错项目、缺版本区段或缺 anchor 均 fail-closed；
- 从原 reader document 定位唯一 heading span，保留 payload hash、可见正文 hash、
  原 quote/span/read_id、目标版本以及项目来源结构；字段归一后另保留字段 span/hash。

只投影 project / version / release_date 三个原字段；没有从 PyPI 上传日期推断。
沿用原 native identity、Lookup 终态与 official-field publication 验证器。
不修改通用身份匹配、日期 relation binder、Claim/Evidence/Gate、cursor/schema、
qualified judge 或 Deep-4B。不是普通文字出现版本就获得资格。

## 集中负控与回归

27 项新测试包含旧版本在 6,000 字之后的正例，错项目/相邻版本/家族/预发布、
私有或伪造地址、TOC/prose、上传/更新时间、重复/冲突/非法日期、缺 anchor、
损坏正文 hash/transport hash/字段 span、错误 source_version、字符超限、
一读完成且无额外搜索、模型 prose 不得通过原发布路径。

命名影响集 `fastapi_release_binding` 含 12 文件；L2 research-presentation-v1
包含完整影响集和已有研究展示/Standard/Deep/审计/恢复栈。
首轮影响 334 PASS / 10 FAIL：旧负控取第一次 read，新的精确 notes 读取失败后
存在有效 PyPI fallback，负控篡改的是已失败记录。修正为篡改真实成功的 native
身份记录，保留所有拒绝条件；修正后的 terminal + 新测试 100 PASS。
类型检查先发现 tuple 固定长度推断新增 1 条，显式 tuple[str, ...] 后 NEW0
（current122/baseline128/resolved6）。不因可定位 fixture 或类型注解修改重复 L3。
最终命名 L2 **869 PASS / 394.43 秒**，包含全部影响集及修正后的负控；
Ruff 全 src/tests/tools、新文件 format、mypy baseline NEW0、diff-check PASS。
已有 legacy 未格式化文件不做整文件重排。未触发 L3：只扩已有官方 source adapter，
没有共享模型/Schema/cursor/生产权威切换或无法局部解释的行为漂移。

## 固定真实重放与只读审计

执行前 registry 保存原请求、base、两个生产文件 hash；只运行原 S5/N3 各一次。
无手动 handoff、Deep trigger、数据库写入或测试捷径。独立 SQLite/HTTP/SSE
真实路径调用相同生产代码；服务已关闭，审计前后 DB 字节不变。

| 样本 | 持久 run / version | 原终态 | 取得字段 | recovery耗时 |
| --- | --- | --- | --- | --- |
| S5 | web_lookup_1e50924b370d4317826915f4d78ad274 / 3 | VERIFIED / requested_claims_bound | FastAPI / 0.136.0 / 2026-04-16 | 4.172 秒 |
| N3 | web_lookup_6a7241f0946547caa226aa6852b28cdf / 3 | 同上 | FastAPI / 0.115.0 / 2024-09-17 | 4.484 秒 |

每例 24 项，共 48 PASS：原 terminal/identity/publication 验证、原 HTML 再解析、
transport/解码/可见正文/字段/正式答案 hash、原 span/heading、精确身份、同版快照、
thread/turn/run、冻结预算、模型 prose 隔离及无多余 child。
一物理 read、零 web_search；official_resolve 在原预算账内计 1 次 query，
不能称为零查询。归一正文 58 字；0 answer_generation_calls。

简单问题自然 Lookup 完成，无需 Standard/Deep，这不是绕过升级资格。
本次通过的只有上述确定性官方字段，不包括性能、机制或泛化语义研究结论。
API 中字段已走正式发布路径，但未观测浏览器首次可用内容时间，
两例 TTUV 仍 **NOT_OBSERVED**；4.172/4.484 是 recovery 耗时，不是 TTUV/p95。
此前真实 Deep 完成、进程重启与 S1 TTUV 证据保留，不借本轮替代或重复。

证据目录 `D:/study-agent-validation/reading-notebook-ui-evidence/r6c-fastapi-date-binding/`：
原 HTML、source-trace、预登记、实际 SSE/GET/DB、source_binding、原验证器 audit、
初始失败与最终回归日志、服务关闭和 closeout-state。

## 边界与唯一下一批

原 Lookup/Standard/Deep 时间、查询、读取与发布权限冻结；无 A 线 durable learning
或另一窗口 UI 改动；未 push/PR/CI。这个本地来源闭环可以独立关闭，RP-1 仍 NO-GO。
**唯一下一完整批次：字段级研究 claim 单元合同与覆盖追踪**。
先利用已有 S3/S5/N3 持久记录说明整句 claim 的 required_units 空数组与未回答字段
如何影响停止及审计，定义可追溯问题单元/证据覆盖合同再决定窄修；
不默认为已经授权 qualified judge 或扩大 Deep-4B 发布门，不追加游戏/UI样本或预算。
