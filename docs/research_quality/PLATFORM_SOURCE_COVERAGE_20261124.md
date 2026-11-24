# 平台信源覆盖审计（2026-11-24）

审计基线为 `main@84f654ac3a805016a708b42ad1154339d4fcb8b4`。这份清单记录 Study Agent 目前的接入和用户补回的候选信源。仓库配置、历史浏览器样本、当次 Browse 样本和发布证据分别记录。2026-08-26、10-04、10-09 为用户找回的讨论时间，完整历史逐字原文仍待定位。

## 仓库现在如何检索和读取

| 能力 | 现有入口 | 覆盖边界 |
| --- | --- | --- |
| 通用网页发现 | 本地 Docker SearXNG、Bing RSS、DuckDuckGo HTML；可配置 Browse Google/Brave/Bing；可选独立 DeepSeek Search | 依赖公开索引。提供方返回的是候选链接。DeepSeek Search 的接口无浏览器会话，平台覆盖须用逐站样本验收。 |
| 平台定向发现 | `browse_sites` 调用 [站点池](../../src/web/site_pool.py)；另有 [社区证据缺口路由](../../src/web/research/facet_coverage.py) | 站点池按关键词、规则和开关挑选。默认普通检索策略为 `fallback`；站点池里的“默认启用”指进入站点池时可参加选择。 |
| 模型决策 | [ResearchDecision](../../src/web/semantic_recovery.py) 的每条查询有 `rq_id` 和 `query`；活动研究还有独立的 [域名定向](../../src/web/research/deeper_targeting.py) | 当前没有每条查询的结构化站点选择。正向 `site:` 是索引范围约束。点名站内搜索需要由 DeepSeek 判断语义，再由执行层按已知站点能力派发。 |
| 正文读取 | [通用读取器](../../src/web/tool_gateway.py)先尝试 GitHub 或已知官方元数据，再走通用文章提取，可选付费 DeepSeek Fetch；活动研究另有有界浏览器读取路径 | 登录浏览器能看到的页面需要对应入口才能读到。专用 GitHub Reader 支持仓库、文件、目录、发行版和代码搜索。Issues 的搜索卡片、公开 issue 页面和结构化评论分别验收。 |
| 发布证据 | [工具证据](../../src/web/tool_evidence.py)及 [运行时证据投影](../../src/application/research_runtime_source_evidence_context.py) | 有效链接只进入候选。读到的相关正文须通过适用的证据和发布规则。帖子和评论可以支持“某位用户报告什么”，单条样本只能证明该样本；公告和规范适合证明发布方的事实。 |
| RSS 与内容结构 | [新闻 RSS 管线](../../src/news/rss_fetcher.py)、Feed 注册表 | 支持 RSS/Atom 摘要与新闻入口。此次未在研究入口找到面向 B 站/YouTube 的字幕或视频内容适配，以及可稳定提取评论、楼中楼与评论引用的站点适配。 |

## 实现过的站点池

下表中“历史”是 2026-11-15 的样本，保留当时登录态和局限。来源为 [建站点池](https://github.com/2002yy/study-agent/commit/09c0e60c)、[搜索引擎比较](BROWSE_ENGINE_PROBE_20261115.md)、[受限站点处理](https://github.com/2002yy/study-agent/commit/c8064bc3)、[米游社及知乎](https://github.com/2002yy/study-agent/commit/d034d743)、[B 站](https://github.com/2002yy/study-agent/commit/8630798b) 和本地 `D:/study-agent-validation/site-pool-20261115/` 的各轮矩阵。矩阵包含探查失败及只抓到导航链接的旧轮次，采用最终适配与对应复测判断。

| 站点 | 路由及登录 | 历史观测与可用内容 |
| --- | --- | --- |
| B 站 | 默认，公开站内搜索 | 两次各 5 个有效视频链接；可发现视频。视频陈述、字幕和评论须独立读取。 |
| 米游社 | 默认，登录会话实测，各游戏版块 | 总 `/search` 404；星铁、原神、绝区零、崩坏三、未定事件簿走各自版块。5/5，两次；曾读到约 1452 字攻略。 |
| V2EX | 默认，配置标记需登录 | 当时登录态 5/5，结果类型为主题。当前是否仍命中独立记录。 |
| 知乎 | opt-in，需登录 | 经典卡片页 5/5；AI-only 页可无任何问题链接。评论未验收。 |
| 掘金 | 默认，站内 | 5/5，技术文章。 |
| 牛客 | 默认，站内 | 搜索由 XHR 渲染，匹配经验帖等 feed 链接。 |
| GitHub | 默认，站内 | 5/5；匹配 issue、PR、discussion。仓库专用读取另有入口。 |
| HN | 默认，HN Algolia | `query` 与 `type=story` 生效，目标为 HN story 讨论页。 |
| Hugging Face | 默认，全文搜索 | 5/5，模型等仓库链接。 |
| arXiv | 默认，站内 | 有命中样本，也有离题查询零命中；摘要页和 PDF 链接。 |
| Steam | 默认，商店搜索 | 返回游戏商品，首屏之后渲染；Steam Community 是另一个候选入口。 |
| LINUX DO | 默认，Google 域限制发现 | 原生搜索需要登录；已读到约 3523 字主题。 |
| Reddit | 默认，Google 域限制发现 | 原生搜索探查时跳登录；已读到约 2896 字帖子。 |
| Stack Overflow | 默认，Google 域限制发现 | 原生搜索进 `/nocaptcha`；Google 可找到 5 个目标问题。 |
| Chiphell | 默认，Google 域限制发现 | 原生搜索只出页脚；已读到约 4272 字主题。 |
| NGA | opt-in | 存在站点条目和结果规则，历史只识别到页脚或注册链接，未验收为可用搜索。 |
| Google / Bing / Brave | 通用搜索适配 | 四引擎样本中 Google 保留为 Browse 默认。Bing、Brave 可切换；三者 11-15 复测各有 5 个有效结果。 |
| DuckDuckGo | 默认关闭 Browse 站点 | HTML 端遇到图片挑战。 |

登录、验证或访问拒绝按正常权限处理；已配对的 Browse 使用当前会话。已为若干站点配置同域的公开搜索发现路径。搜索、正文、评论按各自的实际返回记录。2026-11-24 的 #637 已修复 Browse 0.1.5 启动：之前应用入口对 B 站、米游社、V2EX 全失败；修复后同组三站各得 5 条链接。独立普通 HTTP 样本取到 B 站视频公开元信息，米游社样本正文为空，使用浏览器取得约 3402 字。原始证据 `D:/study-agent-validation/search-comparison-20261124/platform-*.json`。

## 用户找回的历史候选

| 类别 | 国内 | 海外或通用 |
| --- | --- | --- |
| 综合问答 | 知乎、百度贴吧 | Reddit |
| 视频 | B站、抖音、快手 | YouTube |
| 社交 | 微博、小红书 | Twitter/X |
| 技术 | V2EX | GitHub |
| 游戏 | NGA、TapTap | Steam、Discord |
| 金融 | 雪球 | — |
| 招聘 | 牛客、BOSS直聘、猎聘、智联招聘 | — |
| 订阅 | RSS | RSS |
| 通用搜索 | — | Google、Bing、Brave、DuckDuckGo |

历史讨论还提到 MediaCrawler 的平台搜索、详情与评论提取，以及 Agent Reach 的多平台接入与路由。以上两者作为参考保留，未作为当前仓库的依赖或生产能力计入。

## 补充候选全表

以下是扩展表的全部平台，每个条目单列。地区、信息领域及信息价值沿用用户清单。运行时接入核对以 `main@84f654ac` 的站点池、通用网关、域名定向、[研究来源分类](../../src/web/research/deeper_targeting.py)、[新闻域名排序](../../src/news/domain_policy.py)、[文章优先级](../../src/news/article_fetcher.py)和 [Feed 注册表](../../src/news/feed_registry.py)为依据。通用索引可能收录这些平台的公开页面。

- **未见专项接入**表示在上述入口未找到平台专用配置；**域名规则**表示该域可参与排序或来源分类。两种情况下的实测列仍可以记录独立 Browse 结果。
- **未测**表示现有审计没有该项结果。零命中、离题、登录和回执不完整均直接写在对应格。下文保留查询与样本链接。
- **发布证据**对全表统一为未验收。本次确实读到的回答、帖子、摘要与模型卡，可按该类来源承担的角色送入现有证据链，需要再跑同题相关性、支撑和发布检查。标题、链接和评论容器只能作为线索。

### 全表 Browse 实测方法

全表逐条用用户已配对的 Browse 打开公开入口，保留当次页面文字和可见搜索控件的结果。在只等到页面骨架的条目上，用独立标签补等一次可见文字；访问验证和拒绝按原样记录。页面探针发出 156 次首访，另有 50 次渲染补测。90 条看到页面文字，30 条检测到搜索控件，其余详见各行状态。“页面可见”只说明探针取得页面文字，包括可能的登录提示、错误提示或导航；搜索、正文、评论三列保存单独验证过的样本。结果受本机登录会话、网络、地区、入口与渲染时间影响。

“各部委”“地方政府网站”“各游戏Wiki”“个人博客”“Telegram 公开频道”“专业评测频道”等是集合项，本轮各选表中链接作代表。候选在原清单重复出现时仍保留。检测记录只含公开入口、状态与计数。新增公开页面审计和定向探针费用 ¥0。

### 国内

| 信息领域 | 平台 | 信息价值 | 仓库接入 | 免费 Browse 发现 | 正文或详情 | 评论或回复 | Browse 页面实测 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 综合问答 | 知乎 | 经验和专业解释 | 站点池 · 原生，opt-in | 登录后 17 个内容链接 | 回答约 1011 字 | 未提取 | 页面可见，见搜索控件 · [入口](https://zhihu.com) |
| 综合问答 | 百度知道 | 经验和专业解释 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://zhidao.baidu.com) |
| 大众论坛 | 百度贴吧 | 长尾讨论与小众兴趣 | 未见专项接入 | 10 个帖子链接，前排离题 | 未读到相关正文 | 未测 | 页面可见，见搜索控件 · [入口](https://tieba.baidu.com) |
| 大众论坛 | 豆瓣小组 | 长尾讨论与小众兴趣 | 未见专项接入 | 小组原生搜索 Obsidian，未匹配话题 | 未测 | 未测 | 页面可见 · [入口](https://douban.com/group) |
| 生活消费 | 小红书 | 实际体验和消费决策 | 未见专项接入 | 站内页未匹配到笔记 | 未测 | 未测 | 页面可见 · [入口](https://xiaohongshu.com/explore) |
| 生活消费 | 什么值得买 | 实际体验和消费决策 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见，见搜索控件 · [入口](https://smzdm.com) |
| 生活消费 | 大众点评 | 实际体验和消费决策 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://dianping.com) |
| 社会热点 | 微博 | 事件传播与公众反馈 | 未见专项接入 | 跳转登录 | 未测 | 未测 | 页面可见，见搜索控件 · [入口](https://weibo.com) |
| 社会热点 | 今日头条 | 事件传播与公众反馈 | 未见专项接入 | 未测 | 未测 | 未测 | 浏览器未返回可核验页面 · [入口](https://toutiao.com) |
| 视频 | B站 | 演示、教程、评论 | 站点池 · 原生 | 28 个视频链接 | 标题可读，字幕未测 | 未提取 | 页面可见 · [入口](https://bilibili.com) |
| 视频 | 抖音 | 演示、教程、评论 | 未见专项接入 | 未匹配视频，回执不完整 | 未测 | 未测 | 页面可见，见搜索控件 · [入口](https://douyin.com) |
| 视频 | 快手 | 演示、教程、评论 | 未见专项接入 | 未匹配视频链接 | 未测 | 未测 | 页面可见 · [入口](https://kuaishou.com) |
| 视频 | 西瓜视频 | 演示、教程、评论 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://ixigua.com) |
| 私域与自媒体 | 微信公众号 | 行业文章与机构信息 | 未见专项接入 | 搜狗微信与 Google 均未取得链接 | 未测 | 未测 | 页面可见 · [入口](https://weixin.sogou.com) |
| 私域与自媒体 | 腾讯新闻号 | 行业文章与机构信息 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见，见搜索控件 · [入口](https://news.qq.com) |
| 软件开发 | CSDN | 中文开发经验 | 域名规则 · 新闻排序、研究分类 | 站内 26 个文章链接，主题命中 | 未测 | 未测 | 页面可见，见搜索控件 · [入口](https://blog.csdn.net) |
| 软件开发 | 博客园 | 中文开发经验 | 域名规则 · 研究分类 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://cnblogs.com) |
| 软件开发 | 掘金 | 中文开发经验 | 站点池 · 原生 | 20 个文章链接 | 文章约 3256 字 | 未提取 | 页面可见，见搜索控件 · [入口](https://juejin.cn) |
| 软件开发 | SegmentFault | 中文开发经验 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见，见搜索控件 · [入口](https://segmentfault.com) |
| 软件开发 | 开源中国 | 中文开发经验 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://oschina.net) |
| 软件开发 | V2EX | 中文开发经验 | 站点池 · 原生 | 跳到版块页，前五离题 | 未读到相关正文 | 未测 | 页面可见 · [入口](https://v2ex.com) |
| 开源 | Gitee | 国内开源项目 | 域名规则 · 研究分类 | 仓库原生搜索 SQLite，2 个匹配链接 | 未测 | 未测 | 页面可见 · [入口](https://gitee.com) |
| 开源 | GitCode | 国内开源项目 | 域名规则 · 研究分类 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://gitcode.com) |
| AI 与科技 | 机器之心 | 技术进展与应用 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://jiqizhixin.com) |
| AI 与科技 | 量子位 | 技术进展与应用 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://qbitai.com) |
| AI 与科技 | 新智元 | 技术进展与应用 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://aiera.com.cn) |
| AI 与科技 | InfoQ | 技术进展与应用 | 域名规则 · 新闻排序 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://infoq.cn) |
| AI 与科技 | 少数派 | 技术进展与应用 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://sspai.com) |
| 商业科技 | 36氪 | 企业动态与行业调查 | 信源名称规则 · 文章排序 | 未测 | 未测 | 未测 | 浏览器未返回可核验页面 · [入口](https://36kr.com) |
| 商业科技 | 虎嗅 | 企业动态与行业调查 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://huxiu.com) |
| 商业科技 | 钛媒体 | 企业动态与行业调查 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见，见搜索控件 · [入口](https://tmtpost.com) |
| 商业科技 | 晚点LatePost | 企业动态与行业调查 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://latepost.com) |
| 财经新闻 | 财新 | 财经报道 | 域名规则 · 新闻排序 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://caixin.com) |
| 财经新闻 | 第一财经 | 财经报道 | 域名规则及 RSSHub 默认 Feed | 未测 | 未测 | 未测 | 页面可见 · [入口](https://yicai.com) |
| 财经新闻 | 经济观察报 | 财经报道 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://eeo.com.cn) |
| 财经新闻 | 证券时报 | 财经报道 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://stcn.com) |
| 金融投资 | 雪球 | 市场观点及讨论 | 未见专项接入 | 未匹配讨论链接 | 未测 | 未测 | 页面可见，见搜索控件 · [入口](https://xueqiu.com) |
| 金融投资 | 东方财富 | 市场观点及讨论 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见，见搜索控件 · [入口](https://eastmoney.com) |
| 金融投资 | 同花顺 | 市场观点及讨论 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://10jqka.com.cn) |
| 游戏综合 | NGA | 攻略、评测和反馈 | 站点池 · 原生，opt-in | 未匹配帖子 | 未测 | 未测 | 页面可见 · [入口](https://bbs.nga.cn) |
| 游戏综合 | TapTap | 攻略、评测和反馈 | 未见专项接入 | 站内未匹配帖子 | 已知攻略仅标题可见 | 未测 | 页面可见 · [入口](https://taptap.cn) |
| 游戏综合 | 游民星空 | 攻略、评测和反馈 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://gamersky.com) |
| 游戏综合 | 游侠网 | 攻略、评测和反馈 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://ali213.net) |
| 游戏综合 | 3DM | 攻略、评测和反馈 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://3dmgame.com) |
| 游戏综合 | 机核 | 攻略、评测和反馈 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见，见搜索控件 · [入口](https://gcores.com) |
| 游戏专项 | 米游社 | 机制与玩家研究 | 站点池 · 原生，按游戏版块 | 原神版 21 个帖子链接 | V5.2 攻略约 3251 字 | 未提取 | 页面可见 · [入口](https://miyoushe.com) |
| 游戏专项 | 黑盒 | 机制与玩家研究 | 未见专项接入 | 未测 | 未测 | 未测 | net::ERR_CERT_COMMON_NAME_INVALID · [入口](https://heybox.cn) |
| 游戏专项 | 小黑盒 | 机制与玩家研究 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://xiaoheihe.cn) |
| 游戏专项 | 各游戏Wiki | 机制与玩家研究 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://genshin-impact.fandom.com/wiki/Genshin_Impact_Wiki) |
| 数码硬件 | Chiphell | 实测、故障、体验 | 站点池 · Google 同域 | 7 个主题链接 | 匹配段落约 316 字 | 15 个有内容的帖子区节点，含楼主 | 页面可见，见搜索控件 · [入口](https://chiphell.com) |
| 数码硬件 | 酷安 | 实测、故障、体验 | 未见专项接入 | 未测 | 未测 | 未测 | 浏览器未返回可核验页面 · [入口](https://coolapk.com) |
| 数码硬件 | IT之家 | 实测、故障、体验 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见，见搜索控件 · [入口](https://ithome.com) |
| 数码硬件 | 中关村在线 | 实测、故障、体验 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://zol.com.cn) |
| 求职招聘 | 牛客 | 招聘与面经 | 站点池 · 原生 | 13 个内容链接 | 主区约 2636 字，命中笔试 | 1 个容器，条目未核实 | 浏览器未返回可核验页面 · [入口](https://nowcoder.com) |
| 求职招聘 | BOSS直聘 | 招聘与面经 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见，见搜索控件 · [入口](https://zhipin.com) |
| 求职招聘 | 猎聘 | 招聘与面经 | 未见专项接入 | 未测 | 未测 | 未测 | 浏览器未返回可核验页面 · [入口](https://liepin.com) |
| 求职招聘 | 智联招聘 | 招聘与面经 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见，见搜索控件 · [入口](https://zhaopin.com) |
| 求职招聘 | 应届生求职网 | 招聘与面经 | 未见专项接入 | 未测 | 未测 | 未测 | 浏览器未返回可核验页面 · [入口](https://yingjiesheng.com) |
| 学术研究 | 知网 | 中文学术资料 | 未见专项接入 | 未测 | 未测 | 未测 | 无可核验回执 · [入口](https://cnki.net) |
| 学术研究 | 万方 | 中文学术资料 | 未见专项接入 | 未测 | 未测 | 未测 | 无可核验回执 · [入口](https://wanfangdata.com.cn) |
| 学术研究 | 维普 | 中文学术资料 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见，见搜索控件 · [入口](https://cqvip.com) |
| 学术研究 | 科学网 | 中文学术资料 | 未见专项接入 | 未测 | 未测 | 未测 | 浏览器未返回可核验页面 · [入口](https://sciencenet.cn) |
| 政府政策 | 中国政府网 | 政策原文与流程 | 未见专项接入 | Google 探针连接中断 | 未测 | 未测 | 浏览器未返回可核验页面 · [入口](https://gov.cn) |
| 政府政策 | 各部委 | 政策原文与流程 | 未见专项接入 | 未测 | 未测 | 未测 | net::ERR_CONNECTION_CLOSED · [入口](https://miit.gov.cn) |
| 政府政策 | 地方政府网站 | 政策原文与流程 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见，见搜索控件 · [入口](https://shanghai.gov.cn) |
| 综合新闻 | 新华网 | 新闻与官方信息 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见，见搜索控件 · [入口](https://news.cn) |
| 综合新闻 | 人民网 | 新闻与官方信息 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://people.com.cn) |
| 综合新闻 | 央视新闻 | 新闻与官方信息 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://news.cctv.com) |
| 综合新闻 | 澎湃新闻 | 新闻与官方信息 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://thepaper.cn) |
| 综合新闻 | 南方周末 | 新闻与官方信息 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://infzm.com) |
| 汽车 | 汽车之家 | 车型实测与车主反馈 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见，见搜索控件 · [入口](https://autohome.com.cn) |
| 汽车 | 懂车帝 | 车型实测与车主反馈 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见，见搜索控件 · [入口](https://dongchedi.com) |
| 汽车 | 易车 | 车型实测与车主反馈 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://yiche.com) |
| 法律 | 国家法律法规数据库 | 法律原文与案例 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://flk.npc.gov.cn) |
| 法律 | 中国裁判文书网 | 法律原文与案例 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://wenshu.court.gov.cn) |
| 企业信息 | 国家企业信用信息公示系统 | 企业登记与经营信息 | 未见专项接入 | 未测 | 未测 | 未测 | net::ERR_CONNECTION_CLOSED · [入口](https://gsxt.gov.cn) |
| 企业信息 | 企查查 | 企业登记与经营信息 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://qcc.com) |
| 企业信息 | 天眼查 | 企业登记与经营信息 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://tianyancha.com) |

### 海外

| 信息领域 | 平台 | 信息价值 | 仓库接入 | 免费 Browse 发现 | 正文或详情 | 评论或回复 | Browse 页面实测 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 综合社区 | Reddit | 经验与讨论 | 站点池 · Google 同域 | 14 个帖子链接 | 详情遇 JS 挑战 | 未测 | 页面可见 · [入口](https://reddit.com) |
| 综合社区 | Quora | 经验与讨论 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://quora.com) |
| 社交媒体 | X | 实时传播和回应 | 未见专项接入 | 跳转登录 | 未测 | 未测 | 页面可见 · [入口](https://x.com) |
| 社交媒体 | Facebook | 实时传播和回应 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://facebook.com) |
| 社交媒体 | Threads | 实时传播和回应 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://threads.com) |
| 社交媒体 | Bluesky | 实时传播和回应 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://bsky.app) |
| 社交媒体 | Mastodon | 实时传播和回应 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://mastodon.social) |
| 视频媒体 | YouTube | 演示和直播 | 未见专项接入 | Hades II 探针观察到 2 个视频链接，回执不完整；PostgreSQL WAL 探针未命中 | 未验收 | 未测 | 页面文字为空（已补等） · [入口](https://youtube.com) |
| 视频媒体 | Twitch | 演示和直播 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://twitch.tv) |
| 视频媒体 | TikTok | 演示和直播 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://tiktok.com) |
| 技术问答 | Stack Overflow | 专业问答 | 站点池 · Google 同域 | 8 个问题链接 | 问题约 416 字 | 1 条答案约 280 字 | 无可核验回执 · [入口](https://stackoverflow.com) |
| 技术问答 | Stack Exchange | 专业问答 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://stackexchange.com) |
| 技术社区 | Hacker News | 行业和开发实践 | 站点池 · HN Algolia | 本轮未匹配 story 链接 | 未测 | 未测 | 页面可见 · [入口](https://news.ycombinator.com) |
| 技术社区 | Lobsters | 行业和开发实践 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见，见搜索控件 · [入口](https://lobste.rs) |
| 技术社区 | DEV Community | 行业和开发实践 | 域名规则 · 新闻排序、研究分类 | 未测 | 未测 | 未测 | 浏览器未返回可核验页面 · [入口](https://dev.to) |
| 开源项目 | GitHub | 代码、问题及发行记录 | 站点池 · 原生，另有仓库读取器 | 仓库 Issues 24 个链接 | 独立标签 issue 约 1602 字 | 未提取 | 页面可见 · [入口](https://github.com) |
| 开源项目 | GitLab | 代码、问题及发行记录 | 未见专项接入 | 项目搜索 SQLite，未匹配 | 未测 | 未测 | 页面可见，见搜索控件 · [入口](https://gitlab.com) |
| 开源项目 | Codeberg | 代码、问题及发行记录 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://codeberg.org) |
| AI 生态 | Hugging Face | 模型、基准与评议 | 站点池 · 原生 | 40 个符合探针规则的仓库链接 | 模型卡主区可见 | 未测 | 无可核验回执（已补等） · [入口](https://huggingface.co) |
| AI 生态 | Papers with Code | 模型、基准与评议 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://paperswithcode.com) |
| AI 生态 | OpenReview | 模型、基准与评议 | 未见专项接入 | 搜索 attention，未取得回执 | 未测 | 未测 | 页面可见 · [入口](https://openreview.net) |
| 长文博客 | Medium | 长文和分析 | 域名规则 · 新闻排序、研究分类 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://medium.com) |
| 长文博客 | Substack | 长文和分析 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://substack.com) |
| 长文博客 | 个人博客 | 长文和分析 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见，见搜索控件 · [入口](https://simonwillison.net) |
| 即时讨论 | Discord | 公开实时讨论 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://discord.com) |
| 即时讨论 | Telegram 公开频道 | 公开实时讨论 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://t.me/s/telegram) |
| 科研论文 | arXiv | 论文发现 | 站点池 · 原生 | 本轮搜索无可复核回执 | 独立标签读到摘要约 1136 字 | 未测 | 页面文字为空（已补等） · [入口](https://arxiv.org) |
| 科研论文 | Google Scholar | 论文发现 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见，见搜索控件 · [入口](https://scholar.google.com) |
| 科研论文 | Semantic Scholar | 论文发现 | 未见专项接入 | 搜索 transformer attention，未取得回执 | 未测 | 未测 | 无可核验回执 · [入口](https://semanticscholar.org) |
| 科研论文 | PubMed | 论文发现 | 未见专项接入 | 原生索引页 10 个可见标题 | 未测全文 | 未测 | 页面可见，见搜索控件 · [入口](https://pubmed.ncbi.nlm.nih.gov) |
| 科研数据 | Crossref | 出版元数据与数据集 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://crossref.org) |
| 科研数据 | OpenAlex | 出版元数据与数据集 | 未见专项接入 | 作品搜索 transformer，未匹配作品链接 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://openalex.org) |
| 科研数据 | Zenodo | 出版元数据与数据集 | 未见专项接入 | 搜索 SQLite，未匹配记录链接 | 未测 | 未测 | 浏览器未返回可核验页面 · [入口](https://zenodo.org) |
| 科学媒体 | Nature | 科研动态和解释 | 未见专项接入 | 未测 | 未测 | 未测 | 浏览器未返回可核验页面 · [入口](https://nature.com) |
| 科学媒体 | Science | 科研动态和解释 | 未见专项接入 | 未测 | 未测 | 未测 | 验证或拒绝（已补等） · [入口](https://science.org) |
| 科学媒体 | Quanta Magazine | 科研动态和解释 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://quantamagazine.org) |
| 国际新闻 | Reuters | 国际报道 | 域名规则 · 新闻排序 | Google 找到相关报道 | 未测 | 未测 | 页面可见 · [入口](https://reuters.com) |
| 国际新闻 | AP | 国际报道 | 域名规则 · 新闻排序 | 搜索 USB-C，未取得回执 | 未测 | 未测 | 页面可见 · [入口](https://apnews.com) |
| 国际新闻 | BBC | 国际报道 | 域名规则 · 新闻排序 | 原生搜索 USB-C，2 个匹配链接 | 未测 | 未测 | 页面可见，见搜索控件 · [入口](https://bbc.com/news) |
| 国际新闻 | AFP | 国际报道 | 未见专项接入 | 未测 | 未测 | 未测 | net::ERR_CONNECTION_CLOSED · [入口](https://afp.com) |
| 深度新闻 | Financial Times | 深度报道 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://ft.com) |
| 深度新闻 | The Economist | 深度报道 | 未见专项接入 | 未测 | 未测 | 未测 | 浏览器未返回可核验页面 · [入口](https://economist.com) |
| 深度新闻 | 纽约时报 | 深度报道 | 域名规则 · 新闻排序 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://nytimes.com) |
| 深度新闻 | 卫报 | 深度报道 | 域名规则 · 新闻排序 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://theguardian.com) |
| 商业财经 | Bloomberg | 商业报道与监管披露 | 未见专项接入 | 未测 | 未测 | 未测 | 浏览器未返回可核验页面 · [入口](https://bloomberg.com) |
| 商业财经 | CNBC | 商业报道与监管披露 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://cnbc.com) |
| 商业财经 | Yahoo Finance | 商业报道与监管披露 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://finance.yahoo.com) |
| 商业财经 | SEC EDGAR | 商业报道与监管披露 | 未见专项接入 | Apple 申报浏览页未匹配文件链接 | 未测 | 未测 | 无可核验回执 · [入口](https://sec.gov/edgar/search) |
| 科技媒体 | Ars Technica | 科技报道 | 未见专项接入 | 未测 | 未测 | 未测 | 浏览器未返回可核验页面 · [入口](https://arstechnica.com) |
| 科技媒体 | The Verge | 科技报道 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://theverge.com) |
| 科技媒体 | TechCrunch | 科技报道 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://techcrunch.com) |
| 科技媒体 | Wired | 科技报道 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://wired.com) |
| 硬件性能 | Tom's Hardware | 专项测试 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://tomshardware.com) |
| 硬件性能 | TechPowerUp | 专项测试 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://techpowerup.com) |
| 硬件性能 | Notebookcheck | 专项测试 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见，见搜索控件 · [入口](https://notebookcheck.net) |
| 游戏媒体 | IGN | 游戏报道和评测 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://ign.com) |
| 游戏媒体 | GameSpot | 游戏报道和评测 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://gamespot.com) |
| 游戏媒体 | Eurogamer | 游戏报道和评测 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见，见搜索控件 · [入口](https://eurogamer.net) |
| 游戏媒体 | PC Gamer | 游戏报道和评测 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://pcgamer.com) |
| 游戏社区 | Steam Community | 实测经验与机制资料 | 未见专项接入 | 讨论版 15 个话题链接 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://steamcommunity.com/app/1145350/discussions/) |
| 游戏社区 | Reddit | 实测经验与机制资料 | 站点池 · Google 同域 | 14 个帖子链接 | 详情遇 JS 挑战 | 未测 | 页面可见 · [入口](https://reddit.com) |
| 游戏社区 | ResetEra | 实测经验与机制资料 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://resetera.com) |
| 游戏社区 | 各游戏Wiki | 实测经验与机制资料 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://baldur-s-gate-3.fandom.com/wiki/Baldur%27s_Gate_3_Wiki) |
| 游戏性能 | Digital Foundry | 专业性能测量 | 未见专项接入 | 未测 | 未测 | 未测 | 无可核验回执 · [入口](https://digitalfoundry.net) |
| 游戏性能 | 专业评测频道 | 专业性能测量 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://youtube.com/@DigitalFoundry) |
| 产品评价 | Trustpilot | 用户评价 | 未见专项接入 | 未测 | 未测 | 未测 | 无可核验回执 · [入口](https://trustpilot.com) |
| 产品评价 | G2 | 用户评价 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://g2.com) |
| 产品评价 | Capterra | 用户评价 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://capterra.com) |
| 产品评价 | Amazon Reviews | 用户评价 | 未见专项接入 | 未测 | 未测 | 未测 | 无可核验回执 · [入口](https://amazon.com) |
| 就业招聘 | LinkedIn | 招聘及雇主信息 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://linkedin.com/jobs) |
| 就业招聘 | Indeed | 招聘及雇主信息 | 未见专项接入 | 未测 | 未测 | 未测 | 页面可见 · [入口](https://indeed.com) |
| 就业招聘 | Glassdoor | 招聘及雇主信息 | 未见专项接入 | 未测 | 未测 | 未测 | 验证或拒绝 · [入口](https://glassdoor.com) |
| 公共数据 | World Bank | 统计与公共数据 | 未见专项接入 | 人口指标详情探针连接中断 | 未测 | 未测 | net::ERR_CONNECTION_CLOSED · [入口](https://data.worldbank.org) |
| 公共数据 | IMF | 统计与公共数据 | 未见专项接入 | 未测 | 未测 | 未测 | 验证或拒绝 · [入口](https://imf.org/en/Data) |
| 公共数据 | OECD | 统计与公共数据 | 未见专项接入 | 未测 | 未测 | 未测 | 浏览器未返回可核验页面 · [入口](https://oecd.org/en/data) |
| 公共数据 | UN Data | 统计与公共数据 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://data.un.org) |
| 历史网页 | Internet Archive | 历史网页快照 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://archive.org) |
| 历史网页 | Wayback Machine | 历史网页快照 | 未见专项接入 | 未测 | 未测 | 未测 | 页面文字为空（已补等） · [入口](https://web.archive.org) |


## 信源注册表的边界和后续顺序

五类访问能力分别是开放网页、部分开放的平台、平台内部内容、内容内部结构（字幕、评论、图片文字、附件）和须授权访问的空间。每站可跨多类，计划时同时选择平台和要读取的内容类型。需要授权的空间以实际权限为准。

后续若将此表转为运行时注册表，从现有站点池扩展。建议字段按决策层用途分组：

| 关注点 | 可用字段 |
| --- | --- |
| 选哪类来源 | `platform_id`、`domains`、`region`、`topics`、`content_types` |
| 如何访问 | `search_methods`、`read_methods`、`auth_requirement`、`fallback_methods` |
| 何时信任 | `evidence_roles`、`access_status`、`last_verified_at` |

原推荐优先级按信息覆盖价值记录：

- P0 国内信息孤岛（B站、知乎、贴吧、小红书、微信公众号）；技术与海外社区（GitHub、Reddit、YouTube）。
- P1 游戏（NGA、TapTap、米游社、Steam）；技术（V2EX、掘金、CSDN、Stack Overflow）；稳定一手来源（RSS、政府网站、开放学术接口）。
- P2 热点与社交（微博、抖音、快手、X）；垂直研究（雪球、牛客、硬件社区）。

选站基于信息在哪里产生。游戏配队可分官方机制、玩家数值研究和视频实战；软件排错可分官方文档、GitHub Issues、V2EX 和 Reddit 复现；模型能力可分官方报告、Hugging Face 与独立评测；校招经验可从招聘官网与牛客、知乎、小红书各取所长；政策办理先找政府原文与办事指南、再查实际办理经验；购买决策分别看官方规格、独立实测和使用反馈。明确要求“在 B 站／米游社找”时，DeepSeek 决策层应表达对应平台意图，执行层按实际可用能力查找。本批只建立审计证据。

## 2026-11-24 免费 Browse 使用审计

采用本机已配对浏览器的实际页面，每条入口一次固定关键词，观察渲染后的目标链接、主题相关性和一页详情。链接数是探针匹配到的可见、去重内容 URL；选取相关样本检查详情中对应的正文区域和主题词。回复数只指可见内容节点，未翻页、未统计站点显示的总评论数；嵌套评论和视频字幕未验收。切换域名曾导致扩展脱离，四个 Google 发现样本改用独立标签打开已发现的 URL。访问墙、探针未命中和传输失败都保留原结果。本批费用 ¥0，未调用 DeepSeek Search、Fetch 或聊天模型。

### 现有适配的使用结果

| 站点与查询 | 发现 | 详情、评论及限制 |
| --- | --- | --- |
| B站 · 原神 那维莱特 配队 | 原生搜索，28 个视频链接 | 目标视频标题可读，未取得字幕、视频论述或评论。[视频](https://www.bilibili.com/video/BV1bC4y1V7LE/) |
| 米游社 · 同题 | 原神版块站内搜索，21 个帖子链接 | 样本为 V5.2 攻略，读取约 3251 字，有配队主题；评论探针未提取到。证明能读攻略，版本仍须逐题核对。[攻略](https://www.miyoushe.com/ys/article/60066437) |
| V2EX · 开发者 笔记 Obsidian | 配置的 `/search?q=` 跳到 `/go/search`，20 个主题，前五条均离题 | 当前原生入口该题失败。#637 的 5 个 URL 也有该版块的帖子，足以确认传输恢复，不能计为命中。Google 同域补探针本次连接中断。[跳转目标](https://www.v2ex.com/go/search) |
| 知乎 · Obsidian 笔记 | 当前已登录会话，经典页 17 个内容链接 | 样本约 1011 字，命中主题；未提取到评论。作为已知不稳定的 opt-in 保留。[回答](https://www.zhihu.com/question/1898882815422095713/answer/2014355010306203882) |
| 掘金 · SQLite WAL | 站内搜索 20 个文章链接 | 样本约 3256 字，命中 SQLite WAL；未提取到评论。[文章](https://juejin.cn/post/7645141802761568299) |
| 牛客 · 校招 笔试 经验 | 站内搜索 13 个内容链接 | 页面抓到主题文字及 1 个可见评论区容器，约 2636 字为页面主区计数，评论条目尚未核实。[经验帖](https://www.nowcoder.com/feed/main/detail/0aac498d0f9249228f4f18db69901edd) |
| GitHub · uv pytorch cuda | 仓库 Issues 搜索 24 个链接；前五含相关讨论 | 首选页面的正文探针空；独立标签对前五已知 issue #10360 读到约 1602 字，命中 torch；未提取评论。[Issue](https://github.com/astral-sh/uv/issues/10360) |
| Steam · Hades II | 商店搜索 50 个商品链接 | 命中 Hades II，游戏介绍约 678 字，未提取用户评测。内容是商店信息。[商品](https://store.steampowered.com/app/1145350/Hades_II/) |
| Hugging Face · Qwen3 | 原生全文搜索命中 40 个符合本探针仓库规则的可见链接 | 命中 Qwen3.5-9B 模型卡，页面主区可见。精确版本研究须筛掉名字相近的版本。[模型卡](https://huggingface.co/Qwen/Qwen3.5-9B) |
| arXiv · transformer attention | 本轮原生搜索未取得可复核结果 | 独立标签读到论文摘要约 1136 字，命中 attention；未核对 PDF 全文。[摘要](https://arxiv.org/abs/1706.03762) |
| HN · SQLite WAL | Algolia 搜索在本轮观察窗口内零个符合规则的 story 链接 | 历史已验证 URL 参数；未验收本轮评论。 |
| NGA · 原神 那维莱特 配队 | 当前探针零个帖子链接 | 未验收为可用，继续 opt-in。 |
| LINUX DO · Obsidian 笔记 | Google 同域发现 10 个主题链接 | 独立标签样本未取得正文节点。历史可读样本仍有效为历史证据。[样本](https://linux.do/t/topic/1376348) |
| Reddit · Hades II Steam Deck | Google 同域发现 14 个帖子链接 | 独立标签出现 JS 挑战参数，未读取帖子或评论。[样本](https://www.reddit.com/r/SteamDeck/comments/1nx5ect/hades_2_on_the_steam_deck_is_nextlevel/) |
| Stack Overflow · SQLite WAL concurrent writers | Google 同域发现 8 个问题链接 | 目标页读到约 416 字问题正文和 1 条约 280 字的答案。该样本用于核对社区观点，SQLite 规范仍回到官方文档。[问题](https://stackoverflow.com/questions/30846095/can-i-use-wal-mode-in-sqlite3-if-i-use-an-additional-mutex-for-multiple-writers) |
| Chiphell · 迷你主机 功耗 | Google 同域发现 7 个主题链接 | 命中小主机实测功耗讨论，首个匹配文本约 316 字。探针识别 15 个有内容的帖子区节点，包含楼主与回复，未检查逐条归属或引用链。[讨论](https://www.chiphell.com/thread-2688887-1-1.html) |

### 优先候选的免费可用性

| 候选与查询 | 实测观察 |
| --- | --- |
| 贴吧 · 原神 那维莱特 配队 | 10 个格式正确的帖子链接，但前排离题，点开的样本是论坛用语。未计为有效发现。 |
| 小红书 · Obsidian 笔记 | 到达搜索页，未提取符合规则的笔记链接。该样本无法裁定平台整体可用性。 |
| 微信公众号 · SQLite WAL | 搜狗微信及 Google 公开索引两个入口都未提取可复核的公众号链接。当前仍是候选。 |
| YouTube · Hades II Steam Deck settings | 搜索页观察到 2 个视频 URL，详情探针回执不完整，本轮无可核验的视频内容。 |
| TapTap · 原神 那维莱特 配队 | 搜索未匹配帖子链接。打开此前发现的攻略可见标题，所用正文规则未命中。[已知攻略](https://www.taptap.cn/moment/861319174629099829) |
| 微博 · 地铁 通勤 | 跳转登录，结束。 |
| X · SQLite WAL | 跳转要求登录的 onboarding，结束。 |
| 抖音 · Hades II 攻略 | 观察时零个符合规则的视频链接，回执不完整，未验收。 |
| 快手 · 原神 配队 | 未提取符合规则的视频链接。 |
| 雪球 · 指数基金 定投 | 未提取符合规则的讨论链接。 |
| PubMed · GLP-1 semaglutide STEP 1 | 原生检索页观察到 10 个可见文献标题，命中主题。文章全文及专项接入未验收。[样本索引](https://pubmed.ncbi.nlm.nih.gov/35441470/) |
| Reuters · EU USB-C | Google 找到相关报道，未读报告原文。定位报道与核验法规分别有独立任务。[报道](https://www.reuters.com/technology/eu-parliament-adopts-rules-common-charger-electronic-devices-2022-10-04/) |
| 中国政府网 · 国务院 互联网 政务服务 | Google 发现探针连接中断，状态未知。 |

另外用同一浏览器检查了四个入口。CSDN 的 `SQLite WAL` 搜索提取到 26 个文章链接并命中主题，未读详情；Steam Community 的 Hades II 讨论版有 15 个可见话题链接，未验收讨论正文。公开网页对照成功读取 [PostgreSQL 正式发布稿](https://www.postgresql.org/about/news/postgresql-19-released-3449/)的主区和 [澳洲 eSafety 官方 FAQ](https://www.esafety.gov.au/about-us/industry-regulation/social-media-age-restrictions/faqs)的主区。它们分别是发布事实和监管说明的一手来源。

### 补充定向探针

全表页面探针之外，对 12 个入口补查关键词或已知详情。较清楚的命中分别是 Gitee 原生搜索 SQLite 的 2 个仓库链接，以及 BBC 原生搜索 USB-C 的 2 个报道链接。样本只核实搜索命中。OpenReview、Semantic Scholar 和 AP 的搜索没有可复核回执，其余探针的零命中或连接错误保留在逐站表中。[Gitee 查询](https://search.gitee.com/?q=SQLite&type=repository) · [BBC 查询](https://www.bbc.co.uk/search?q=USB-C)

### 审计结论

1. 最先补 **平台意图到现有能力的派发**。DeepSeek 在同一轮研究计划里区分“在某站找”和“以某站为讨论对象”；执行层给出真实支持的模式（原生搜索、公开索引发现、仅按 URL 读取），并保持用户给定的站点范围。
2. 再修 **已接入路径的结果校验**。V2EX 需要识别搜索页跳成版块页。贴吧的离题结果说明平台域名、结果样式、数量三项齐全时仍需核对题意。米游社要核对游戏与版本。
3. 最后才加入 **必要的内容读取能力**。B 站目前适合发现视频，正文样本更完整的米游社、掘金、GitHub issue 可以优先接证据链。涉及实际视频演示、评论或楼层归属的题，先验收对应内容读取。以上免费样本尚无研究发布通过的动态证据。

## Codex、OpenCode 与 Study Agent 的联网代码对照

2026-11-24 从 GitHub 查询并读取公开仓库分支源码。对照范围是工具注册、查询入口、提供方选择、网页读取与结果返回。源码能说明客户端行为，无法据此评价同一题的答案质量，也无法推出托管后端的内部搜索算法。

| 环节 | Codex | OpenCode | Study Agent |
| --- | --- | --- | --- |
| 模型入口 | 工具注册器按配置、模型及提供方能力暴露托管 `web_search` 或独立扩展 `web.run`；独立扩展可用时客户端避免同时挂载托管入口 | `websearch` 注册查询工具，权限检查后调用 `WebSearch.Service`，结果含 URL、标题、内容与提供方元数据 | 语义研究先由模型输出 `rq_id`、`query`，执行器再调度搜索；活动研究另有域名定向路径 |
| 提供方与执行 | 托管工具规格按 cached、indexed、live、disabled 配置外网行为；扩展将命令传给配置的搜索端点 | 提供方有独立执行接口与注册表；选择、会话偏好和冷却在服务层 | `GeneralWebGateway` 已有 SearXNG、Browse、独立 DeepSeek Search 及其他通用后备；站点池是现有 Browse 定向入口 |
| 读指定来源 | 独立搜索扩展接受搜索及页面相关命令，执行由其搜索服务承接 | `webfetch` 是按 URL 的独立只读工具，处理格式、权限、跳转、超时及响应大小约束 | 已有 `web_read` 路径及浏览器读取能力；证据链独立核对已读内容与用户主张 |

- **Codex** `50aeac27d825007a0ac6bd846087ed4e7095bdb3`。[注册与互斥](https://github.com/openai/codex/blob/50aeac27d825007a0ac6bd846087ed4e7095bdb3/codex-rs/core/src/tools/spec_plan.rs#L693) · [托管搜索规格](https://github.com/openai/codex/blob/50aeac27d825007a0ac6bd846087ed4e7095bdb3/codex-rs/core/src/tools/hosted_spec.rs) · [独立扩展](https://github.com/openai/codex/blob/50aeac27d825007a0ac6bd846087ed4e7095bdb3/codex-rs/ext/web-search/src/tool.rs)
- **OpenCode** `24cf6eb258437acf046876dea9f9ab527926474b`。[websearch 注册](https://github.com/anomalyco/opencode/blob/24cf6eb258437acf046876dea9f9ab527926474b/packages/core/src/tool/plugin/websearch.ts) · [提供方服务](https://github.com/anomalyco/opencode/blob/24cf6eb258437acf046876dea9f9ab527926474b/packages/core/src/websearch.ts) · [webfetch](https://github.com/anomalyco/opencode/blob/24cf6eb258437acf046876dea9f9ab527926474b/packages/core/src/tool/plugin/webfetch.ts)
- **Study Agent** `84f654ac3a805016a708b42ad1154339d4fcb8b4`。[模型查询决策](../../src/web/semantic_recovery.py) · [研究入口](../../src/tools/persistent_web_agent.py) · [检索读取网关](../../src/web/tool_gateway.py) · [证据发布检查](../../src/web/research/evidence_gate.py)

可借鉴的是模型入口少、执行路径可替换。Study Agent 已有执行网关，下一片直接沿用现有搜索和读取入口。模型根据问题给出检索词及可选平台，例如“在米游社找那维莱特配队”给站点标识，“B 站过去三年收入如何”允许查财报等开放网页。执行层用现有站点池决定原生搜索或已审计的同域索引，并把实际通道、空结果、登录墙及预算耗尽交还给模型。通用搜索依部署配置先用一个通道，只有确有缺口且权限和额度允许才补查。平台清单负责说明覆盖，只有现有可派发能力进入模型工具参数。优先用同题检验点名站内、提到平台、站内受限这三种情形，观察实际请求数、命中链接、可读正文和答案支撑。
