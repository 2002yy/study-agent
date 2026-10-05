# Lookup L5：恢复正文与事实支持

本 slice 从 #174 merge `7ff7451da608775324383968b4c7ed23c5687832` 独立分支开始，不修改其16案例、生产解析器、预算或发布权限。进度唯一入口仍为 `docs/PROJECT_STATUS.md`。

## 执行门与证据等级

#174 exact-head PR CI37312220879 SUCCESS、final review PASS、expected-head合并完成。exact-main push CI37314347931首次核对仍in_progress。因此当前只准备合同与离线开发控件，不执行正式资格化、不宣布Lookup-Official QUALIFIED。

`tests/test_lookup_rescue_support.py` 的四例使用明确标为synthetic的搜索/读取传输数据。它们经过真实GeneralWebGateway → recovery → ChatService → 临时SQLite发布出口；属于运行合同回归，不能冒充真实或原始响应绑定的来源资格证据。实际网络和模型调用不得从测试意图推算。

## 冻结四例

| 案例 | 恢复正文 | 所需结论 |
| --- | --- | --- |
| 替代官方来源 | 首选官方读超时，搜索找到另一官方站点正文，含明确日期 | 检查当前合同是否允许该URL和reader提供字段绑定；不支持则明确拒绝发布 |
| 非官方直接来源 | 正文包含目标版本和日期 | 可信/直接不等于发布权；无有效逐字段绑定则拒绝发布 |
| 相关但缺字段 | 目标版本教程正文，不含日期 | 可读与read_backed允许成立；日期支持和发布必须拒绝 |
| 多正文不支持 | 邻近版本正文 | ≤2搜索阶段、≤3逻辑读、≤30秒并保留finalization reserve；拒绝不支持的事实 |

每例分别记录：传输后端调用、逻辑read、查询阶段、耗时、目标覆盖、停止原因、可用正文、请求字段支持、发布refs及摘要。确定性出口答案模型调用为零；禁止用read_backed或目标marker覆盖替代逐事实支持。后端替换是控制数据，不是新reader能力。

## 已核对的发布权限边界

核对范围绑定main7ff7451d：

- `src/web/research/official_resolver.py:valid_candidate` 只接受查询计划中注册的URL。
- `src/web/tool_gateway.py:GeneralWebGateway.read` 通用读取返回正文，不生成原生官方字段跨度。
- `src/web/research/official_publication.py:publish_official_fields` 要求注册候选、native方法、版本一致性、摘要及真实字段跨度。官方域名本身不能授权通用正文。
- `src/application/chat_service.py:complete_turn` 的现有确定性研究出口调用上述字段发布入口，并保存审计；不能绕过该出口把模型知识或相关正文作为事实。

当前已知替代官方/非官方通用正文均缺少这一路径的字段发布权限。不得为了让L5成功临时伪造official_fields、切换模型判定或放宽Gate。若正式重放确认该限制，结论应为：Lookup-Official在其主线门完成后独立合格；Generic Rescue仅恢复、发布NOT QUALIFIED。Lookup整体仍NOT CLOSED。

## 开发失败样本

首轮两个正文写为Python3.14.0，而请求为Python3.14；通用正文的精确target marker不会采纳patch后缀，因此status为provider_exhausted，不能声称read_backed。日志保留 `D:/study-agent-validation/lookup-L5-development.log`（2 failed、85 passed）。该失败来自已知通用身份边界，不是新生产回归；当前不扩大身份能力。控件正文改成请求的精确3.14，专门测已有可读性通过后是否仍拒绝无字段绑定的发布。旧失败没有被重解释为通过。

## 下一门

开发影响集 `lookup_rescue_support`：97 PASS/43.15s；Ruff全src/tests/tools及diff-check PASS。四例分别通过真实发布/保存出口验证零refs、零答案模型调用；前三例read_backed，第四例3次逻辑读有界停止。仅新增独立tests/docs/manifest，未触发生产合同变更或L3切换；#174已有完整3551/6 skip结果不重复跑。正式来源资格化仍未执行。

后续turn核对已知exact-main run37314347931及exactSHA。绿后运行独立四例的来源绑定重放/资格检查，保存明确来源provenance与真实出口审计；如原始来源不足则保持资格未完成。Standard与Deep暂不执行。
