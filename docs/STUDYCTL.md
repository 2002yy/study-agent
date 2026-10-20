# studyctl

仓库内执行，无需全局安装：

```powershell
python tools/studyctl.py status --json
python tools/studyctl.py doctor --json
python tools/studyctl.py --help
python tools/studyctl.py --help --json
```

status/doctor只读本地Git与权威文件是否存在，不加载产品、模型或凭据，不联网、不运行测试。status分别统计tracked变化和Git normal模式的未跟踪条目（目录不展开，不能冒充文件总数）。doctor失败为BLOCKED，不代表产品测试失败或通过。

正常命令stdout恰好一个agent-cli-result-v1 JSON；参数错误不回显未知值，Git stderr不直接泄露。退出码：0成功，2参数错误，3前提缺失，4执行/验收失败，5超时/取消。--help默认人类文本，--help --json为机器说明。

--repo可放在子命令前后；显式--output只发布新的报告文件，拒绝覆盖，以同目录临时文件和hard link发布；--dry-run即使指定--output也不写文件。不支持hard link的文件系统保守阻断，不降级为覆盖写入。

## 测试计划（只读，不执行）

```powershell
python tools/studyctl.py test plan --base <ancestor-sha> --head HEAD --json
python tools/studyctl.py test plan --base <ancestor-sha> --include-working-tree --json
```

复用本CLI检出的ci_scope.classify和stage gate读取/解析器；policy_root明确其来源，不从任意--repo加载Python。提交范围用精确commit与祖先关系校验；rename按删除/新增两边分类。默认排除working tree并显示排除标记，显式include才纳入tracked和未跟踪文件；未提交的门配置必须显式纳入，不能暗中用排除的配置缩小测试。

命名影响集必须已登记、非空且在目标检出存在；输出原runner的argv、测试路径与L0检查，仅计划而不执行。文档/无改动只推荐L0；未知或混合范围没有唯一已登记集时返回PARTIAL/3及scope_review，保持保守扩大，不拼造新影响集。full_scope和l3_eligible不是自动执行L3的许可；L2阶段关闭/L3显式资格仍按AGENTS和原预检执行。带前后空白/换行的异常文件路径阻断，不修剪成已登记路径。

test run、research inspect和ci verify后续逐片加入，不提供默认重型测试、真实研究或付费调用。
