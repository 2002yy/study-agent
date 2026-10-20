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

首片仅基础查询；test plan/run、research inspect和ci verify后续逐片加入，不提供默认重型测试、真实研究或付费调用。
