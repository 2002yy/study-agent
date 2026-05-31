# Career Tech Stack & Game Development Trends

> Updated: 2026-05-31
>
> Purpose: 为个人求职、项目规划和简历包装提供技术路线参考。本文分为两部分：国内软件就业热门技术栈，以及游戏开发方向风向与学习路线。

---

## 1. Executive Summary

当前更适合采用“双主线 + 一条兴趣线”的准备方式：

```text
就业主线：Java 后端 / 后端工程化
差异化主线：Python + AI 应用 / Agent 工程
兴趣与展示线：Godot / Unity / Unreal 游戏开发工程化
```

建议不要把求职完全押在纯算法岗、纯游戏客户端或纯 Prompt 方向。更稳的定位是：

> 后端开发 / AI 应用开发 / Python 工程化 / Java 后端开发，游戏开发作为工程能力和兴趣项目的补充展示。

---

## 2. Domestic Employment Tech Stack Priority

### 2.1 Tier 1 — Must Prepare

| Direction | Stack | Why it matters |
|---|---|---|
| Java Backend | Java 17/21, Spring Boot, Spring Cloud, MyBatis/JPA, MySQL, Redis, MQ, Linux, Docker | 国内企业系统、政企、金融、制造业数字化、中后台岗位仍大量使用 Java 生态 |
| Python + AI Application | Python, FastAPI, OpenAI-compatible API, RAG, Agent, Embedding, Vector DB, document parsing, logging, cache, CI | 大模型应用从“玩 prompt”转向工程落地，Study Agent 可以直接贴合该方向 |
| TypeScript Frontend / Full-stack | TypeScript, Vue 3 / React, Vite, Element Plus / Ant Design, Axios, testing | 前后端联调、AI 产品界面、管理后台和可视化展示都需要基础前端能力 |
| Engineering Foundation | Linux, Git, Docker, GitHub Actions, logging, testing, security basics | 面试和项目展示都越来越看重工程闭环，而不是只会写局部功能 |

Recommended baseline:

```text
Java / Spring Boot / MySQL / Redis / MQ / Linux / Docker
+
Python / FastAPI / LLM API / RAG / Agent / document parsing
+
Vue3 or React / TypeScript
+
CI / testing / logging / security / deployment
```

---

### 2.2 Tier 2 — Valuable but Not First Priority

| Direction | Stack | Recommended Positioning |
|---|---|---|
| Go + Cloud Native | Go, Gin, gRPC, Protobuf, Docker, Kubernetes, Prometheus | 第二后端语言；适合云原生、平台、基础设施岗位 |
| C++ / Systems | C++17/20, Linux, CMake, multithreading, networking, memory, GDB | 系统、游戏引擎、数据库内核、音视频、基础软件方向；门槛高但含金量高 |
| Data / ML Engineering | PyTorch, SQL, pandas, Airflow, MLflow, model serving | 与 LiteCDNet、AI 工程化衔接，但不建议只包装成纯算法岗 |
| Mobile / HarmonyOS | Android/Kotlin, ArkTS, HarmonyOS, DevEco Studio | 特定生态机会，适合投移动端、IoT、华为生态相关岗位 |

---

## 3. Why AI Application Engineering Matters

AI 相关岗位的重点正在从“会不会调用模型”转向：

- 能否把 LLM 接入真实业务流程
- 能否做 RAG、文档解析、上下文管理和工具调用
- 能否处理成本、延迟、日志、失败重试和安全边界
- 能否让用户确认写入、回滚和追溯来源
- 能否支持多模型、多 Provider、私有化或本地模型

Study Agent 已经具备较好的项目包装基础：

| Existing Capability | Career Value |
|---|---|
| Multi-provider LLM client | 对应 AI 应用开发 / 大模型应用工程 |
| Markdown long-term memory | 对应上下文工程、记忆管理、个人知识库 |
| News pipeline + source tracing | 对应联网检索、信息溯源、RAG 前置链路 |
| Safe writer + backups | 对应本地数据可靠性与安全写入 |
| CI + tests + packaging guards | 对应工程质量意识 |
| Streamlit UI | 原型展示能力；后续可升级为 FastAPI + Vue/React |

Next upgrade direction:

```text
Streamlit prototype
  -> FastAPI service
  -> Vue/React frontend
  -> RAG document QA
  -> Docker deployment
  -> CI + tests + demo screenshots
```

---

## 4. Game Development Trends

### 4.1 AI-assisted Game Production Is Becoming Normal, but Controversial

A recent Google Cloud / Harris Poll survey reported that a very high share of developers were already using AI agents in game workflows, especially for repetitive tasks and content/code/audio/video assistance. At the same time, GDC-related surveys and industry reporting show stronger backlash from artists, writers and designers, mostly around copyright, originality, job displacement and quality control.

Practical interpretation:

```text
AI is useful for:
- prototype generation
- code assistant / refactoring
- test case generation
- localization drafts
- content ideation
- level design brainstorming
- asset variation exploration

AI is risky for:
- replacing core creative direction
- generating unreviewed production code
- shipping legally uncertain assets
- creating systems the team cannot maintain
```

For personal projects, AI should be used as a productivity amplifier, not as a replacement for understanding engine architecture, gameplay loops, state management and performance.

---

### 4.2 Premium PC / AA / Indie Games Still Have Opportunity

The success of premium PC and console titles, including Chinese high-budget games such as Black Myth: Wukong, shows that the market is not only about mobile live-service games. High-quality single-player, AA, indie and culturally distinctive games can still break through.

Practical interpretation:

```text
Small team opportunity:
- distinctive core mechanic
- polished game feel
- strong art direction
- clear demo loop
- Steam-friendly presentation
- complete tutorial + trailer + screenshots

Hard part:
- content volume
- performance polish
- controller / keyboard support
- save system
- localization
- store page and community operation
```

For BallWar / Godot projects, this means the right target is not “become a huge commercial game immediately,” but:

> make a polished, readable, testable, replayable small game prototype that proves engineering and design ability.

---

### 4.3 Mobile, Mini Games and Live Operations Remain Important in China

国内游戏商业化仍然高度重视移动端、小游戏、买量、活动运营、留存和长线内容。纯客户端开发能力不够，很多岗位会要求理解：

- 活动系统
- 用户留存
- 数据埋点
- A/B test
- 热更新
- 多端适配
- 资源包体控制
- 支付和合规流程
- 反外挂 / 风控 / 内容安全

Practical interpretation:

```text
Game developer ≠ only gameplay programmer.

More employable profiles:
- gameplay + tools
- client + performance optimization
- game backend + operations systems
- technical artist + shader/VFX tools
- data-aware game engineer
- AI-assisted content pipeline engineer
```

---

### 4.4 Engine Direction: Unity, Unreal and Godot Have Different Job Value

| Engine | Best For | Job Market Value | Learning Advice |
|---|---|---|---|
| Unity | mobile games, casual games, indie, 2D/3D, cross-platform | 国内岗位仍多，尤其移动端和中小项目 | 学 C#、UGUI/UI Toolkit、Addressables、性能优化、资源管理 |
| Unreal Engine | 3A, high-end 3D, action games, cinematic, virtual production | 高端 3D、主机/PC、技术美术和 C++ 岗位价值高 | 学 C++、Blueprint、Gameplay Ability System、渲染、网络同步 |
| Godot | indie, 2D, lightweight prototypes, open-source, education | 国内岗位少，但展示工程能力很好 | 适合个人项目、架构训练、性能测试、玩法验证 |
| Cocos / Laya | mini games, web games, lightweight mobile | 国内小游戏生态相关 | 若投小游戏/商业化团队，可补 TypeScript + Cocos Creator |

For the current user project stack:

```text
Godot / BallWar = excellent for portfolio and engineering demonstration.
Unity = better for domestic game client job matching.
Unreal = better for high-end 3D / technical art / engine-facing direction.
```

Recommended strategy:

```text
Keep Godot as personal engineering project.
Add one small Unity demo if applying to game client roles.
Learn Unreal basics only if targeting high-end 3D, action games, or engine/C++ roles.
```

---

### 4.5 Game Backend and Tooling Are Often More Employable Than Pure Gameplay

Game companies need more than gameplay code. For employability, these directions are practical:

| Role | Stack |
|---|---|
| Game Client | Unity/C#, Unreal/C++, Godot/GDScript, UI, animation state, resource loading, performance |
| Game Backend | Java/Go/C++, MySQL, Redis, MQ, gateway, room/matchmaking, leaderboard, inventory, payment callbacks |
| Tools Engineer | Python, C#, editor plugins, asset pipeline, batch import/export, automation |
| Technical Artist | Shader, VFX, material pipeline, animation, profiling, Unity/Unreal render pipeline |
| QA Automation / Test Dev | Python, automation, replay tests, crash logs, performance benchmarks |
| Data / LiveOps Engineer | SQL, event tracking, retention, funnel, A/B test, dashboard |

For job stability, a strong path is:

```text
Java backend / Go backend
+
Game domain systems: matchmaking, inventory, leaderboard, activity, battle pass, mail, logs
```

This lets you apply to both general backend and game backend roles.

---

## 5. How to Position Existing Projects

### 5.1 Study Agent

Position as:

> AI application engineering project with multi-provider LLM access, context-tier memory, source-traced web search and safe local persistence.

Best target roles:

- AI 应用开发
- Python 后端
- Agent 工程
- 大模型应用开发
- 后端开发 with AI experience

Next upgrades:

```text
FastAPI API layer
RAG document upload
Vue/React frontend
Dockerfile
online demo screenshots
more tests around provider failure and memory write rollback
```

---

### 5.2 BallWar / Godot

Position as:

> A Godot 2D strategy/action prototype focused on gameplay systems, UI layout, save/restore flow, event roulette, performance constraints and regression tests.

Best target roles:

- 游戏客户端开发助理 / 实习
- 工具型游戏开发
- 独立游戏工程展示
- 测试开发 with game/performance awareness

Next upgrades:

```text
README with GIF/video
input/control tutorial
performance benchmark table on MX330
save/load test matrix
event system architecture diagram
one polished 3-minute gameplay loop
exported Windows build
```

If applying to game client roles, add:

```text
Unity small demo:
- player control
- UI panel
- save/load
- object pool
- simple combat or tile system
- profiler screenshot
```

---

### 5.3 LiteCDNet

Position as:

> Lightweight remote sensing change detection model with accuracy-efficiency tradeoff, ablation experiments and deployment-oriented model design.

Best target roles:

- AI algorithm assistant / CV-related intern
- Python / PyTorch engineering
- research-oriented undergraduate project

Risk:

```text
Pure algorithm roles are competitive.
Use LiteCDNet as technical depth evidence, not the only job direction.
```

---

## 6. Recommended 8-week Preparation Plan

### Weeks 1-2: Backend Employment Baseline

```text
Java 17/21
Spring Boot REST API
MySQL CRUD + indexes
Redis cache
JWT auth
Docker Compose
basic unit tests
```

Output:

```text
A small backend project with README, API docs, database schema and Docker startup.
```

### Weeks 3-4: AI Application Upgrade

```text
FastAPI wrapper for Study Agent
LLM provider abstraction cleanup
RAG document upload
source tracing
error handling
logging
Dockerfile
```

Output:

```text
Study Agent becomes a service-style AI app, not only a Streamlit prototype.
```

### Weeks 5-6: Frontend / Full-stack Display

```text
Vue3 or React
TypeScript
login mock
chat page
file upload page
memory management page
API integration
```

Output:

```text
A presentable full-stack AI assistant demo.
```

### Weeks 7-8: Game Portfolio Polish

```text
BallWar README polish
GIF / short video
architecture diagram
performance benchmark
save/load regression tests
one stable exported build
```

Optional:

```text
Unity mini-demo for domestic game client job matching.
```

---

## 7. Resume Keywords

### General Backend + AI Application

```text
Java, Spring Boot, MySQL, Redis, Docker, Linux, GitHub Actions,
Python, FastAPI, OpenAI-compatible API, RAG, Agent, Context Engineering,
Vue3/React, TypeScript, RESTful API, CI/CD, logging, testing
```

### Game Development Add-on

```text
Godot, GDScript, Unity, C#, Unreal Engine, C++, object pooling,
state machine, save/load system, UI layout, performance profiling,
game event system, gameplay loop, tool pipeline, automated regression tests
```

### Best Self-positioning

```text
后端开发 / AI 应用开发 / Python 工程化 / Java 后端开发
补充方向：游戏客户端工程 / 游戏工具开发 / 游戏后端
```

---

## 8. Source Notes

This document uses public reports and industry signals available around 2025-2026. Important references include:

- WSJ report on China encouraging AI adoption while managing employment pressure.
- arXiv study based on BOSS Zhipin job postings about ChatGPT-related skill demand in China.
- Reuters report on Google Cloud / Harris Poll survey about AI agents in game development.
- GDC-related State of the Game Industry coverage on layoffs, live-service pressure and generative AI sentiment.
- Newzoo-related market reporting on 2025 global game revenue and PC/mobile performance.
- Financial Times coverage of Black Myth: Wukong and Chinese AAA ambitions.
- Tencent Hunyuan-Game research paper on AI-assisted game asset and video generation.
- Public information on games such as Black Myth: Wukong, Love and Deepspace, Wuthering Waves and Genshin Impact for market-pattern examples.

The recommendations are not meant as market guarantees. They are a practical route for a CS undergraduate with existing projects in AI application, computer vision research and Godot game development.
