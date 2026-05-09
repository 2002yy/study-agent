# 路由规则

> 修改本文件后重启 Streamlit 即可生效。

## rule
- keywords: 为什么, 本质, 底层, 机制, 原理, 从根上讲, 概括, 一句话总结
- role: nahida
- mode: 苏格拉底
- model: pro
- reason: 追问本质/底层机制 → 纳西妲用苏格拉底深度引导

## rule
- keywords: 怎么办, 下一步, 实现, 修改, 代码, bug, 报错, 测试, 方案, 部署, 配置
- role: keqing
- mode: 项目
- model: pro
- reason: 任务/实现/排错 → 刻晴用项目模式收束

## rule
- keywords: 我来讲, 你听我解释, 检查我理解, 我复述, 我的理解是, 你听听看, 我来解释, 帮你检查, 讲给你听, 说给你听, 我理解的是
- role: nahida
- mode: 费曼
- model: pro
- reason: 用户尝试复述 → 纳西妲用费曼模式找漏洞

## rule
- keywords: 论文, 摘要, 降AI, 章节, 参考文献, 表述, 替换, 论据, 论点
- role: keqing
- mode: 论文
- model: pro
- reason: 论文/审读 → 刻晴用论文模式审视结构

## rule
- keywords: 累, 复盘, 收尾, 今天到这, 简单总结, 陪我理一下, 不想学了, 休息
- role: firefly
- mode: 普通
- model: flash
- reason: 疲惫/收尾 → 流萤轻陪伴

## rule
- keywords: 入门, 开始学, 先问我, 有趣点, 别直接讲, 新手, 零基础
- role: march7
- mode: 苏格拉底
- model: flash
- reason: 入门/启动 → 三月七苏格拉底引导

## default
- role: nahida
- mode: 普通
- model: flash
- reason: 无匹配规则，使用默认
