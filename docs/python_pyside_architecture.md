# Python + PySide 桌面应用架构规范

**适用范围**：使用 Python 与 Qt for Python（PySide）构建的桌面 GUI 应用。本文按技术栈和应用类型制定，不以任何特定代码库的现有目录、类或实现为前提。

**性质**：这是架构边界规范，不是 UI 视觉规范、性能基准手册或发布清单。本文中的“必须 / 不得”是默认架构约束；“应”表示强推荐；“可”表示允许选项。偏离必须说明具体原因、影响和退出条件，不能只写“当前代码如此”。

**权威范围**：本文是 Python + PySide 架构、线程归属、后台任务和 Qt model/view 边界的唯一规范。`docs/software_standards.md` 是跨领域历史参考汇编，不再作为这些主题的硬性依据。本文不取代项目维护规则、数据契约或用户明确的行为要求。

## 1. 设计目标

架构首先要保证职责清楚、依赖方向稳定、界面事件循环能够继续工作、后台任务生命周期可管理，以及核心行为能脱离 GUI 测试。分层的目的不是增加文件或类的数量，而是让变化和副作用有清楚的归属。

既有目录、类名、worker 类型和内部调用链不是必须保留的架构契约。达到边界要求时可以重划模块、替换执行机制或整体重写内部实现；用户可见行为、外部接口和持久数据语义若要改变，则必须作为独立产品/兼容性决策说明。

## 2. 责任边界

| 边界 | 负责内容 | 不负责内容 |
|---|---|---|
| 表现层 | 控件与视图、用户输入转换、展示状态、把应用结果映射到界面 | 持久化细节、业务规则、长时间计算、直接编排多种基础设施 |
| 应用层 | 用户可触发的用例、步骤编排、事务边界、调用领域能力、声明所需端口 | Qt 控件、界面文案、具体数据库或文件格式 |
| 领域层 | 业务概念、规则、不变量和可独立计算的逻辑 | Qt、界面状态、文件/网络/数据库访问、线程与进程调度 |
| 适配与基础设施层 | 文件、数据库、网络、操作系统及非界面 Qt 平台能力等外部接口的实现 | 决定用户操作流程或持有领域规则的第二份权威实现 |
| 组合根 | 创建具体实现、装配依赖、确定应用生命周期 | 承载业务流程或成为所有模块的共享状态仓库 |

### 2.1 依赖规则

- `UI → 应用 → 领域` 是默认依赖方向。领域层不得依赖 UI、应用层或基础设施。
- 应用层通过自己定义的接口或契约使用外部能力；基础设施实现这些接口。组合根可以同时了解各层并负责装配。
- 模块按稳定的业务能力或技术责任组织。小型能力不必为形式上的分层单独创建包；无论如何组织文件，依赖方向和责任边界必须保持成立。
- 一个用例可以有独立的处理逻辑；这不意味着每个用例都需要一套独立的线程、进程、任务服务或生命周期框架。
- 禁止循环依赖、隐藏的反向调用和通过全局可变对象绕过接口。跨边界调用的输入、输出、错误和副作用必须可辨认。

### 2.2 Modular Monolith and Vertical Slices

- The default application shape is a modular monolith: one desktop application and deployment unit, with cohesive in-process capability modules assembled by a small composition root. Task-specific worker processes remain valid under section 4; they do not turn a feature into a separately deployed service.
- Organize code primarily as vertical slices around stable user or business capabilities. A slice may own its UI adapter, application use cases, domain rules, infrastructure adapters, and tests while preserving the dependency direction in section 2.1. Do not create empty layers or duplicate shared infrastructure merely to make every slice look identical.
- Each slice exposes a deliberate public entry point. Other slices depend on that contract, not on its internal widgets, handlers, persistence details, or private modules. Cross-slice coordination belongs in an application use case or the composition root, according to responsibility.
- Keep genuinely cross-cutting facilities in small shared modules with explicit contracts. Shared modules must not become a second home for feature-specific workflows or mutable business state.
- Make feature ownership discoverable: the owning slice is responsible for its application registration, settings keys, resources, dependencies, migrations, tests, and user documentation. Adding or removing a capability must update or remove each owned artifact; architecture checks should detect stale registrations and forbidden cross-slice imports where practical.
- Vertical slices do not imply one worker, thread, process, or task service per capability. Follow the shared execution-facility rules in section 4.

### 2.3 跨边界数据

- 跨层传递稳定的数据契约，不把 `QWidget`、视图项、信号对象或其他界面对象交给领域逻辑或后台任务。
- 进程边界只传可序列化、可独立解释的数据；不得传线程锁、打开的文件句柄、数据库连接或依赖进程内身份的对象。
- 边界数据可以采用领域对象、值对象或 DTO；规范不强制所有数据复制成多份模型。转换只在确有职责边界时发生，并明确谁拥有权威状态。

## 3. Qt 对象与线程归属

- `QWidget` 及其绘制、布局、焦点和输入事件必须在 GUI 线程处理。与 GUI view 连接的 Qt model 也在 GUI 线程创建和更新；其他 `QObject` 在其归属线程内使用和销毁。
- `QObject` 有线程归属。跨线程交互使用队列信号槽、`invokeMethod` 或该 API 明确支持的线程安全调用；不得因为一次运行“看起来正常”就直接跨线程读写对象。
- 后台代码不得持有或操作界面对象，也不得直接修改 GUI model。后台结果回到 GUI 线程后，由界面适配层决定如何呈现或提交。
- UI 线程不得同步等待后台结果，也不得在事件回调里执行可能长时间阻塞的 I/O 或无界计算。任务已移出 UI 线程不代表完成了响应性设计；结果解码、差异计算和最终界面提交同样必须纳入责任分析。
- 默认采用单 UI 进程：界面和 Qt 对象由 UI 线程负责，非界面工作交给共享后台线程执行。若操作必须修改归属 GUI 线程的控件或文档且无法安全移入工作线程，应优先在 UI 线程按可取消的小段执行；当线程模型仍无法满足进度或取消交互时，可使用独立辅助进程承载进度/取消界面。辅助进程只通过明确 IPC 交换数据，不得访问 UI 进程的 Qt 对象；该模型不会让被阻塞的 UI 进程恢复响应。取消必须在安全分段边界检查，并在报告取消前恢复操作前状态。
- `processEvents()` 不得作为长任务的通用调度手段。它会在原操作尚未完成时重入事件处理；确需显式泵事件的特殊集成代码必须隔离，并记录重入保护和验证理由。
- 不规定统一的“每段代码必须少于 16 ms”硬门槛。帧间隔是呈现性能的参考，不是脱离刷新率、工作负载和交互目标的普遍架构常数。架构审查要证明长任务期间相关界面操作仍能被处理；具体延迟目标由独立的产品体验要求定义。

## 4. 后台任务与执行设施

### 4.1 任务逻辑与调度分离

- 用例逻辑表达“要做什么”；执行设施负责排队、并发上限、任务标识、生命周期、结果回传和资源回收。二者不得混成一个只服务于某个窗口的 worker 类。
- 多个能力应复用共享的执行设施或明确分工的执行池。业务能力可以有自己的 task handler，但不得各自重新实现线程/进程创建、等待、取消和结果传递。
- 共享设施不能成为巨型业务 worker：任务输入和结果使用显式契约，具体业务处理留在所属用例或 handler 中。
- 并发数量必须受控；系统应定义关闭时如何等待或取消任务、任务失败如何报告、过期结果如何忽略，以及重复请求如何合并或拒绝。

### 4.2 按工作性质选择执行方式

| 工作性质 | 默认选择 | 需要判断的事项 |
|---|---|---|
| 阻塞 I/O | 支持的异步接口，或有界线程池 | 库是否线程安全、取消能否传递、连接和文件资源由谁关闭 |
| 纯 Python CPU 计算 | 先评估共享后台线程能否满足 UI 响应目标；若 GIL 竞争仍造成明显阻塞，再采用 UI 进程外的工作进程或改用可证明释放 GIL 的实现 | 工作量是否足以抵消进程启动与数据序列化成本；是否需要并行或隔离 |
| Qt/C 扩展或原生计算 | 仅在其文档说明释放 GIL、线程安全且生命周期清楚时考虑线程执行 | GIL 行为、库的线程约束、输入输出是否可安全共享 |
| 短小且有界的计算 | 可在调用线程完成 | 它是否确实短小、有界，并且不包含同步 I/O 或随数据量增长的全量工作 |

上表是决策起点，不是“所有任务一律用进程 / 线程 / async”的命令。默认优先 GUI 线程负责呈现、共享后台线程执行非界面工作；只有线程模型不能满足操作约束或交互要求时，才考虑独立辅助进程。长时间纯 Python CPU 工作不得留在 GUI 线程；采用进程时须考虑 IPC 数据形状、取消语义、启动成本及平台启动方式。

### 4.3 任务契约

- 需要进度时，进度描述真实阶段或可计算的完成量；信号按可见更新需要节流，不得每个循环迭代都通知界面。
- 取消仅在工作能够检查取消请求并安全停止时提供。取消请求、任务停止、失败和成功是不同结果，不得把“请求已发送”显示成“任务已完成”。
- 用户发起新请求、切换上下文或关闭窗口后，旧任务结果不得覆盖较新的状态。使用任务 ID、版本号或等价机制判定结果是否仍有效。
- 后台完成后的合并和界面提交也要避免一次性大规模阻塞；优先使用正确的批量通知、差异更新、惰性加载或受控分块，并保持状态一致。
- Shared derived work must be demand driven. Its active consumers declare the minimum result or scope they need, and the coordinator runs only the broadest currently requested level. With no active consumers, cancel or invalidate pending work and keep the expensive provider idle. Re-enabling a consumer after discarding its cached base requires rebuilding a valid base before applying incremental changes.

### 4.4 进度窗口与 UI 辅助进程

- Every progress session uses the application-wide `TaskProgressController` and its single UI helper process. Feature slices must not create local progress dialogs or start helper processes themselves. The helper may display several concurrent task windows, each identified by a stable task ID.
- Progress modes are independent of the display host. Every session explicitly selects `ProgressMode.NONE`, `ProgressMode.INDETERMINATE`, or `ProgressMode.DETERMINATE`. Determinate mode requires a real positive total; numeric updates must not infer or change the mode. When a task reaches a measurable phase, switch modes explicitly.
- Helper windows use the Qt tool-window flag so they do not create a system taskbar button. The helper process receives only serializable task commands over local IPC and must not access widgets, models, or other Qt objects owned by the main process.
- Before a helper window is shown, the main process dims and blocks its owning top-level window with a shape-matched overlay. Overlays are shared per owner and remain until all progress sessions for that owner are dismissed.
- The helper process keeps progress painting responsive when the main UI thread is blocked. Cancellation requests return to the main process over IPC and are handled when its event loop can run; long work must still check cancellation at safe boundaries and preserve consistent state.
- 应用组合根负责创建、预热和关闭唯一的进度控制器。控制器退出时先释放遮罩并停止辅助进程；进度会话按任务 ID 更新、取消和结束。

## 5. Qt Model/View 与批量更新

- 小型、静态、简单的数据可使用便利控件；当数据量、更新频率、排序过滤或惰性加载要求使便利控件难以维护时，采用 Qt Model/View。不存在适用于所有应用的固定条目数阈值。
- model 的所有权和线程归属必须清楚。若 model 是 `QObject`，遵守其线程归属；在 view 所属 GUI 线程完成用于显示的 model 更新。
- 通知必须准确反映操作：插入行使用插入通知，删除行使用删除通知，现有数据改变使用 `dataChanged` 或对应信号，整体替换才使用 reset。不得用 `beginInsertRows/endInsertRows` 包裹与插入无关的修改。
- 连续多项变更应合并为语义正确的批次，避免每项操作都触发全量布局或昂贵的重复刷新。数据变化期间 begin/end 配对且行范围必须准确。
- 只有所有相关行高度确实统一且显示行为允许时，才启用统一行高优化；不得为了满足通用规则破坏可变行高需求。
- 大数据源按需读取、分页或虚拟化是否合适，取决于数据访问成本、用户交互和一致性要求；model 可以拥有受控的数据表示，不强制采用单一存储形状。

## 6. 状态、副作用与失败

- 每项业务状态有单一权威来源；界面选择、焦点、展开状态等纯呈现状态可由表现层拥有。缓存和派生值不得在没有一致性策略时变成第二个权威来源。
- 文件、数据库、网络等副作用由适配器实现，并通过应用层明确的操作入口调用。涉及多步持久化修改时，事务或原子性由实际存储契约保证，不在 UI 层手写隐式补偿。
- 错误在边界处增加操作上下文并转换成调用方能处理的类型。日志记录应避免同一异常在每层重复记录；面向用户的消息由表现层生成，不把原始堆栈或敏感信息直接显示给用户。
- 资源获取与释放责任必须可追踪，任务取消、异常、窗口关闭和进程退出路径都应纳入生命周期设计。
- User settings and transient presentation state are different contracts. A user preference must have an explicit default, a stable owning feature key, and a defined persistence scope. Unless the product explicitly says otherwise, a user-changed preference is restored across application sessions.
- Load persisted preferences before assembling the feature that consumes them. Persist changes through an infrastructure adapter rather than from widgets; settings that can apply safely at runtime should take effect immediately and must not require a restart.
- Defaults must remain valid when a key is absent, corrupt, or from an older schema. A reset-to-default action restores the documented default without silently deleting unrelated user data; migrations must be explicit when a setting changes meaning.
- Persistent inline status, validation, and error messages should use a shared presentation component. Use modal dialogs only when the user must make a decision or acknowledge a blocking condition; do not create feature-specific copies of the shared inline message style.

## 7. 日志与诊断

- 应用日志统一使用 Python 标准库 `logging`；模块通过 `logging.getLogger(__name__)` 或项目定义的 logger 层级获取 logger，不直接配置全局 root logger。
- 基础运行日志（至少是警告、错误和关键生命周期事件）默认保持可用；用户开关控制的是更详细的诊断日志，而不是让应用在故障时完全失去可追踪性。
- 由组合根或共享基础设施统一创建 logger、handler、formatter、级别和生命周期。表现层的日志开关只能调用明确的应用服务，不得自行创建、移除或重复配置 handler。
- `DEBUG` 用于详细诊断，`INFO` 用于正常生命周期和重要操作，`WARNING` 用于可恢复问题，`ERROR` 用于操作失败，`CRITICAL` 仅用于应用无法继续的严重故障。异常边界使用 `logger.exception(...)` 保留堆栈。
- 同一异常只在一个合适的边界记录一次；下层可以增加操作上下文并继续抛出，上层负责把失败转换为用户可理解的消息。不得把原始堆栈直接显示给用户。
- 文件日志写入每用户应用数据或状态目录，并使用大小轮转和有限保留数量。开发环境可额外输出标准错误；生产环境不得依赖当前工作目录保存日志。
- 日志记录应包含模块、操作、结果以及必要的任务 ID 或关联 ID。不得记录密码、令牌、完整文件内容、原始用户数据或不必要的敏感路径。
- GUI 线程和后台任务都可以调用线程安全的 logger；高频或可能阻塞的日志写入应使用队列处理。进度日志按阶段或受控频率记录，不得为每个进度 tick 写一条日志。
- Qt 消息可以通过 `qDebug`、`qInfo`、`qWarning`、`qCritical` 和集中式 message handler 接入，但必须防止 Qt handler 与 Python logger 互相转发形成递归。`qFatal` 不作为普通业务错误处理。
- 关闭窗口、取消任务、资源释放和进程退出时，日志设施必须有明确的关闭顺序；日志失败不得阻塞正常的用户退出路径。

## 8. 验证方式

- 领域规则和应用用例优先以不启动 Qt GUI 的单元测试覆盖；适配器用契约或集成测试验证外部行为。
- Qt model 测试核验行数、数据角色、排序过滤及通知语义；跨线程任务测试核验成功、失败、取消、重复/过期结果和关闭行为。
- UI 自动化集中验证关键用户流程和状态呈现。对长任务，验证用户仍能执行目标所需的窗口、输入、导航等操作，并验证完成后的结果应用也可操作；不能以“使用了 worker”或“总耗时下降”单独宣称界面不卡。
- 测试隔离业务逻辑和 UI 绑定；不为形式覆盖率而把简单映射强拆成多层，也不在 GUI 测试里重复测试已经由应用层测试回答的问题。

## 9. 架构审查清单

1. 业务规则和用例是否能在没有控件、Qt 事件循环和真实存储的条件下理解与测试？
2. 依赖方向、状态所有权、持久化副作用和跨层数据契约是否明确？
3. UI 回调是否同步等待、执行全量工作，或在任务完成后又进行大量同步提交？
4. 线程 / 进程设施是否共享且有界，任务逻辑是否仍按业务能力隔离？
5. 窗口关闭、取消、失败、过期结果和并发请求是否有定义？
6. Qt model 的通知是否与真实数据变化类型一致，批量更新是否避免重复刷新？
7. 有无仅凭线程类存在、目录名称或一次成功运行来证明边界正确？

## 10. 参考依据与适用边界

Qt 与 Python 官方文档用于确定框架和运行时行为；架构分层与职责组织属于本规范结合桌面应用场景制定的项目中立要求，并非声称某个单一外部标准规定了唯一结构。

- Qt: [Threads and QObjects](https://doc.qt.io/qt-6/threads-qobject.html)、[QThread](https://doc.qt.io/qt-6/qthread.html)、[QCoreApplication.processEvents](https://doc.qt.io/qt-6/qcoreapplication.html#processEvents)
- Qt: [Model/View Programming](https://doc.qt.io/qt-6/model-view-programming.html)、[QAbstractItemModel](https://doc.qt.io/qt-6/qabstractitemmodel.html)、[Fetch More](https://doc.qt.io/qt-6/qtwidgets-itemviews-fetchmore-example.html)
- PySide: [QThread](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QThread.html)、[QAbstractItemModel](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QAbstractItemModel.html)
- Python: [threading](https://docs.python.org/3/library/threading.html)、[multiprocessing](https://docs.python.org/3/library/multiprocessing.html)、[asyncio](https://docs.python.org/3/library/asyncio.html)、[Global Interpreter Lock](https://docs.python.org/3/glossary.html#term-global-interpreter-lock)
- Python: [Logging HOWTO](https://docs.python.org/3/howto/logging.html)、[Logging Cookbook](https://docs.python.org/3/howto/logging-cookbook.html)
- Qt: [Qt Logging](https://doc.qt.io/qt-6/qtlogging.html)
- 架构概念参考：[Separated Presentation](https://martinfowler.com/eaaDev/SeparatedPresentation.html)、[Hexagonal Architecture](https://alistair.cockburn.us/hexagonal-architecture/)

这些参考资料不意味着 Android ANR 时限、Web RAIL 数值、特定帧预算、固定条目数或某一种 worker 结构自动成为 PySide 桌面应用的硬要求。采用任何量化目标时，必须另行说明目标交互、适用环境和验收方式。
