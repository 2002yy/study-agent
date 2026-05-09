# assets/

本目录存放视觉资源，仅供本地个人学习使用。

## 目录说明

| 子目录 | 用途 |
|--------|------|
| avatars/ | 角色头像：march7.png, keqing.png, nahida.png, firefly.png |
| backgrounds/ | 页面/群聊背景图 |
| icons/ | 未读标记、群图标等小图标 |

## 命名规则

- `march7.png` / `keqing.png` / `nahida.png` / `firefly.png` — 角色头像
- `default.png` — 任何头像缺失时使用
- 格式: png 或 webp，推荐 128×128

## 缺失时的 fallback

当前系统不依赖真实图片。`src/ui/avatar.py` 使用文字替代：
- 三月七 → "7"、刻晴 → "晴"、纳西妲 → "妲"、流萤 → "萤"
- 页面不会因图片缺失而崩溃

## 版权说明

- 角色素材来自《崩坏：星穹铁道》《原神》，版权归 HoYoverse 所有
- 仅用于个人学习工具界面，不作商业用途、不分发
- 图片文件不在代码仓库中共享，由用户自行准备
- 如公开发布，需替换为原创或授权素材
