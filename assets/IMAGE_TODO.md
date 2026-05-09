# 图片资源清单

> 最后更新: v0.6 资源接入

## 头像 avatars/ ✅

| 文件名 | 角色 | 状态 |
|--------|------|------|
| `march7.png` | 三月七 | ✓ 已接入 |
| `keqing.png` | 刻晴 | ✓ 已接入 |
| `nahida.png` | 纳西妲 | ✓ 已接入 |
| `firefly.png` | 流萤 | ✓ 已接入 |
| `default.png` | 缺失时使用 | ⬜ 未提供（系统用文字 fallback） |

`src/ui/avatar.py` — 图片优先，缺失时回退文字（7/晴/妲/萤）。

## 备用头像 avatars_alt/ ✅

| 文件 | 用途 |
|------|------|
| `march7_alt_cute.png` | 三月七 Q 版 |
| `keqing_alt_card.png` | 刻晴卡片版 |
| `nahida_alt_full.png` | 纳西妲全身版 |
| `firefly_alt_chibi.png` | 流萤 Chibi 版 |

v0.6 不加载，v0.7 角色卡/主题切换再用。

## 背景 backgrounds/ ✅

| 文件名 | 用途 | 状态 |
|--------|------|------|
| `chat_bg_light.jpg` | **默认聊天背景**（低对比、柔和、不抢文字） | 保留 |
| `wechat_bg_soft.jpg` | **微信群背景** | 保留 |
| `warm_close_bg.jpg` | warm/close 氛围可选背景 | 保留 |
| `march7_energy_bg.jpg` | 欢迎/启动页专用（**不做默认背景**，活力感强会干扰代码块和论文阅读） | 保留 |

v0.6 使用纯 CSS 暗色主题，背景图保留为后续主题切换资源。
默认背景：`chat_bg_light.jpg`。启动页：`march7_energy_bg.jpg`。

## 横幅 banners/ ✅

| 文件 | 用途 |
|------|------|
| `march7_banner.jpg` | 欢迎页/学习启动卡/入门模式 |
| `keqing_banner.jpg` | 项目模式/任务边界卡/验收清单 |
| `nahida_banner.jpg` | 概念地图/本质总结卡 |
| `firefly_banner.jpg` | 课后复盘/warm-close 陪伴区域 |

v0.6 不加载，v0.7 角色动态卡 + 欢迎页再用。

## 图标 icons/ ⬜

当前无图片资源，使用 CSS 纯色替代（红点等）。

## 版权说明

- 角色素材来自《崩坏：星穹铁道》《原神》，版权归 HoYoverse 所有
- 仅限本地个人学习工具使用
- 如公开发布，需替换为原创或授权素材
