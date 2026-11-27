# 结论先行

Jolt 解决的是“刚体和约束求解得更稳”，它不解决“什么算一栋楼”。你要研究的三类限制里，真正影响设计的是接口边界和结构模型，求解器本身反而是问题最少的。下面按“有文档依据的硬限制 → 结构层缺口 → 可执行做法 → 失效边界”展开。

---

## 一、真实存在的引擎层限制

### 1. 最直接的一条：4.4+ 内建 Jolt 没有替代关节节点

扩展版 README 明确写了：扩展提供一组可选替代关节节点，用来支持 **breakable joints、soft limits、逐关节 solver 迭代覆盖**；而作为引擎模块内建后，扩展进入维护模式，只合 bug fix [来源](https://raw.githubusercontent.com/godot-jolt/godot-jolt/master/README.md)。

官方文档把这句话写实了：`JoltPinJoint3D`、`JoltHingeJoint3D`、`JoltSliderJoint3D`、`JoltConeTwistJoint3D`、`JoltGeneric6DOFJoint3D` **没有包含进 Jolt 模块** [来源](https://raw.githubusercontent.com/mihe/godot-docs/29c9520b3270e416865304502df82a1bf7de0153/tutorials/physics/using_jolt_physics.rst)。

所以“用物理关节把墙块连起来，超过受力就断”这条路，在 4.4+ 内建 Jolt 下没有现成节点。剩下只能用原生 `Joint3D` 系列，而断裂判定要自己写（原生关节没有断裂阈值属性，这是从文档只把 breakable joints 归给扩展节点推出的推断）。

### 2. 关节的“软化”参数被忽略

原生关节里这些属性在 Jolt 下不生效，设成非默认值只会打警告：

| 节点 | 不支持的属性 |
|---|---|
| PinJoint3D | `bias`、`damping`、`impulse_clamp` |
| HingeJoint3D | `bias`、`softness`、`relaxation` |
| SliderJoint3D | `angular_*`、`*_limit/softness`、`restitution`、`damping` |
| ConeTwistJoint3D | `bias`、`relaxation`、`softness` |
| Generic6DOFJoint3D | `*_limit_*/softness`、`restitution`、`damping`、`erp` |

依据同上 [来源](https://raw.githubusercontent.com/mihe/godot-docs/29c9520b3270e416865304502df82a1bf7de0153/tutorials/physics/using_jolt_physics.rst)。

实际后果：你没法做“先变软、再撕裂”的渐进破坏手感，断裂只能是一个硬切换。想让一块墙在受力时先轻微位移再脱落，得靠你自己在逻辑层插值，而不是靠关节参数。

### 3. 接触冲量是估计值

`PhysicsDirectBodyState3D.get_contact_impulse()` 的返回值是 Jolt 内部**预先估计**的，只有“这两个 body 没有同时和第三个 body 碰撞”时才准确 [来源](https://raw.githubusercontent.com/mihe/godot-docs/29c9520b3270e416865304502df82a1bf7de0153/tutorials/physics/using_jolt_physics.rst)，README 也把它列在“与 Godot Physics 不同”的条目里 [来源](https://raw.githubusercontent.com/godot-jolt/godot-jolt/master/README.md)。

建筑块天然是互相挤压的。所以拿接触冲量当“伤害值/断裂阈值”，数值会漂。可执行替代：用命中瞬间的速度变化、或者干脆用武器侧的伤害数值 + 块自身的血量，物理只负责“碎掉之后怎么飞”。

### 4. 冻结的运动学刚体默认收不到接触报告

`FREEZE_MODE_KINEMATIC` 冻结的 `RigidBody3D`，默认**不报告**与静态/运动学 body 的接触，即使 `max_contacts_reported` 设了非零。要开 `Physics > Jolt Physics 3D > Simulation > Generate All Kinematic Contacts`，而文档同时提醒：大量/大体积运动学体与复杂静态几何重叠时会白白吃掉 CPU 和内存 [来源](https://raw.githubusercontent.com/mihe/godot-docs/29c9520b3270e416865304502df82a1bf7de0153/tutorials/physics/using_jolt_physics.rst)。

这条直接否掉了“把整栋楼冻结成一个整体，靠 body 接触事件检测被打中”的方案。命中检测应该走 `Area3D` 或射线。

（顺带一条相关的：`simulation/areas_detect_static_bodies` 这个设置项存在，说明 Area3D 检测静态体是可配置行为，做掩体命中时要确认它开着。依据是文档里的设置改名列表 [来源](https://raw.githubusercontent.com/mihe/godot-docs/29c9520b3270e416865304502df82a1bf7de0153/tutorials/physics/using_jolt_physics.rst)。）

### 5. 进入场景树后改 shape 很贵

README 原文：body 进入场景树之后再操作它的 shape 可能代价很高 [来源](https://raw.githubusercontent.com/godot-jolt/godot-jolt/master/README.md)。

所以“墙被打出一个洞，运行时重建碰撞体”是反模式。正确方向是**预切块**，破坏 = 隐藏/移除/替换块，而不是修改块。

### 6. 尺度窗口与碰撞边距

Jolt 自己的建议：动态物体 **0.1–10 m**，速度 0–500 m/s，重力 0–10 m/s²；静态物体 0.1–2000 m [来源](https://raw.githubusercontent.com/godot-jolt/godot-jolt/master/README.md)。

边距（Jolt 叫 convex radius）的行为是：先用它**收缩**形状，再套壳，所以不会像 Godot Physics 文档描述的那样把形状撑大。默认值对小块可能有问题，靠 `collision_margin_fraction` 乘 AABB 最小轴自动算，`shape.margin` 退化为上界。文档还提醒 shape query 可能返回奇怪法线，把它设成 0.0 能缓解，但太小又会出异常碰撞 [来源](https://raw.githubusercontent.com/mihe/godot-docs/29c9520b3270e416865304502df82a1bf7de0153/tutorials/physics/using_jolt_physics.rst)。

对掩体的含义：几厘米厚的薄墙正好落在敏感区。这是推断，但依据是“margin 为上界且随 shape 尺寸缩放”这条机制。实践上要么把薄墙做成 ≥0.15 m，要么单独实测 fraction。

### 7. 块与块之间的 ghost collision 没有保护

Jolt 用两套机制抑制 ghost collision（碰撞法线反向于运动方向）：`ConcavePolygonShape3D` / `HeightMapShape3D` 上的 active edge detection，以及运行