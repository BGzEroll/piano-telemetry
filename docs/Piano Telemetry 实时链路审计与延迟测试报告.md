# Piano Telemetry 实时链路审计与延迟测试报告

测试日期：2026-08-22  
测试平台：Windows 11 `10.0.26200`、AMD64 Family 25 Model 97、16 逻辑处理器  
Python：3.12.13（Conda `piano-midi`）  
项目版本：当前工作区 `0.1.0`

## 1. 结论

当前实现满足本项目“实时透传优先、遥测和录制允许丢失”的设计目标，属于表现良好的软实时 MIDI 中间件：

- MIDI 回调严格先向输出端口发送原始消息，再尝试发布遥测副本。
- 回调不会等待 WebSocket、分析器、录制文件或 MIDI 导出。
- 所有跨线程事件队列都有界，满载时丢弃观察数据，不会反压透传回调。
- 5000 个测量样本的纯路由 P99 往返延迟为 **0.328 ms**。
- Web 服务、分析器、WebSocket 消费和 Session 录制同时运行时，P99 为 **0.394 ms**，最大值为 **0.662 ms**。
- 重载场景处理 5500 个事件时，转发、入口队列、录制订阅和 Web 客户端均为 **0 丢失、0 错误**。

上述数值包含两次 Windows 虚拟 MIDI 传递、测试发送端和接收回调，因此不是单纯的 Python 函数耗时。测试未包含电钢 USB、NanoHost/VST、音频驱动和声卡缓冲。

## 2. 实时链路

```text
电钢/虚拟输入
    │ native MIDI callback
    ▼
MidiRouter._handle_message
    ├─ 1. midi_out.send_message(message) ──────────────► NanoHost / VST
    │
    └─ 2. MidiEvent.from_raw + publish_nowait
               │
               ▼
        有界 Ingress Queue
               │ Dispatcher 后台线程
               ├─► Web 有界订阅 ─► 状态分析 ─► WebSocket 客户端有界队列
               └─► Recorder 有界订阅 ─► JSONL 后台写盘 ─► 停止后导出 MIDI
```

音频输出所需的最短路径在第 1 步结束。后续分析、浏览器绘图、录制和导出均位于旁路。

## 3. 代码审计

| 环节 | 当前实现 | 实时性判断 |
|---|---|---|
| MIDI 输入 | `python-rtmidi` 或 teVirtualMIDI native callback | 回调线程进入 Python，属于软实时，不是硬实时 |
| 优先透传 | `MidiRouter._handle_message()` 首先调用 `send_message()` | 顺序正确，观察链路无法先于输出执行 |
| 遥测发布 | `EventDispatcher.publish_nowait()` | 队列满时立即返回并增加 `ingress_drop_total` |
| Dispatcher | 独立后台线程向每个订阅者广播 | 不占用 MIDI callback；订阅者之间不分走事件 |
| Web 订阅 | 容量 4096，`DROP_OLDEST` | Web 落后时保留较新状态，不阻塞 Dispatcher |
| 浏览器客户端 | 每客户端容量 256，满时丢最旧消息 | 慢浏览器不会阻塞其他客户端或 MIDI 路由 |
| Recorder 订阅 | 容量 8192，`DROP_NEWEST` | 写盘落后时保留已有顺序并丢新事件，不反压路由 |
| JSONL 写盘 | 独立 daemon 线程，约 1 秒刷新一次 | 文件 I/O 不发生在 MIDI callback 或 Dispatcher 中 |
| MIDI 导出 | Session 停止后由控制线程执行 | 不在实时链路中；导出期间 MIDI 路由仍可运行 |
| 异常隔离 | 转发和观察发布分别捕获异常 | 观察链路异常不会撤销已经成功的 MIDI 输出 |

### 3.1 已验证的不变量

自动测试覆盖以下关键行为：

- `send_message` 必须发生在 `publish_nowait` 之前。
- 观察发布异常不会从回调传播，也不会影响已完成的输出。
- 慢订阅者丢失自己的事件，不影响快速订阅者接收完整广播。
- Ingress 满时直接丢弃，不要求消费者先腾出空间。
- Recorder 发生入口丢失、订阅丢失或序号缺口时，会把 Session 标记为不完整。
- WebSocket 客户端和录制器使用彼此独立的队列。

完整测试结果：`34 passed`。

## 4. 延迟测试方法

使用 `tests/benchmark_midi_latency.py`，每次只保持一条消息在途：

1. 测试端向 `Piano Telemetry Input` 发送 Control Change 消息。
2. Piano Telemetry 经托管虚拟端口透传。
3. 测试端从 `Piano Telemetry Output` 收到同一消息。
4. 使用 `perf_counter_ns()` 计算发送前到接收 callback 的时间。

每组先预热 500 条，再统计 5000 条；单条超时阈值为 1 秒。

### 4.1 纯路由基线

命令：

```powershell
python tests\benchmark_midi_latency.py --samples 5000 --warmup 500 --json
```

### 4.2 Web 服务常驻

启动 Web 服务及其 Web 分析、Recorder 工作线程，再连接已有路由：

```powershell
python tests\benchmark_midi_latency.py --existing-router --samples 5000 --warmup 500 --json
```

### 4.3 WebSocket + 实际录制重载

在 4.2 的基础上：

- 建立一个持续消费消息的 WebSocket 客户端；
- 启动真实 Session 录制；
- 重复 500 + 5000 条消息；
- 检查路由、Dispatcher、WebSocket 和 Recorder 指标；
- 测试 Session 完成后通过“不保存”接口清理。

## 5. 实测结果

| 场景 | 收到/请求 | 超时 | min | median | mean | P95 | P99 | max | 速率 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 纯路由基线 | 5000/5000 | 0 | 0.104 ms | 0.129 ms | 0.136 ms | 0.162 ms | 0.328 ms | 0.444 ms | 5831 条/s |
| Web 服务常驻 | 5000/5000 | 0 | 0.087 ms | 0.113 ms | 0.119 ms | 0.159 ms | 0.284 ms | 0.816 ms | 6784 条/s |
| WebSocket + 录制 | 5000/5000 | 0 | 0.094 ms | 0.174 ms | 0.185 ms | 0.288 ms | 0.394 ms | 0.662 ms | 4666 条/s |

不同组之间的细小快慢变化属于 Windows 调度、CPU 状态和短测试窗口抖动，不能解读为 Web 服务会降低延迟。更有意义的是三组均无超时，且最重场景的 P99 仍低于 0.4 ms。

重载场景结束时的完整指标：

| 指标 | 结果 |
|---|---:|
| `events_received_total` | 11000 |
| `events_forwarded_total` | 11000 |
| `forward_errors_total` | 0 |
| `observer_publish_errors_total` | 0 |
| `ingress_drop_total` | 0 |
| `dispatch_errors_total` | 0 |
| `websocket_drop_total` | 0 |
| 本次录制事件 | 5500 |
| Recorder 订阅丢失 | 0 |
| Session 完整性 | `complete: true` |

正常钢琴 Note On/Off、踏板和少量控制消息的速率通常远低于本测试约 4666 条/秒的完成速率，因此当前实现具有充足余量。若开启 MIDI Clock、Active Sensing 或大体积 SysEx，事件率和单消息成本会提高，仍应以实际设备复测。

## 6. 剩余风险与限制

### 6.1 不是硬实时系统

Windows、CPython GIL、垃圾回收和系统线程调度都可能造成偶发长尾。当前结果证明本机软实时表现优秀，但不能承诺严格的最坏执行时间。

### 6.2 驱动发送是最短路径中的必要阻塞点

`send_message()` 必须同步交给 MIDI 驱动，无法像遥测一样丢弃。如果 teVirtualMIDI、USB 驱动或目标应用异常卡住，仍可能拉长 callback。这是当前最主要的外部风险。

### 6.3 `Queue.put_nowait()` 不等待容量，但仍使用短临界区

Python `Queue` 的 `put_nowait()` 不会等待空位，但内部需要短暂获取互斥锁。它不会形成容量反压；在极端线程争用下仍可能产生微小调度抖动。

### 6.4 Web 事件循环调度队列没有显式总量上限

Web 订阅和每客户端队列均有界，但 `loop.call_soon_threadsafe()` 提交到 asyncio 的待执行 callback 队列本身没有本项目级容量限制。浏览器或事件循环严重卡顿时不会反压 MIDI callback，但可能增加进程内存和 UI 延迟。后续如需更强过载保护，可将线程到事件循环之间改成“单次待调度 + latest 状态覆盖”。

### 6.5 测试边界

本报告没有测量：

- 电钢琴 USB 输入延迟；
- NanoHost/VST 合成时间；
- ASIO/WASAPI 缓冲及声卡输出延迟；
- 长时间运行后的系统温度、节能策略和后台负载影响；
- 睡眠/唤醒、设备热插拔或驱动异常。

## 7. 建议

1. 保持 SysEx、MIDI Clock 和 Active Sensing 默认关闭，只在实际需要时启用。
2. 发布版本继续保留当前 drop/error 指标；Session 不完整时必须明确提示。
3. 在目标演奏电脑、电钢、NanoHost 和实际音频缓冲配置下，再运行 `--existing-router` 基准。
4. 若后续增加更多观察订阅，继续坚持有界队列和非阻塞 overflow 策略。
5. 如需长期稳定性数据，增加 30–60 分钟的并发 WebSocket、录制和 MIDI Clock soak test。

## 8. 最终判定

当前链路可以继续作为低延迟演奏中间件使用。以本机实测数据看，Piano Telemetry 本身引入的虚拟 MIDI 往返长尾很低，开启 Web 可视化和录制后仍保持亚毫秒级 P99；实时链路和尽力而为观察链路的隔离设计有效。
