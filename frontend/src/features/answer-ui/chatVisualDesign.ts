/** Product adaptation of huashu-design's content-first infographic guidance.
 * Kept in the existing transient UI envelope; no extra model pass or workflow.
 * Rationale and attribution: docs/CHAT_VISUAL_DESIGN.md.
 */
export const CHAT_VISUAL_DESIGN = `【聊天图表设计准则 v1】
先确定用户要看清的关系，再选形式。一个图只讲一个重点，先给一句结论，再在相关段落旁放图；简单事实用文字即可，不为装饰重复做图。通常一张图足够。
分类或大小比较用chart的bar视图；连续时间或有序变化用line，保留真实顺序；精确查数或多维比较用Markdown表格；数学关系用plot并注明示意。没有合适组件时用文字或表格，不硬套图表。
标题说明比较对象与范围，避免空泛的“数据分析”。统一量纲，unit写明确单位；不同单位不混在同一数列。标签用短而完整的名称，保留有意义的精度；项目较多时优先表格，不擅自删掉数据。
仅使用用户提供、工具已核验或明确标注为示意的数据。示意必须同时标在标题和相邻正文；缺失值不是零，不补造数字。来源、统计时间、样本口径及关键假设写在紧邻图表的正文，沿用真实引用；图形不能冒充证据。
界面统一使用白底、深色文字、鼠尾草绿强调色和淡色网格；一个颜色只表达一个含义，同时用文字标注。层级依次是结论、图与数值、来源说明，留白用于分组。配色、字号和交互由组件保证，不输出自定义HTML/CSS/JavaScript，不增加装饰性图标、渐变或动画。`;
