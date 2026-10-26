# CI：Playwright 容器化与拆分门禁（方案，未实施）

> 状态：**提案**。本文件不改变任何工作流；`ci.yml` 在方案获批并单独验证前保持现状。
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

- 依赖的不是仓库代码，而是 hosted runner 的 apt 镜像吞吐；同一脚本在 `7dc68d07` 只用 41 秒。
- 把 20 分钟提到 40 分钟只是把失败推迟，**不是修复**，也不再继续加时间。
- 不能靠跳过浏览器门禁变绿：Golden Journeys 与 real-stack 是本仓库唯一覆盖真实前端与真实服务栈的门禁。

## 2. 目标与非目标

**目标**

1. 浏览器测试不再依赖运行期 `apt-get`。
2. 门禁结构显式：哪个作业失败、哪个被合法跳过，最终 `test` 必须能区分。
3. 保留 `test` 作为唯一稳定必需检查名，不制造“改名后保护失效”。
4. 后端/前端与浏览器三块并行，缩短墙钟时间。

**非目标**

- 不提高超时、不放宽断言、不跳过任何浏览器套件。
- 不把 Python 测试搬进容器（`ci_scope` 依赖 `gh` CLI 与浅克隆语义，迁移风险与本文无关）。
- 不在本方案里改任何产品代码或 S1 的安全语义。

## 3. 目标作业图

```
classify (ubuntu-24.04, gh CLI)
   ├── backend  (ubuntu-24.04)   pytest / ruff / mypy / packaging / secrets / RAG baseline
   ├── frontend (ubuntu-24.04)   npm unit tests + build        (按 classify 触发)
   └── browser  (playwright:v1.62.1-noble 容器)
          ├── golden-journeys   chromium + firefox + webkit
          └── real-stack        chromium only (vite + uvicorn inside the container)
test (ubuntu-24.04, always())  ← 汇总以上全部必需结果，唯一必需检查
```

并行收益：后端 ~29 分钟、浏览器 ~4 分钟、前端 ~1 分钟，总墙钟由“串行约 35 分钟”降到“约 30 分钟”，且不再有 apt 风险。

## 4. 作业规格

### 4.1 `classify`

- 运行环境：`ubuntu-24.04`（沿用现状，保留 `gh` CLI）。
- 复用 `tools/ci_scope.py`；分类失败或输出不可解析时，**扩大为全量**（`full_scope=true`），而不是缩窄。
- 输出：`scope`、`impact_set`、`frontend_required`、`frontend_e2e_required`、`research_browser_required`、`browser_required`、`qualification_required`、`l3_eligible`、`l3_required_for_merge`（与现状字段一致，避免下游改名）。
- 该作业失败 ⇒ `test` 失败（不能因为“没分类成功”而跳过其余检查）。

### 4.2 `backend`

- 运行环境：`ubuntu-24.04`，无容器。
- 步骤与现状一致：setup-python 3.12、`pip install -r requirements*.txt`、`pytest`、RAG baseline、ruff、packaging、detect-secrets、mypy + baseline 门。
- 移除：`Install Playwright browsers`、两段浏览器步骤。
- 保留 `pytest.log` 等诊断上传（拆到本作业自己的 artifact，避免与 browser 作业互相覆盖）。

### 4.3 `frontend`

- 运行环境：`ubuntu-24.04`。
- `npm ci`、`npm test`、`npm run build`。
- 同样不再安装浏览器。

### 4.4 `browser`（容器）

- 运行环境：`ubuntu-24.04`，`container: mcr.microsoft.com/playwright:v1.62.1-noble`。
  - 版本必须与 `frontend/package.json` 的 `@playwright/test` 一致（当前 `1.62.1`）；**最终实现时锁定 digest**（`...@sha256:<digest>`），不用 `latest`、不用浮动 tag。
- 镜像已含浏览器与系统依赖 ⇒ **不执行** `npx playwright install --with-deps`。若仍需要校验，只断言 `@playwright/test` 版本与镜像 tag 一致，不触发下载。
- Node 项目依赖仍需 `npm ci`。
- real-stack 需要 Python 3.12 + `requirements*.txt`：
  - 容器内用 `actions/setup-python@v5` 安装 3.12（镜像是 Ubuntu 基础，可用），或预装 `python3.12` + venv。
  - 浏览器（Chromium）→ Vite 5173 → 后端 8000 全部在容器内 `127.0.0.1`，与现配置一致；`playwright.real-stack.config.ts` 的 `webServer` 不需要改。
- **shell**：容器内默认 shell 可能不是 bash。所有使用 `set -o pipefail` / `tee` 的步骤显式声明 `shell: bash`。
- 两个子步骤独立记录结果：`golden_journeys`、`real_stack_browser_e2e`，各自 `continue-on-error: true`，由 `test` 判定，避免一个失败掩盖另一个。
- 失败时必须把日志尾部打到作业输出（沿用现有 `tail` 方案），完整日志进 artifact。

### 4.5 `test`（唯一必需检查）

- `if: always()`，`needs: [classify, backend, frontend, browser]`。
- 逐项读取 `needs.*.result`，按下表判定；**任何未知状态一律失败**。

## 5. 门禁真值表（核心合同）

| classify | 是否要求浏览器 | backend | frontend | browser 两个套件 | `test` |
| --- | --- | --- | --- | --- | --- |
| success | 是 | success | success | 都 success | **SUCCESS** |
| success | 否 | success | success | skipped（合法） | **SUCCESS** |
| success | 是 | success | success | 任一 failure / cancelled / 未产出结果 | **FAILURE** |
| success | 是 | success | success | 一个 success 一个 failure | **FAILURE** |
| success | * | failure | * | * | **FAILURE** |
| success | * | * | failure（当 frontend 被要求） | * | **FAILURE** |
| failure / cancelled | * | * | * | * | **FAILURE** |
| 任一 needs 结果缺失、为空或无法解释 | * | * | * | * | **FAILURE** |

实现要点（避免官方文档点名的两类假绿）：

1. **不能把 skipped 一律当成功**：只有当 `classify` 明确输出“不要求该套件”时，`skipped` 才算合法；`classify` 要求但作业 skipped（例如上游失败导致级联跳过）必须失败。
2. **`needs` 默认遇到失败会跳过下游**：`test` 必须 `always()`，否则后端失败时它直接 skipped，而 skipped 在很多保护配置里被视为通过。
3. **`test` 名称保持不变**：改动前先用
   `gh api repos/2002yy/study-agent/branches/main/protection` 或仓库设置核对现有 required status checks 的精确名称；若保护已引用 `test`，拆分后仍只引用 `test`。
4. 汇总脚本建议写成 `tools/check_ci_outcomes.py` 的扩展（已有 `REQUIRED_STEPS` 概念），把“是否要求”作为输入，而不是在 YAML 里堆条件表达式；这样门禁逻辑可单测。

## 6. 迁移与验证顺序

1. **只加不改**：先在新 PR 里加 `browser` 作业与 `test` 汇总，`backend`/`frontend` 仍跑原有步骤（Playwright 安装暂时保留但删除 `--with-deps` 的浏览器安装？——不，本步先不删，保证对比基线）。
2. 在草稿 PR 上触发一次，核对：作业图、`browser` 容器拉取时间、两个套件真实执行、`test` 的名称与结论。
3. 确认无回归后，再删除 `backend` 中的 Playwright 安装与浏览器步骤，形成最终形态。
4. 用一次**故意失败**的实验验证门禁（例如临时让 real-stack 断言的期望值错误），确认 `test` 变红；再用一次 **classify 要求但 browser 跳过** 的实验确认不会被判绿。两个实验都在 PR 分支完成，不推到 main。
5. 全绿后合并；随后让 #289 基于新 `main` 重新取一次精确 HEAD 的完整成功证据。

## 7. 风险与对策

| 风险 | 对策 |
| --- | --- |
| 容器镜像拉取失败/变慢 | 锁 digest；拉取失败 ⇒ `browser` 失败 ⇒ `test` 失败（不会假绿）；必要时只对镜像做 registry 缓存 |
| 容器内 Python 依赖安装慢 | 仅 real-stack 需要；可缓存 pip wheel（`~/.cache/pip`），失败即失败，不降级跳过 |
| 容器内 stderr/PTY 差异导致 Playwright 超时 | 保持 `workers: 1`；`--reporter=line`；失败时上传 trace/video 到 artifact |
| required check 改名导致保护失效 | 保留 `test` 名称；改动前先读保护配置并记录 |
| 拆分后诊断文件互相覆盖 | 每个作业独立 artifact 名 |
| 时间预算失控 | 不提高超时；容器化本身去掉了 40 分钟 apt 段 |

## 8. 附：Windows 启动链哨兵负控（与本文相关的独立门禁）

S1 的 P1 要求在 **Windows + Vite** 上证明“启动脚本不再把令牌交给前端”。这需要 Windows runner，不能由脚本断言或现有 E2E 代替：

1. `windows-latest`：`npm ci`（frontend）。
2. 以标准启动脚本的环境语义启动 Vite（`STUDY_AGENT_API_TOKEN=<哨兵>`，并模拟旧脚本额外注入 `VITE_STUDY_AGENT_API_TOKEN=<哨兵>` 作对照）。
3. 写一个仅测试用的临时探针模块（导出 `import.meta.env`），请求其 Vite 变换结果：
   - 正常路径：**不含**哨兵；
   - 对照路径（显式注入 VITE_）：**必须包含**哨兵，否则探针无效。
4. 结果不打印哨兵明文，只打印 `found/not-found`。

该作业可作为 `browser` 之外的第三条可选门禁；在 S1 合并前至少手动跑一次，结果记录在 PR。

## 9. 待确认

1. 是否接受“先加后删”的两步迁移（多一次 PR 提交），换取可对比的基线？
2. 镜像 digest 采用哪个来源（`docker manifest inspect` 记录到本文件）？
3. Windows 哨兵门禁是并入本 PR，还是单独第三个 PR？
