# CI：Playwright 容器化与拆分门禁（方案，未实施）

> 状态：**提案（rev 2）**。本文件不改变任何工作流；`ci.yml` 在方案获批并单独验证前保持现状。
> 基线：`main = 5b0acbb7656e113ab8737b4e4e633aaee21a4bcf`。
> 关联：S1 安全修复在 #289，与本文互不混合。

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

## 4. 作业规格

### 4.1 `classify`

- `ubuntu-24.04`，保留 `gh` CLI。
- 复用 `tools/ci_scope.py`；分类失败或输出不可解析时**扩大为全量**（`full_scope=true`）。
- 输出字段与现状一致（`scope`、`impact_set`、`frontend_required`、`frontend_e2e_required`、`research_browser_required`、`browser_required`、`qualification_required`、`l3_eligible`、`l3_required_for_merge`）。
- 该作业失败 ⇒ `test` 失败。

### 4.2 `backend`

- `ubuntu-24.04`，无容器。
- 步骤与现状一致：setup-python 3.12、`pip install -r requirements*.txt`、`pytest`、RAG baseline、ruff、packaging、detect-secrets、mypy + baseline 门。
- 移除 Playwright 安装与两段浏览器步骤（在 M2 执行）。
- 诊断 artifact 使用本作业独立名称。

### 4.3 `frontend`

- `ubuntu-24.04`；`npm ci`、`npm test`、`npm run build`。
- 仅当 `frontend_required == 'true'` 时运行；否则**合法跳过**（见 §5）。

### 4.4 `browser`（容器）

- `container: mcr.microsoft.com/playwright:v1.62.1-noble@sha256:<amd64 digest>`（§10 记录已核实值）。
  - 与 `frontend/package.json` 的 `@playwright/test` 版本对齐（`1.62.1`）。
  - M1 增加一步 `npx playwright --version`，把镜像内实际版本写进日志；不靠标签推断。
- 镜像已含浏览器与系统依赖 ⇒ **不执行** `npx playwright install --with-deps`。
- `npm ci` 仍然需要。
- real-stack 需要 Python 3.12 + `requirements*.txt`：容器内 `actions/setup-python@v5` 或预装 venv；浏览器→Vite 5173→uvicorn 8000 全走容器内 `127.0.0.1`，`playwright.real-stack.config.ts` 不需要改。
- **shell**：容器内默认 shell 可能不是 bash；凡使用 `set -o pipefail` / `tee` 的步骤显式 `shell: bash`。
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

## 6. 迁移顺序（含命名冲突处理）

当前 `.github/workflows/ci.yml` **只有一个作业，ID 是 `test`**。因此不能在保留旧作业的同时再新增一个也叫 `test` 的作业。迁移必须显式交接名称：

### M0 · 安全交接必需检查

1. 先取证据：`gh api repos/2002yy/study-agent/branches/main/protection`（若 404 说明未受保护，同样记录），以及仓库设置里的 required status checks 精确名称。把结果写进 PR，不改配置。
2. 旧作业 **改名为 `legacy`**，其步骤暂时一条不改（仍含 Playwright apt 安装）。
3. 新增汇总作业 `test`：`needs: [legacy]`，`if: always()`，只按 `needs.legacy.result` 判定。
4. 保护配置若引用 `test`，此时继续有效：名字由新汇总作业承接。
5. **此阶段可以暂时失败，但不得为了让对比通过而放宽任何门禁**；M0 的目标是“名称交接 + 汇总逻辑可被观察”，不是变绿。

### M1 · 拆分执行

1. 引入 `classify` / `backend` / `frontend` / `browser`，`legacy` 与它们并存但浏览器步骤开始由 `browser` 承担。
2. `test` 的 `needs` 扩为全部四类 + `legacy`（若仍保留），按 §5 真值表判定。
3. 覆盖合法跳过（前端/浏览器）与异常态（被要求却 skipped、单套件失败、上游失败）。
4. 运行两次**故意的假绿实验**（在 PR 分支，不推 main）：
   - 让 real-stack 断言故意失败 ⇒ `test` 必须红；
   - 让 classify 要求浏览器但 `browser` 被跳过 ⇒ `test` 必须红。

### M2 · 删除旧安装链

1. 确认 `browser` 真执行、两个假绿实验都能让 `test` 变红之后，删除 `legacy`（或清空其浏览器步骤）。
2. 删除后重新跑一次完整流程，确认 required check 名称仍是 `test`。

## 7. 风险与对策

| 风险 | 对策 |
| --- | --- |
| 容器镜像拉取失败/变慢 | 锁 digest；拉取失败 ⇒ `browser` 失败 ⇒ `test` 失败（不假绿） |
| 容器内 Python 依赖安装慢 | 仅 real-stack 需要；可缓存 pip wheel；失败即失败，不降级跳过 |
| 容器内 PTY/缓冲差异导致 Playwright 超时 | 保持 `workers: 1`、`--reporter=line`；失败上传 trace/video |
| required check 改名导致保护失效 | M0 先取证；旧作业改名 `legacy`、汇总作业承接 `test` |
| 拆分后诊断文件互相覆盖 | 每作业独立 artifact 名 |
| 时间预算失控 | 不提高超时；容器化本身去掉了 40 分钟 apt 段 |

## 8. Windows 启动链哨兵负控（独立 PR，S1 合并前必须取得证据）

S1 的 P1 要求证明“启动脚本不再把令牌交给前端”，且**不能**用脚本断言或现有 E2E 代替。该门禁单独建 PR，但 **#289 合并前必须有一次真实 Windows 验收证据**（PR 里附 artifact 链接，不贴令牌明文）。

1. `windows-latest`：`npm ci`（frontend）。
2. 用 `tools/start-study-agent.ps1` 的环境语义启动 Vite，`STUDY_AGENT_API_TOKEN=<随机哨兵>`。
3. 引入一个**仅测试用**的临时探针模块（导出 `import.meta.env`），请求 Vite 变换后的模块：
   - 正常路径：**不含**哨兵；
   - 对照路径：显式注入 `VITE_STUDY_AGENT_API_TOKEN=<同一哨兵>` 后**必须包含**哨兵，否则探针无效。
4. 只打印 `found/not-found`，不打印哨兵值；探针在作业结束时删除，不进入仓库。

## 9. 已裁定与待确认

已裁定（rev 2）：

- 两步迁移：接受；第一步解决命名冲突（§6 M0）。
- digest 来源：以 registry 返回的真实 manifest digest 为准（§10），用 `docker buildx imagetools inspect` 核实并记录平台。
- Windows 哨兵：独立 PR，S1 合并前必须有真实 Windows 证据（§8）。

仍待确认：

1. M0 是否接受“旧作业先改名 `legacy`、`test` 由汇总作业承接”这一最小交接（相比一次性拆分，能保留可比基线）。
2. 容器内 Python 采用 `actions/setup-python` 还是预装 venv（影响启动耗时，不影响门禁语义）。

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

- 工作流锁 **linux/amd64 manifest digest**（`sha256:c091b2…`），因为 runner 是 amd64；索引 digest 一并记录用于追溯。
- 镜像内实际 Playwright 版本在 M1 用 `npx playwright --version` 打印并写入日志；**本文件不声称已核验镜像内版本**，只记录了标签与依赖版本对齐（均为 1.62.1）。
- 若上游重新推送同标签，digest 不变性由 digest 锁定保证；标签漂移不会影响已锁定的作业。
