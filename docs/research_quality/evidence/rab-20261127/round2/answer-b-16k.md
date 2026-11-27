## 先给结论

Godot 4.x + Jolt **没有任何内置的“可破坏结构”能力**。Jolt 提供的是刚体、关节、接触与查询；断裂、支撑关系、结构强度、碎块回收，全部要你自己写。

真正会限制你的问题集中在两处：**一是 Jolt 的接口语义与 Godot Physics 不一样，很多人在迁移时默认它能继承过来；二是它明确不保证的东西（接触冲量、确定性、关节软限位）恰好是“写实破坏”最想依赖的**。

下面把“确实存在的限制”和“常被误传的说法”分开讲，再给一套可执行的架构和失效边界。

---

## 一、引擎能力层：真正必须自己做的

| 你需要的东西 | Jolt / Godot 提供吗 | 依据 |
|---|---|---|
| 预切分碎块、凸包碰撞 | 提供（`ConvexPolygonShape3D`、`ConcavePolygonShape3D`） | — |
| 运行时网格切割 + 凸分解 | **不提供**，只能自己实现或借助外部工具 | 推断（文档未涉及网格处理） |
| 支撑/连通性判定 | **不提供**，需要自己维护图结构 | 社区讨论里也是自己搭支撑树 [来源](https://forum.godotengine.org/t/collapsable-buildings-in-3d/45949/13) |
| 结构应力/荷载重分配 | **不提供** | 同上，该帖也只到“连通性 + 冻结/激活”这个层面 |

那篇倒塌建筑的长帖很说明问题：做到最后，方案是“自己建一棵支撑树 → 子节点失去支撑就改挂或下坠 → 只激活需要掉的那部分 → 用碎片和烟尘遮住真实细节”。这是社区里已经验证过的做法，不是引擎功能 [来源](https://forum.godotengine.org/t/collapsable-buildings-in-3d/45949/13)。

所以，必须调整预期：**你是在用 Jolt 实现一个自己设计的结构系统，而不是在配置一个“破坏模块”。**

---

## 二、接口层：这些限制是真实的，且最容易出错

### 1. 内置模块里没有 `JoltHingeJoint3D` 这类节点

扩展版提供了一整套替代关节节点，能做**可断关节、软限位、逐关节覆盖求解迭代次数**——这几乎是“可破坏结构”最想要的东西 [来源](https://raw.githubusercontent.com/godot-jolt/godot-jolt/master/README.md)。

但从 4.4 起 Jolt 变成引擎内置模块，官方文档明确写着：**扩展里暴露的那些关节节点没有被包含进 Jolt 模块** [来源](https://raw.githubusercontent.com/mihe/godot-docs/29c9520b3270e416865304502df82a1bf7de0153/tutorials/physics/using_jolt_physics.rst)。

后果：在 4.4+ 使用内置 Jolt 时，“关节受力超过阈值自动断开”这个功能**没有现成实现**，必须自己累计伤害再 `queue_free()` 掉关节节点。逐关节的求解迭代次数也没法调。

同时，扩展本身已进入维护模式，只合 bug fix [来源](https://raw.githubusercontent.com/godot-jolt/godot-jolt/master/README.md)。因此不建议特意为了关节节点而停留在扩展上。

### 2. 原生关节的软限位参数会被静默忽略

`HingeJoint3D` 的 `bias`/`softness`/`relaxation`、`SliderJoint3D` 的 `*_limit/damping`、`Generic6DOFJoint3D` 的 `*_limit_*/erp` 等等，在 Jolt 下都不支持；设成非默认值只会**输出一条警告** [来源](https://raw.githubusercontent.com/mihe/godot-docs/29c9520b3270e416865304502df82a1bf7de0153/tutorials/physics/using_jolt_physics.rst)。

如果你想要“墙在倒塌前先微微下沉、裂缝张开”这种渐进屈服感，不要通过调整这些参数来实现，应该在自己的伤害模型里分阶段修改材质/网格/支撑关系。

### 3. 接触冲量是**预估值**，多体接触下不准确

这一条对“按冲击力扣血”的方案是决定性的。文档原文的大意是：`get_contact_impulse()` 返回的冲量是根据接触流形和速度**提前估算**的，只有在这两个物体**没有同时与别的物体碰撞**时才准确 [来源](https://raw.githubusercontent.com/mihe/godot-docs/29c9520b3270e416865304502df82a1bf7de0153/tutorials/physics/using_jolt_physics.rst)。

而建筑倒塌现场恰恰是“一堆东西互相压着”。结论很直接：

- **单发子弹打静止墙面**：冲量可用，误差可接受。
- **碎块堆里、连续命中、爆炸推开一堆物体**：冲量不可用于数值化伤害。改用你自己的能量公式（弹丸质量 × 速度、爆炸半径衰减），这是唯一可控的办法。

### 4. 冻结的刚体默认不上报静态/运动学接触

`RigidBody3D` 用 `FREEZE_MODE_KINEMATIC` 冻结时，默认**不报告**与静态/运动学物体之间的接触，即使 `max_contacts_reported` 设了非零值。要开启得打开 `Physics > Jolt Physics 3D > Simulation > Generate All Kinematic Contacts`，但文档警告：大量大型运动学物体与复杂静态几何（凹多边形、高度图）重叠时会**在无感知的情况下消耗大量 CPU 和内存** [来源](https://raw.githubusercontent.com/mihe/godot-docs/29c9520b3270e416865304502df82a1bf7de0153/tutorials/physics/using_jolt_physics.rst)。

“先把整栋楼冻结，等它被撞了再激活”是社区里的常见做法 [来源](https://forum.godotengine.org/t/collapsable-buildings-in-3d/45949/13)；但在 Jolt 下，**冻结状态收不到撞击接触**，所以命中判定不能依赖 body 接触信号。

### 5. 碰撞边距（margin）语义完全变了

在 Godot Physics 下，`Shape3D.margin` 基本是个摆设——“Godot Physics 自己并不使用它” [来源](https://raw.githubusercontent.com/mihe/godot-docs/29c9520b3270e416865304502df82a1bf7de0153/tutorials/physics/using_jolt_physics.rst)。

在 Jolt 下，它变成了“凸半径”：先把形状**收缩**，再套一层圆角壳；实际值由 `collision_margin_fraction × AABB 最小轴` 得出，`margin` 属性只作为上限 [来源](https://raw.githubusercontent.com/mihe/godot-docs/29c9520b3270e416865304502df82a1bf7de0153/tutorials/physics/using_jolt_physics.rst)。

所以在 Jolt 下：
- 小块碎片的默认边距可能过大，导致碰撞体看上去比网格“胖”或“圆”。
- 把它调到 `0.0` 会让形状查询返回奇怪的碰撞法线，文档明确不推荐。
- 从 Godot Physics 迁移过来的项目，一定要重新核对一遍 margin，不能沿用旧值。

### 6. 幽灵碰撞的缓解只在“同一个 body 内部”生效

Jolt 提供了两套机制：三角形面片的 active edge detection（只作用于 `ConcavePolygonShape3D` / `HeightMapShape3D`），以及 enhanced internal edge removal（作用于**同一个 body 内任意形状之间**的边）。

文档最后一句是关键：**这两套机制都不作用于两个不同 body 之间的幽灵碰撞** [来源](https://raw.githubusercontent.com/mihe/godot-docs/29c9520b3270e416865304502df82a1bf7de0153/tutorials/physics/using_jolt_physics.rst)。

换成建筑语来说就是：

- **完整状态**：整段墙做成一个凹多边形 body → 碎块沿墙滑动的“挂边”问题有缓解。
- **破坏状态**：墙变成 20 个独立 `RigidBody3D` 碎块 → 块与块之间的接缝**没有任何缓解**；碎块滑过接缝时会被内部边顶住、弹飞或抖动。

这是拼装式可破坏建筑最真实的限制，而且它不会报错，只会表现为物理看起来“很怪”。缓解办法只能从设计上入手：接触面做重叠或互锁、加大块尺寸、静止后合并回单个 body。

### 7. 其他确实存在但优先级较低的限制

- **进入场景树后再修改 body 的 shape 成本很高** [来源](https://raw.githubusercontent.com/godot-jolt/godot-jolt/master/README.md)。不要用“换碰撞形状”做损伤阶段，替换整个 body（可以从对象池获取）会更可控。
- **`CollisionShape3D` 不能嵌在 `CollisionShape3D` 下面**，必须以 body 作为父节点 [来源](https://forum.godotengine.org/t/collapsable-buildings-in-3d/45949/13)。
- **`SoftBody3D` 与 `Area3D` 完全没有交互**（包括重叠事件和风力），[来源1](https://raw.githubusercontent.com/godot-jolt/godot-jolt/master/README.md)、[来源2](https://raw.githubusercontent.com/mihe/godot-docs/29c9520b3270e416865304502df82a1bf7de0153/tutorials/physics/using_jolt_physics.rst)。绳网、软质遮雨布这类内容不要指望。
- **射线 `face_index` 默认恒为 `-1`**，要开启得打开 `queries/enable_ray_cast_face_index`，代价是凹多边形形状内存增加约 25% [来源](https://raw.githubusercontent.com/mihe/godot-docs/29c9520b3270e416865304502df82a1bf7de0153/tutorials/physics/using_jolt_physics.rst)。如果你想用面索引做“打哪块掉哪块”，这笔内存要算进去。
- **临时内存是固定预算**：Jolt 用栈分配器，`limits/temporary_memory_buffer_size` 需要事先分配足够内存 [来源](https://raw.githubusercontent.com/mihe/godot-docs/29c9520b3270e416865304502df82a1bf7de0153/tutorials/physics/using_jolt_physics.rst)。大坍塌必须预留预算。
- **`WorldBoundaryShape3D` 的有效尺寸在 Jolt 下小得多**（为避免精度问题），用无限地面做大场景要注意 [来源](https://raw.githubusercontent.com/mihe/godot-docs/29c9520b3270e416865304502df82a1bf7de0153/tutorials/physics/using_jolt_physics.rst)。
- **确定性不保证**：即使 Jolt 本身可以确定性，Godot Jolt 也明确表示**不要依赖** [来源](https://raw.githubusercontent.com/godot-jolt/godot-jolt/master/README.md)。联网破坏只能同步事件，不能指望锁步重放。
- **线程**：扩展的物理服务器非线程安全；内置模块虽然支持 `Run On Separate Thread`，但“未经充分测试，应视为实验性” [来源1](https://raw.githubusercontent.com/godot-jolt/godot-jolt/master/README.md)、[来源2](https://raw.githubusercontent.com/mihe/godot-docs/29c9520b3270e416865304502df82a1bf7de0153/tutorials/physics/using_jolt_physics.rst)。
- **尺度建议**：Jolt 自己的文档建议动态物体在 0.1–10 m 量级、静态物体 0.1–2000 m [来源](https://raw.githubusercontent.com/godot-jolt/godot-jolt/master/README.md)。5 cm 的碎片属于超出建议范围。

---

## 三、和实际实现对齐：四态结构模型

### 状态机

```
INTACT（完整） → DAMAGED（受损） → COLLAPSING（解体） → SETTLED（休眠）
```

| 状态 | 物理形态 | 代价 |
|---|---|---|
| INTACT | StaticBody3D（每段一个凹多边形） | 接近零 |
| DAMAGED | 同上，仅换网格/材质 + 更新图 | 接近零 |
| COLLAPSING | 受影响的碎块变成活跃 RigidBody3D | 与碎块数成正比 |
| SETTLED | `sleeping = true`，超时后冻结回静态 | 回到接近零 |

核心思路来自那篇帖子：**只把“这次真正掉下去的那部分”转成活动物理**，其余保持冻结 [来源](https://forum.godotengine.org/t/collapsable-buildings-in-3d/45949/13)。

### 支撑图与连通性重算

用纯数据图，不挂在物理节点上。每次结构事件后做一次从地面出发的 BFS：

```gdscript
extends Node
class_name SupportGraph

var _support: Dictionary = {}   # int -> Array[int]，这块由谁支撑
var _ground: Array[int] = []    # 直接接地的块
var _alive: Dictionary = {}     # int -> bool

func rebuild() -> Array[int]:
    # 反向索引：支撑者 -> 被支撑者
    var supported := {}
    for id in _support:
        for s in _support[id]:
            if not supported.has(s):
                supported[s] = []
            supported[s].append(id)

    var ok := {}
    var stack: Array[int] = []
    for g in _ground:
        if _alive.get(g, false):
            ok[g] = true
            stack.append(g)

    while not stack.is_empty():
        var cur: int = stack.pop_back()
        for child in supported.get(cur, []):
            if _alive.get(child, false) and not ok.has(child):
                ok[child] = true
                stack.append(child)

    var orphans: Array[int] = []
    for id in _alive:
        if _alive[id] and not ok.has(id):
            orphans.append(id)
    return orphans
```

`rebuild()` 是 O(V+E)，一次破坏几百块的建筑完全在预算内。注意它是**二值支撑**：只有“还连着地面”和“断了”两种结果，**没有荷载大小**。这一点下面会作为失效边界再讲。

### 命中判定：用射线，不要用接触冲量

```gdscript
func on_hit(from: Vector3, dir: Vector3, energy: float) -> void:
    var space := get_world_3d().direct_space_state
    var q := PhysicsRayQueryParameters3D.create(from, from + dir * 200.0)
    q.collide_with_areas = false
    var hit := space.intersect_ray(q)
    if hit.is_empty():
        return
    var chunk_id := _chunk_at(hit.position)      # 用预存的 AABB 或质心表
    _damage[chunk_id] -= energy                  # 自己算能量，不读引擎冲量
    if _damage[chunk_id] <= 0.0:
        _break(chunk_id)
```

三个好处：不需要开 `Generate All Kinematic Contacts`；不受“冲量只是估计”影响；判定完全可复盘、可联网同步。

`_chunk_at()` 用每块在建筑局部空间的 AABB 做点包含测试即可，O(n)，n 是几十到几百时完全够用。

### 触发解体

```gdscript
func _break(chunk_id: int) -> void:
    _alive[chunk_id] = false
    var orphans := rebuild()
    _visual_to_damaged(chunk_id)
    _activate(orphans)

func _activate(ids: Array[int]) -> void:
    for id in ids:
        var body: RigidBody3D = _chunk_bodies[id]
        if body.freeze:
            body.freeze = false
            body.sleeping = false
        body.apply_central_impulse(Vector3.DOWN * 1.5)
```

### 碎块设计规则

- **离线预切分**，不要运行时切割网格。运行时凸分解会卡主线程，且没有现成的库。
- 碰撞用 **`ConvexPolygonShape3D`**，不用三角形网格。Jolt 下凸多边形的质心和惯量计算更准确，这正是碎块翻滚是否自然的关键 [来源](https://raw.githubusercontent.com/godot-jolt/godot-jolt/master/README.md)。
- 块的最小尺寸保持在 **0.1 m 以上**，太小的碎片改用粒子/贴花表现。这既是尺度建议，也避开 margin 和 speculative contact 的问题。
- 相邻块**轻微重叠或做互锁凸起**，用来抵消第二.6 条的接缝幽灵碰撞。
- **完整期每段用一个凹多边形 body**，让 active edge detection 起作用；只在真正破坏时才拆成多 body。

### 数值与设置清单

| 设置项 | 建议 | 理由 |
|---|---|---|
| `physics/3d/physics_engine` | `Jolt Physics`（4.4+） | 4.3 需装扩展并选 `Jolt Physics (Extension)` |
| `jolt_physics_3d/collisions/collision_margin_fraction` | 保留默认或略调低，**不要设 0** | 太小会导致碰撞法线异常 |
| `jolt_physics_3d/simulation/allow_sleep` | 开启 | 碎块静止后自动降开销 |
| `jolt_physics_3d/limits/temporary_memory_buffer_size` | 按最大同时坍塌量上调 | 固定预算，事故现场才知道不够 |
| `jolt_physics_3d/simulation/generate_all_kinematic_contacts` | **默认不开**，只在确实需要时开 | 大型运动学体 + 复杂静态几何的组合代价高 |
| `jolt_physics_3d/simulation/baumgarte_stabilization_factor` | 碎块下陷时小幅上调，别到 1.0 | 1.0 一步消除穿透但常常不稳定 |
| `jolt_physics_3d/queries/enable_ray_cast_face_index` | 只在需要面索引时开 | 凹多边形内存 +25% |

### 回收

按碎裂时序做环形缓冲：同时活跃碎块超过阈值（比如 150）时，把最老的、速度低于阈值的碎块 `freeze = true` 或直接合并回静态 body。Jolt 没有内置的聚合或 LOD，这一层必须自己写。

---

## 四、失效边界：这套方案在哪里会崩

**1. 需要真实荷载重分配的坍塌**
连通性只能回答“还连着”和“断了”两种状态。真实的结构倒塌里，柱子断了以后旁边柱子承受三倍荷载，会在几秒后跟着断。要这个效果，你要写自己的应力/荷载求解器，而它的输入**不能是** `get_contact_impulse()`（多体接触下不准确）。这条限制是结构性的，不是调参能解决的。

**2. 由大量独立碎块拼成的地板和墙面**
如第二.6 所述，鬼影碰撞的缓解不跨 body。碎块墙拼出的可破坏掩体，玩家贴墙滑动时可能会卡顿、被顶飞。可接受的做法是把掩体做成“整块凹多边形 + 若干假装饰碎块”，只在被摧毁那一刻才真正拆开。

**3. 薄于约 0.1 m 的碎块**
低于 Jolt 建议的尺度区间 [来源](https://raw.githubusercontent.com/godot-jolt/godot-jolt/master/README.md)，margin 的收缩-加壳会让薄板实际体积偏差明显，快速碎片还会穿透。薄玻璃、薄木板建议不要用物理模拟，不要承担这份代价。

**4. 一次性几百块同时激活**
临时内存是固定预算，且没有自动降级。现场崩是“最后一块豆腐”压垮的，必须靠自建上限兜住。

**5. 需要精确冲量数值的任何设计**
按冲击力扣血、按冲量算声音大小、按冲量算粒子量——在单接触时能用，在多接触时都不可靠。改成基于自己速度/质量的模型。

**6. 软体、绳索、布料、软限位关节**
`SoftBody3D` 与 `Area3D` 无交互；原生关节的软限位参数被忽略并警告；`JoltHingeJoint3D` 等替代节点不在内置模块里。这类需求在 4.4+ 内置 Jolt 上没有实现路径。

**7. 联网确定性**
不保证。只能同步“哪块碎了、从哪个方向来、多大能量”，让各端各自跑非确定性模拟。视觉上会有分叉，接受不了就只能上回放缓冲。

**8. 运行时动态切网格**
不是不能用，是**没有现成工具**：网格切割、凸分解、UV 与法线重建、碰撞体生成，全部要自己写；而且改已入树的 body shape 本身在 Jolt 下就慢。适合做少量、低频的特殊破坏，不适合做通用碎块系统。

---

## 五、用最小实验验证这些边界（建议先做这个再动手）

别信任何二手结论，包括这份回答。花半天做四个对照实验：

1. **接缝测试**：用 10 个 0.5 m 的盒子拼成一面墙，各是独立冻结 `RigidBody3D`，全部激活后让一个球滚过接缝。观察是否弹飞。→ 验证第二.6 条。
2. **冲量测试**：同一颗子弹分别打在“孤立单块墙”和“三块互相压着的墙”上，打印 `get_contact_impulse()`。看数值差多少。→ 验证第二.3 条。
3. **冻结接触测试**：冻结的 `RigidBody3D`（`FREEZE_MODE_KINEMATIC`）配 `max_contacts_reported = 4`，让另一个刚体砸上去，看 `body_entered` 是否触发。再打开 `Generate All Kinematic Contacts` 对比。→ 验证第二.4 条。
4. **规模测试**：一次性激活 50/150/400 块，记录帧时间与物理耗时。→ 定出你自己的碎块上限。

这四个实验跑完，你对“哪些限制是真的”就不再是听别人说，而是自己量出来的。