# CI：Playwright 容器化与拆分门禁（历史设计方案 + 实际验收结果）

> **状态：已实施、已验收（2026-10-27）。**
> 本文保留获批时的原始设计决策（§1–§7），并补记实际交付、证据与未完成事项（§0、§6、§8、§9）。
> 设计基线：`main = 5b0acbb7656e113ab8737b4e4e633aaee21a4bcf`。
> 验收基线：`main = 346e254736c5b17d3d5087edcb244ab5b9b55f04`。
> 关联：S1 安全修复在 #289，与 CI 改造分开评审；两者的 Windows 验收证据见 §8。

## 0. 实际交付与验收

| 阶段 | 计划 | 实际交付 | 状态 |
| --- | --- | --- | --- |
| M0 | 旧作业改名 `legacy`，汇总作业承接 `test` | #291 已合并（`ci: M0 rename and aggregate`）：`test` 名称安全交接，保护配置若引用 `test` 不中断 | ✅ 完成 |
| M1 | 拆分 `classify/backend/frontend/browser`，容器化浏览器作业 | #292 已合并（`ci: M1 part 1 - whole-job gate for the split`）：五作业拆分 + `playwright:v1.62.1-noble` 容器 + 步骤级门禁 + 假绿负控 | ✅ 完成 |
| M2 | 删除旧安装链（`legacy` 与运行期 apt/浏览器安装） | 随 M1 part 2 一并完成：作业图已是 `classify → backend/frontend/browser → test`，工作流内不再出现 `playwright install` 或 apt 安装段；无需另开分支 | ✅ 完成（并入 #292） |
| main 验收 | 合并后 main 本身必须在五作业基线上为绿 | `346e2547`，run [40473062649](https://github.com/2002yy/study-agent/actions/runs/40473062649)（`event=push`）`conclusion=success`：`classify` / `backend` / `frontend` / `browser` / **`test`** 全部成功 | ✅ 通过 |

### 0.1 假绿负控（已执行，证据可复现）

| 实验 | 变异 | run / SHA | 观察 |
| --- | --- | --- | --- |
| ① 真实断言失败 | `frontend/e2e/real-stack.spec.ts` 期望一段永不存在的回复文本 | [40467042348](https://github.com/2002yy/study-agent/actions/runs/40467042348) / `0bbbf28e` | 浏览器步骤因 `continue-on-error: true` 仍显示 `success`，**步骤级门禁**判红 ⇒ `browser=failure` ⇒ `test=failure` |
| ② 必需作业被跳过 | 分类器仍要求浏览器，但 `browser` 的 `if` 被追加 `&& false` | [40469040730](https://github.com/2002yy/study-agent/actions/runs/40469040730) / `cb2b0ddc` | `classify/backend/frontend=success`、`browser=skipped`，汇总输出 `Required CI jobs did not succeed: browser:skipped`（`CI_BROWSER_REQUIRED: true`）⇒ `test=failure`；路由契约测试在该变异下仍 58 passed，红的归因唯一 |

补充：实验②早期版本（`40467107536` / `63d41e30`）的变异同时违反两条路由契约测试，导致 `backend` 也失败，隔离性不足，**结论只采用 ②b**。该版本仅作为过程记录保留。

证据归档：

- PR #292 评论：验收矩阵（[6436718301](https://github.com/2002yy/study-agent/pull/292#issuecomment-6436718301)）与最小变异 diff + 复现步骤（[6437063624](https://github.com/2002yy/study-agent/pull/292#issuecomment-6437063624)）；
- 本地归档：`D:\study-agent-validation\artifacts\m1-false-green-experiments-2026-10-27\`（三份 `.diff`）。

### 0.2 实施中修掉的真实缺陷

`browser` 作业在容器内 `HOME=/github/home`（属 `pwuser`）时 Firefox 拒绝启动：53 个产物只产出 41 个，teardown 因清单不完整而失败。已按 Playwright 官方 workaround 设 `HOME: /root`，并加路由契约测试锁住（反向变异：删掉 `HOME` 该测试即红）。

### 0.3 未完成事项

1. **S1 Windows 哨兵自动化**：真实 Windows 验收已在本机完成（§8），但还没有把它固化成可重复执行的 GitHub `windows-latest` 门禁。本机动态证据 ≠ CI 门禁。
2. **分支保护规则确认**：M0 取证时 `branches/main/protection` 返回 404（未受保护），`test` 作为唯一必需检查名目前靠约定维持。是否启用保护、以及 required checks 的精确名称，仍需仓库设置层面确认。

## 1. 问题与证据

两次精确 HEAD 的 CI 都卡在同一步，而不是代码：

| 运行 | HEAD | 结果 | 失败步骤 | 证据 |
| --- | --- | --- | --- | --- |
| `40292396246` | `7dc68d07` | success | — | 安装 41 秒 |
| `40310609353`（合并提交） | `5b0acbb7` | **failure** | `Install Playwright browsers` | 40 分钟上限；apt 只取到 130/~185 个包，单包 5–15 秒（`azure.archive.ubuntu.com`） |
| `40287246070` | `113cbdce` | failure | 同上 | 20 分钟上限，126/~185 |

结论：

- 变慢的不是仓库代码，而是 hosted runner 的 apt 镜像吞吐；同一脚本在 `7dc68d07` 只用 41 秒。
- 把 20 分钟提到 40 分钟只是把失败推迟，**不再继续加时间**。
- 不能靠跳过浏览器门禁变绿：Golden Journeys 与 real-stack 是本仓库唯一覆盖真实前端与真实服务栈的门禁。

## 2. 目标与非目标

**目标**

1. 浏览器测试不再依赖运行期 `apt-get`。
2. 门禁结构显式：哪个作业失败、哪个被合法跳过，最终 `test` 必须能区分。
3. 保留 `test` 作为唯一稳定必需检查名，且在迁移第一步就解决与旧作业的命名冲突。
4. 后端/前端与浏览器三块并行，缩短墙钟时间。

**非目标**

- 不提高超时、不放宽断言、不跳过任何浏览器套件。
- 不把 Python 测试搬进容器（`ci_scope` 依赖 `gh` CLI 与浅克隆语义）。
- 不在本方案里改任何产品代码或 S1 的安全语义。

## 3. 目标作业图

```
classify (ubuntu-24.04, gh CLI)
   ├── backend  (ubuntu-24.04)   pytest / ruff / mypy / packaging / secrets / RAG baseline
   ├── frontend (ubuntu-24.04)   npm unit tests + build        (按 classify 触发)
   └── browser  (playwright@<digest> 容器)
          ├── golden-journeys   chromium + firefox + webkit
          └── real-stack        chromium only (vite + uvicorn inside the container)
test (ubuntu-24.04, always())  ← 汇总全部必需结果，唯一必需检查
```

该图即当前 `ci.yml` 的实际结构（作业 ID 与依赖关系一致）。

## 4. 作业规格

### 4.1 `classify`

- `ubuntu-24.04`，保留 `gh` CLI。
- 复用 `tools/ci_scope.py`；分类失败或输出不可解析时**扩大为全量**（`full_scope=true`）。
- 输出字段与现状一致（`scope`、`impact_set`、`frontend_required`、`frontend_e2e_required`、`research_browser_required`、`browser_required`、`qualification_required`、`l3_eligible`、`l3_required_for_merge`）。
- 该作业失败 ⇒ `test` 失败。

### 4.2 `backend`

- `ubuntu-24.04`，无容器。
- 步骤：setup-python 3.12、`pip install -r requirements*.txt`、`pytest`、RAG baseline、ruff、packaging、detect-secrets、mypy + baseline 门。
- 工作流内**不再**包含 Playwright 安装与浏览器步骤（已随 #292 移除，M2 提前完成）。
- 诊断 artifact 使用本作业独立名称。

### 4.3 `frontend`

- `ubuntu-24.04`；`npm ci`、`npm test`、`npm run build`。
- 仅当 `frontend_required == 'true'` 时运行；否则**合法跳过**（见 §5）。

### 4.4 `browser`（容器）

- `container: mcr.microsoft.com/playwright:v1.62.1-noble@sha256:c091b21d…`（`ci.yml` 中锁 linux/amd64 manifest digest；取证见 §10）。
  - 与 `frontend/package.json` 的 `@playwright/test` 版本对齐（`1.62.1`）。
  - 作业内执行 `npx playwright --version`，把镜像内实际版本写进日志；不靠标签推断。
- 镜像已含浏览器与系统依赖 ⇒ **不执行** `npx playwright install --with-deps`。
- `npm ci` 仍然需要。
- real-stack 需要 Python 3.12 + `requirements*.txt`：容器内安装；浏览器 → Vite 5173 → uvicorn 8000 全走容器内 `127.0.0.1`，`playwright.real-stack.config.ts` 不需要改。
- **shell**：容器内默认 shell 可能不是 bash；凡使用 `set -o pipefail` / `tee` 的步骤显式 `shell: bash`。
- **HOME**：必须显式设 `HOME=/root`。默认的 `/github/home` 属 `pwuser`，Firefox 会拒绝启动，导致产物清单不完整而 teardown 失败（§0.2）。
- 两个子步骤独立记录结果：`golden_journeys`、`real_stack_browser_e2e`，各自 `continue-on-error: true`，由 `test` 判定。
- 失败时把日志尾部打到作业输出，完整日志进 artifact。

### 4.5 `test`（唯一必需检查）

- `if: always()`，`needs: [classify, backend, frontend, browser]`。
- 逐项读取 `needs.*.result`，按 §5 判定；未知状态一律失败。

## 5. 门禁真值表（核心合同）

| classify | 要求浏览器 | 要求前端 | backend | frontend | browser 两套件 | `test` |
| --- | --- | --- | --- | --- | --- | --- |
| success | 是 | 是 | success | success | 都 success | **SUCCESS** |
| success | 是 | 否 | success | **skipped（合法）** | 都 success | **SUCCESS** |
| success | 否 | 是 | success | success | **skipped（合法）** | **SUCCESS** |
| success | 否 | 否 | success | skipped（合法） | skipped（合法） | **SUCCESS** |
| success | 是 | * | success | success | 任一 failure / cancelled / 无结果 | **FAILURE** |
| success | 是 | * | success | success | 一个 success 一个 failure | **FAILURE** |
| success | * | 是 | success | failure | * | **FAILURE** |
| success | * | 是 | success | **skipped（但被要求）** | * | **FAILURE** |
| success | 是 | * | success | * | **skipped（但被要求）** | **FAILURE** |
| success | * | * | failure | * | * | **FAILURE** |
| failure / cancelled | * | * | * | * | * | **FAILURE** |
| 任一 needs 结果缺失、为空或无法解释 | * | * | * | * | * | **FAILURE** |

判定规则（写进 `tools/check_ci_outcomes.py`，可单测，不在 YAML 里堆表达式）：

1. `skipped` 仅在“`classify` 明确声明不需要该作业”时合法；被要求却 skipped ⇒ 失败（含上游失败导致的级联跳过）。
2. `test` 必须 `always()`；`needs` 默认会因上游失败而跳过下游，跳过在很多保护配置里等同通过。
3. `classify` 结果缺失 ⇒ 失败，而不是“按不需要处理”。
4. 前端与浏览器是对称的两条规则，不能只实现浏览器一侧。

实验②b 即为第 1 条与第 4 条的实机验证（§0.1）。

## 6. 迁移顺序（原计划）与实际执行

原计划要求“先解决命名冲突，再拆分，最后删除旧链”，实际按同一顺序落地：

### M0 · 安全交接必需检查（#291，已合并）

1. 先取证：`gh api repos/2002yy/study-agent/branches/main/protection` → **404，main 当时未受保护**，同样记录在案；不改配置。
2. 旧作业改名为 `legacy`，步骤暂时不动（仍含 Playwright apt 安装）。
3. 新增汇总作业 `test`：`needs: [legacy]`、`if: always()`，只按 `needs.legacy.result` 判定。
4. 名称由新汇总作业承接，保护配置若引用 `test` 不中断。
5. 本阶段允许暂时失败，但**不得为了让对比通过而放宽任何门禁**。

### M1 · 拆分执行（#292，已合并）

1. 引入 `classify` / `backend` / `frontend` / `browser`；`legacy` 在拆分落地后删除（即原 M2 的动作）。
2. `test` 的 `needs` 扩为四类，按 §5 真值表判定。
3. 覆盖合法跳过（前端/浏览器）与异常态（被要求却 skipped、单套件失败、上游失败）。
4. 两次故意假绿实验在临时分支以 `workflow_dispatch` 执行，头部未污染 PR：结果见 §0.1。

### M2 · 删除旧安装链（并入 #292）

1. `browser` 真执行、两次假绿实验都能让 `test` 变红之后，`legacy` 随拆分消失；工作流内不再出现运行期 `playwright install` 或 apt 段。
2. “删除后重新跑一次完整流程、确认必需检查名仍是 `test`”的证据：PR head `c87e276f` 的 run `40377215335`（五作业全绿、`test` 为唯一同名检查），以及合并后 main 的 run `40473062649`。

## 7. 风险与对策

| 风险 | 对策 | 实际结果 |
| --- | --- | --- |
| 容器镜像拉取失败/变慢 | 锁 digest；拉取失败 ⇒ `browser` 失败 ⇒ `test` 失败（不假绿） | 已按 digest 锁定并实测通过 |
| 容器内 Python 依赖安装慢 | 仅 real-stack 需要；可缓存 pip wheel；失败即失败，不降级跳过 | `browser` 作业整体 5 分 35 秒（含容器初始化与两套浏览器套件） |
| 容器内 PTY/缓冲差异导致 Playwright 超时 | 保持 `workers: 1`、`--reporter=line`；失败上传 trace/video | 未出现 |
| `HOME` 不适配导致 Firefox 崩溃 | 显式 `HOME=/root`，并用路由契约测试锁住 | 已修（§0.2） |
| required check 改名导致保护失效 | M0 先取证；旧作业改名 `legacy`、汇总作业承接 `test` | 已完成；保护本身仍未启用 |
| 拆分后诊断文件互相覆盖 | 每作业独立 artifact 名 | 已按作业命名 |
| 时间预算失控 | 不提高超时；容器化本身去掉了 40 分钟 apt 段 | `browser` 作业 5 分 35 秒（PR head `c87e276f`） |

## 8. Windows 启动链哨兵负控

原要求：S1 的 P1 必须证明“启动脚本不再把令牌交给前端”，且**不能**用脚本断言或现有 E2E 代替；S1 合并前必须有真实 Windows 证据（只记录 found / not-found，不贴令牌明文）。

### 8.1 已完成的真实 Windows 验收（2026-10-27，PR #289）

被测不变量：**服务端拥有 `STUDY_AGENT_API_TOKEN` 时，使用标准 Windows 启动脚本启动的 Vite，不能通过任何测试探针把这个服务端令牌公开给浏览器。**

| 实验 | 配置 | 观察 | 结论 |
| --- | --- | --- | --- |
| A | 修复版脚本 + 随机哨兵 | HTTP 模块图 150 个响应体、真实 Chromium 160 个响应体，**检出 0**；`/sessions` 经 dev proxy 与直连均 401 | ✅ 通过 |
| B | 临时恢复旧行为 `VITE_STUDY_AGENT_API_TOKEN = STUDY_AGENT_API_TOKEN` | **检出 10 个应用模块**（如 `/src/api.ts`、`/src/features/sessions/sessionApi.ts`） | ✅ 泄露被检出 |
| C | 保持 B 的旧行为，运行安全负控断言 | `SENTINEL_LEAKED_IN_10_RESPONSES`，退出码 1 | ✅ 断言失败（有牙齿） |
| D | 恢复修复版脚本，真实浏览器走 UI | 无令牌：直连 401、经 vite proxy 401、页面显示"需要访问令牌"；设置里粘贴令牌保存后弹窗消失、`/sessions` 出现 200 | ✅ 功能回归通过 |

泄露形态（脱敏）：Vite 8 dev 会把所有 `VITE_*` 注入每个被 transform 的应用模块，因此旧脚本赋值后，令牌出现在
`import.meta.env = {... "VITE_STUDY_AGENT_API_TOKEN": "<SENTINEL>"}` 中，任何浏览器都能读到。修复版在启动 Vite 前清除该名字，
探针在同等范围内检出 0 次。

过程防虚绿：每次启动前 `5173`/`8000` 监听数为 0；启动后进程创建时间晚于本次启动，`node.exe` 的父命令为
`cmd.exe /d /s /c vite --host 127.0.0.1`（即 `npm run dev -- --host 127.0.0.1`）；每次实验后清理端口、子窗口与本 worktree 进程。
证据：`D:\study-agent-validation\artifacts\s1-windows-sentinel-2026-10-27\`（探针脚本、变异 diff、启动日志、进程取证、`SUMMARY.md`）。

### 8.2 仍未完成：把它固化成 CI 门禁

上面的 A/B/C/D 是**本机动态验收**，不等于可重复执行的 GitHub 门禁。待办：

1. `windows-latest`：`npm ci`（frontend）。
2. 用 `tools/start-study-agent.ps1` 的环境语义启动 Vite，`STUDY_AGENT_API_TOKEN=<随机哨兵>`。
3. 探针请求 Vite 变换后的模块：正常路径**不含**哨兵；对照路径显式注入 `VITE_*` 后**必须包含**哨兵，否则探针无效。
4. 只打印 `found/not-found`，不打印哨兵值；探针作业结束时删除，不进入仓库。

### 8.3 相邻缺陷（与令牌安全无关，需另立 PR）

标准脚本启动完前后端后，`Test-FrontendIdentity` 仍在匹配本地化之前的英文标题
`<title>Study Agent Console</title>`，而 `frontend/index.html` 早已是 `<title>学习助手 · 学习工作台</title>`（main 同样如此）。
结果：服务已健康，脚本却在 45 秒后打印“启动失败：前端未在限定时间内通过身份检查”并 `exit 1`，也不会打开浏览器或打印启动摘要。
这正是 §8.1 中每次启动 `exit=1` 的原因；探针证据只依赖“脚本启动了这两个进程”，已用监听端口、进程创建时间与父命令行单独取证。

## 9. 已裁定与待确认

已裁定（rev 2，均已执行）：

- 两步迁移：接受；第一步解决命名冲突（§6 M0，由 #291 完成）。
- digest 来源：以 registry 返回的真实 manifest digest 为准（§10），用 `docker buildx imagetools inspect` 核实并记录平台。
- Windows 哨兵：独立 PR，S1 合并前必须有真实 Windows 证据（§8.1 已完成）。
- 容器内 Python：采用容器内安装（`setup-python` + `requirements*.txt`），`browser` 作业整体 5 分 35 秒内完成，无需预装 venv。

仍待确认：

1. 是否启用 `main` 分支保护，并把 required status check 精确设为 `test`（当前未启用，仅靠约定）。
2. 是否把 §8.1 的 Windows 验收固化为 `windows-latest` 作业（§8.2）。

## 10. 镜像 digest 取证记录（2026-10-26）

命令（本机 Docker daemon 未运行，`imagetools` 直接查询 registry，未使用本地缓存）：

```
docker buildx imagetools inspect mcr.microsoft.com/playwright:v1.62.1-noble
```

返回：

| 项 | 值 |
| --- | --- |
| 标签 | `mcr.microsoft.com/playwright:v1.62.1-noble` |
| 索引 MediaType | `application/vnd.oci.image.index.v1+json` |
| **索引 digest** | `sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e` |
| **linux/amd64 manifest** | `sha256:c091b21d9fae78c76e85cd4356431e9b018402f172a214fc7d7a5e9a7e29d8ac` |
| linux/arm64 manifest | `sha256:941cc91e5022880ac1d14ae90b476b624deb6399dbbc28d612d5d5bd7928fcbd` |
| buildx 版本 | `v0.38.1`（`0dbe87f36ed472fe36b6796c3f70b4210a731fc5`） |

实施约定：

- 工作流锁 **linux/amd64 manifest digest**（`sha256:c091b2…`），因为 runner 是 amd64；索引 digest 一并记录用于追溯。**已按此值写入 `ci.yml`。**
- 镜像内实际 Playwright 版本在作业中用 `npx playwright --version` 打印并写入日志；标签漂移不影响已锁定的作业。
