# Piano Telemetry 项目评估与修订报告

更新日期：2026-08-20

## 1. 结论

项目总体可行。现有环境已经具备 Python 3.12 和 Windows 虚拟 MIDI 的基础条件，可以进入技术验证阶段。

本次修订确定三项核心决策：

1. 事件分发采用广播订阅模型，每个订阅者拥有独立队列，不使用多个模块竞争消费同一个队列。
2. MIDI 实时透传是最高优先级。Recorder、Analyzer、Web 任一模块变慢时均允许丢失观察数据，不得向 MIDI 转发链路施加反压。
3. 当前版本移除 OpenClaw、AI 教练、长期记忆以及为 OpenClaw 单独设计的 TCP Query/Control API。

调整后，第一阶段产品定位为：

> Windows 上低延迟的电钢琴 MIDI 透传、练习记录和浏览器实时可视化工具。

## 2. 本机环境评估

### 2.1 已确认项目

| 项目 | 当前状态 | 评估 |
|---|---|---|
| Miniconda | 已安装于 `C:\software\miniconda3\miniconda3` | 可用 |
| Conda 环境 | `piano-midi` 已存在 | 可用 |
| Python | 3.12.13 | 符合项目要求 |
| loopMIDI | 1.0.16.27，进程正在运行 | 可用于 Python → NanoHost 的虚拟 MIDI 路由 |
| 项目代码 | Phase 0/1 基础已实现 | 等待真实 MIDI 端口完成链路验证 |

### 2.2 需要处理的环境事项

当前 PowerShell 没有加载 Conda 初始化，因此直接执行 `conda` 会找不到命令。可以使用以下任一种方式：

1. 在 VS Code 中直接选择解释器：

   ```text
   C:\software\miniconda3\miniconda3\envs\piano-midi\python.exe
   ```

2. 使用 Miniconda Prompt 激活：

   ```powershell
   conda activate piano-midi
   ```

3. 在未初始化的 PowerShell 中使用完整路径：

   ```powershell
   & 'C:\software\miniconda3\miniconda3\Scripts\conda.exe' run -n piano-midi python app.py
   ```

环境已经安装当前阶段所需的 `python-rtmidi 1.5.8`、`mido 1.3.3` 和 `pytest 9.1.1`，项目以 editable 模式安装。FastAPI 等 Web 依赖留到 Phase 3 再加入。

当前 `.vscode/settings.json` 只指定了 Conda 作为环境和包管理器，没有固定具体解释器。开始开发前应确认 VS Code 状态栏选择的是上述 `piano-midi` 环境，避免把依赖安装到 `base`。

loopMIDI 已安装并运行，但仍需在 Phase 0 确认以下配置：

- loopMIDI 中已经创建一个固定名称的端口，例如 `Piano Telemetry Out`。
- Python 将该端口作为 MIDI Output 打开。
- NanoHost 将同一端口作为 MIDI Input 打开。
- 电钢琴硬件端口没有同时被其他独占程序占用。

## 3. 修订后的范围

### 3.1 当前范围

- 电钢琴 MIDI 输入。
- MIDI 低延迟透传到 loopMIDI。
- NanoHost / VSTi 正常发声。
- Session 管理。
- JSONL 原始事件记录。
- Session 结束后的 Standard MIDI 文件导出。
- 当前按键、延音踏板、力度、和弦状态。
- WebSocket 实时推送。
- 浏览器钢琴键盘和 MIDI 瀑布流。
- 基础本地分析。

### 3.2 当前删除的范围

- OpenClaw 集成。
- AI 练习点评。
- LLM 长期练习记忆。
- OpenClaw TCP Server。
- OpenClaw Query / Control API。
- Piece Progress 的 AI 管理。
- 互动式 AI 乐理教学。

Score Following 和 MusicXML 不依赖 OpenClaw，可以作为远期本地功能保留，但不进入第一版 MVP。

## 4. Event Queue 能否实现订阅广播

可以，但不能让所有模块直接消费同一个普通队列。

普通队列的行为是竞争消费：

```text
                    ┌── Recorder 取走 Event A
Shared Queue ───────┼── Analyzer 无法再取得 Event A
                    └── Web 也无法再取得 Event A
```

这不符合项目需求。正确模型是先由唯一 Dispatcher 消费入口队列，再将每个事件分别投递到每个订阅者自己的队列：

```text
Digital Piano
      │
      ▼
MIDI Input Callback
      │
      ├── 1. 立即发送 → loopMIDI → NanoHost
      │
      └── 2. try_publish(event)
                    │
             Bounded Ingress Queue
                    │
                    ▼
                Dispatcher
          ┌─────────┼─────────┐
          ▼         ▼         ▼
     Recorder Q  Analyzer Q  Web Q
          │         │         │
       Recorder  Analyzer  WebSocket
```

Dispatcher 对每个订阅者执行一次独立投递。Recorder 从 `Recorder Q` 取走事件，只会删除 Recorder 自己队列中的引用，不会影响 Analyzer 和 Web 的队列。

事件对象应设计为不可变对象。广播时一般不需要深拷贝完整数据，只需把同一个不可变事件引用放入多个订阅者队列。

### 4.1 为什么仍保留入口队列

不建议在 MIDI callback 中直接遍历所有订阅者。订阅者数量增加后，即使使用非阻塞写入，callback 工作量也会随订阅者数量增长。

因此 callback 只面向一个入口队列：

1. 获取原始 MIDI 数据和时间戳。
2. 分配递增 `seq`。
3. 立即向 loopMIDI 输出。
4. 尝试把观察事件放入入口队列。
5. 立即返回。

订阅管理、广播、序列化和状态计算均由 Dispatcher 或下游工作线程完成。

## 5. 实时优先与丢弃策略

### 5.1 实时链路

核心链路只有：

```text
MIDI Input Callback → MIDI Output Send
```

这一步必须先于观察事件发布。观察队列已满、Recorder 停顿、浏览器断线等情况不改变 MIDI Output Send 的执行。

Python 和 Windows 不是硬实时系统，因此“绝不阻塞”应理解为工程上的最高优先级和故障隔离目标，而不是操作系统级的绝对时限保证。

### 5.2 所有队列必须有界

禁止使用无限增长队列。无限队列虽然暂时不丢数据，但消费者卡住后会持续占用内存，最终仍可能拖垮 MIDI Core。

建议的队列策略：

| 队列 | 满载策略 | 说明 |
|---|---|---|
| Ingress Queue | 丢弃观察副本，MIDI 继续转发 | 记录 `ingress_drop_total` |
| Recorder Queue | 丢弃新事件或一段旧事件 | 最终 Session 标记为 `incomplete` |
| Analyzer Queue | 清空积压并发送 `stream_gap` | Analyzer 重置当前状态，避免永久卡音 |
| Web State Queue | 只保留最新状态 | 旧状态没有继续发送的价值 |
| Web Event Queue | 丢弃最旧事件 | 瀑布流允许出现短暂缺口 |
| 每个 WebSocket 客户端队列 | 丢弃或断开慢客户端 | 一个慢客户端不得影响其他客户端 |

### 5.3 缺失必须可见，但无需阻止演奏

允许丢失记录不等于静默丢失。至少维护以下计数：

```text
events_received_total
events_forwarded_total
forward_errors_total
ingress_drop_total
recorder_drop_total
analyzer_drop_total
web_drop_total
```

`seq` 在进入观察系统之前分配。只要订阅方发现序号不连续，就知道中间发生了数据缺失。

发生丢弃后，可在数据流恢复时附加：

```json
{
  "kind": "stream_gap",
  "from_seq": 18322,
  "to_seq": 18407,
  "reason": "subscriber_queue_full"
}
```

Session 汇总中同时保存丢失数量：

```json
{
  "complete": false,
  "dropped_events": 86
}
```

## 6. MIDI 技术方案

### 6.1 建议的库边界

- `python-rtmidi`：负责实时输入 callback 和原始字节输出。
- `mido`：负责 MIDI 消息解析和 Session 结束后的 `.mid` 文件生成。
- FastAPI / Uvicorn：负责 HTTP、静态页面和 WebSocket。

实时 callback 中优先使用 `python-rtmidi` 的原始字节接口，避免不必要的对象转换和 JSON 构造。Mido 不需要进入最短透传路径。

### 6.2 MVP MIDI 消息范围

第一版重点支持：

- Note On / Note Off。
- Control Change，尤其是 CC64 Sustain。
- Pitch Bend。
- Channel Pressure / Polyphonic Aftertouch。
- Program Change。

SysEx、MIDI Clock 和 Active Sensing 默认过滤。它们可能产生高频或变长数据，且普通钢琴演奏遥测通常不依赖这些消息。如未来确有需求，再逐项启用并重新做压力测试。

### 6.3 统一事件模型

建议以原始字节为事实源，解析字段为派生值：

```json
{
  "schema_version": 1,
  "kind": "midi_event",
  "seq": 18322,
  "captured_monotonic_ns": 83918273192831,
  "session_time_ns": 1283912231,
  "source_port": "Digital Piano",
  "raw": [144, 64, 81],
  "type": "note_on",
  "channel": 0,
  "note": 64,
  "velocity": 81
}
```

约束如下：

- 所有 JSONL、WebSocket 和 Analyzer 使用相同字段名称。
- `raw` 始终保留原始消息。
- 不再同时使用 `event/type`、`t_ns/timestamp_ns` 等多套命名。
- `Note On velocity=0` 在状态计算时按 Note Off 处理，但原始字节不改写。
- 所有音符和踏板状态按 MIDI channel 隔离维护。

## 7. 状态与分析

### 7.1 两类音符状态

```text
physical_notes：物理按下且尚未收到 Note Off 的音符
sounding_notes：物理按下或由 Sustain 保持的音符
```

收到 `stream_gap` 后，状态分析器应立即清空临时状态并标记为 `uncertain`，而不是继续保留可能已经错误的按键或踏板状态。收到后续完整状态重建点后再恢复为 `valid`。

需要处理：

- Note On velocity 0。
- CC64 半踏板数值。
- CC120 All Sound Off。
- CC121 Reset All Controllers。
- CC123 All Notes Off。
- MIDI 设备断开。
- Session 停止和程序正常退出时的状态清理。

### 7.2 和弦识别

和弦识别不应简单使用踏板下全部 `sounding_notes`，否则旧音会不断累积。建议同时输出：

- `held_chord`：根据当前物理按键识别。
- `onset_chord`：根据最近约 50–100 ms 内的新 Note On 分组识别。
- `sounding_pitch_classes`：仅作为踏板背景参考。

第一版和弦识别支持 Major、Minor、Dim、Aug、7、Maj7、m7、sus2、sus4 和常见转位即可。

### 7.3 Tempo 的边界

没有参考谱、节拍器标记或 MIDI Clock 时，不能把任意 Note On 间隔直接解释为准确 BPM。第一版可以提供：

- Note onset rate。
- IOI 分布。
- 连续音型均匀度。
- 用户指定目标 BPM 时的偏差。

自动 BPM 估计应带置信度，不应作为确定事实显示。

## 8. Session 与存储

### 8.1 Session 状态机

```text
IDLE
  ↓ start
RECORDING
  ↓ stop
FINALIZING
  ├── CLOSED
  └── ABORTED
```

每个 Session 保存：

```text
sessions/<session_id>/
├── session.json
├── events.jsonl.part
├── session.mid
└── summary.json
```

建议使用 UUID 或 ULID 作为真实 `session_id`，时间字符串只作为人类可读标签，避免同一秒内发生冲突。

### 8.2 时间系统

- `captured_monotonic_ns` 使用 `time.perf_counter_ns()`，负责进程内精确排序。
- `session_time_ns` 使用 monotonic 起点计算。
- `session.json` 另外保存 UTC `started_at` 和 `ended_at`，用于跨 Session 的历史排序。

### 8.3 写入和恢复

- Recorder 在独立线程批量写 JSONL。
- 写盘绝不发生在 MIDI callback 或 Dispatcher 中。
- 录制中使用 `.part` 文件。
- 正常结束后 flush、关闭并原子改名为 `events.jsonl`。
- 程序重启时检测残留 `.part`，将 Session 标记为 `aborted`，保留已经成功写入的数据。
- Session 结束后根据 JSONL 生成 `.mid`，不要在 callback 中持续修改 Standard MIDI 文件。
- 若发生丢弃，仍可生成 MIDI 文件，但必须在 `session.json` 和 UI 中显示“不完整”。

## 9. Web 架构

移除 OpenClaw 后，第一版不再需要单独的 TCP Server：

```text
FastAPI
├── HTTP：页面、配置、Session 查询和控制
└── WebSocket：实时 MIDI event 和最新 state
```

WebSocket 建议区分两类数据：

- `event`：瀑布流需要的增量音符事件，允许丢失。
- `state`：当前键盘、踏板和和弦快照，只保留最新值。

客户端首次连接或重连时先取得完整 `state`，再接收增量事件，避免重连后出现永久卡键。

服务默认只监听 `127.0.0.1`。如果以后允许局域网访问，再增加认证、来源限制和配置选项。

## 10. 修订后的模块结构

```text
piano_telemetry/
├── app.py
├── midi/
│   ├── input.py
│   ├── output.py
│   ├── router.py
│   ├── clock.py
│   └── event.py
├── core/
│   ├── dispatcher.py
│   ├── subscriber.py
│   ├── metrics.py
│   ├── session.py
│   └── config.py
├── recorder/
│   ├── jsonl_recorder.py
│   └── midi_exporter.py
├── analyzer/
│   ├── note_state.py
│   ├── chord.py
│   ├── timing.py
│   ├── dynamics.py
│   └── pedal.py
├── network/
│   ├── http.py
│   └── websocket.py
├── web/
│   ├── index.html
│   ├── app.js
│   ├── waterfall.js
│   └── piano.js
├── data/
│   └── sessions/
└── tests/
    ├── unit/
    ├── integration/
    └── stress/
```

不再包含 `tcp_server.py`、OpenClaw adapter 或 AI 相关模块。

## 11. 开发阶段

### Phase 0 — MIDI 链路验证

目标：验证真实硬件链路，不建设 Web 和 Recorder。

```text
Digital Piano → python-rtmidi → loopMIDI → NanoHost
```

验收内容：

- 正确列出电钢琴输入端口和 loopMIDI 输出端口。
- NanoHost 能持续正常发声。
- Note、力度和 Sustain 正确透传。
- 程序可以处理端口不存在、端口占用和设备中途断开。
- 记录输入时间、输出调用时间和错误计数，为延迟测试建立基线。

### Phase 1 — 实时 Core 与广播

- 不可变 MidiEvent。
- 单一有界 Ingress Queue。
- Dispatcher。
- 每订阅者独立有界队列。
- 非阻塞发布和明确丢弃策略。
- 全局及订阅者级 metrics。
- Observer 异常隔离。

### Phase 2 — Session 与 Recorder

- Session 状态机。
- JSONL Recorder。
- 崩溃恢复。
- 缺失事件统计。
- Session 结束后导出 MIDI。

### Phase 3 — Web UI

- FastAPI HTTP / WebSocket。
- 当前按键。
- Sustain。
- Velocity。
- Piano keyboard。
- Canvas waterfall。
- 连接状态、数据缺口和 Session 完整性提示。

### Phase 4 — 本地分析

- physical/sounding note state。
- Chord。
- Timing / IOI。
- Dynamics。
- Pedal。
- Session summary。

### Phase 5 — 可选 Score Mode

只有基础系统稳定后再评估：

- MusicXML。
- Score follower。
- Expected vs actual。
- 小节级节奏和力度分析。

## 12. 实时验收与故障注入

“弹起来没有差异”可以保留为主观验收，但必须同时有可测指标。

建议执行：

1. 正常弹奏和高密度 MIDI 回放至少 30 分钟。
2. 人为让 Recorder 暂停消费 5–10 秒。
3. 人为让 Analyzer 抛出异常。
4. 模拟磁盘写满或写入失败。
5. 连接一个完全不读取数据的慢 WebSocket 客户端。
6. 反复连接和断开浏览器。
7. 演奏中关闭 Recorder、Web 服务或 Analyzer。

核心通过条件：

- 上述故障发生时 MIDI 仍持续转发到 NanoHost。
- Observer 不得在 callback 中等待队列空间。
- Observer 的异常不得传播到 MIDI callback。
- 内存占用保持有界。
- 发生丢失时对应 drop counter 增长，Session 被标记为不完整。
- 无长期卡音；断流或状态缺口后可以清理并重建 UI 状态。

延迟指标应先通过 Phase 0 测出本机基线。可以暂以“Python 增加的输入到输出调用延迟 p99 不高于约 2 ms”为候选目标，再根据电钢琴、WinMM、loopMIDI 和 NanoHost 的实测结果锁定正式门槛。

## 13. 最终建议

当前环境足以开始 Phase 0。正式开发前不需要继续扩展产品功能，先完成最小的真实 MIDI 透传程序并取得延迟、抖动、端口兼容性和设备断连数据。

本项目最重要的架构规则应固定为：

> MIDI Output Send 是生产路径；Event Queue 只是尽力而为的观察路径。任何观察数据都可以丢失，实时演奏不能因等待观察者而停顿。

采用“单一入口队列 + Dispatcher + 每订阅者独立有界队列”后，可以同时满足广播订阅、订阅者互不抢数据、慢订阅者隔离和实时链路优先四个目标。

## 14. 实施状态

截至 2026-08-20，已完成：

- Python 项目和命令行入口。
- 统一、不可变 `MidiEvent` 模型。
- MIDI 输入/输出端口枚举。
- `python-rtmidi` 输入 callback 到输出端口的优先透传。
- SysEx、MIDI Clock、Active Sensing 的显式接收开关。
- 单一有界 Ingress Queue。
- 后台 Dispatcher 广播。
- 每订阅者独立有界队列。
- `DROP_NEWEST`、`DROP_OLDEST`、`LATEST` 策略。
- `LATEST` 订阅的 overwrite/peek 行为。
- Router、Dispatcher 和 Subscription 指标。
- 正常退出时 Sustain Off、All Notes Off 和 All Sound Off。
- Session 状态机和原子元数据写入。
- 独立线程 JSONL Recorder。
- Session 序号缺口和订阅丢弃统计。
- `.part` 文件崩溃恢复和 `aborted` 标记。
- Session 结束后的 Standard MIDI 导出。
- `route --record` 自动 Session 录制模式。
- FastAPI 本地 HTTP 服务和 WebSocket 实时广播。
- “可视化”和“设置”双入口门户。
- Web 设置持久化、端口枚举及 MIDI 路由启停。
- MIDI 瀑布流、钢琴键盘、力度、Sustain、当前按键和基础和弦显示。
- 每个 WebSocket 客户端独立有界队列和慢客户端丢弃策略。
- 程序目录下 `data\config.json` 用户配置存储；EXE 模式对应 EXE 所在目录。
- 程序目录下 `data\sessions` 默认 Session 存储。
- PyInstaller 单文件 Windows EXE 及内置 Web 静态资源。
- WebSocket 运行库作为正式依赖并随 EXE 打包，Uvicorn 使用 `websockets-sansio` 实现。
- 门户、设置页和可视化页采用亮色极简主题，统一使用圆角卡片、轻边框、克制阴影和高辨识度状态色。
- 22 项事件解析、广播隔离、录制、状态分析、路径和 Web API/WebSocket 测试。

自动化测试结果：

```text
22 passed
```

当前 Windows MIDI 枚举结果：

```text
MIDI inputs:
  [0] test 0
MIDI outputs:
  [0] Microsoft GS Wavetable Synth 0
  [1] test 1
```

当前已经可以枚举名为 `test` 的虚拟 MIDI 端口，但电钢琴不在现场，因此真实 Phase 0 硬件链路验证仍未完成。下一次验证前需要：

1. 在 loopMIDI 中创建并保持一个端口，例如 `Piano Telemetry Out`。
2. 连接并开启电钢琴，确认其 Windows MIDI 驱动已经就绪。
3. 再运行 `python -m piano_telemetry ports` 检查两个端口。
4. 使用 `python -m piano_telemetry route --input "输入端口" --output "Piano Telemetry Out"` 开始真实透传。

### EXE 验证

已生成：

```text
dist\PianoTelemetry.exe
```

验证时从不包含源码和 Web 资源的临时目录启动 EXE，结果如下：

- FastAPI/Uvicorn 正常启动。
- 门户 `/` 返回 HTTP 200。
- 内置 `/static/app.css` 返回 HTTP 200。
- 设置和状态 API 正常响应。
- EXE 可独立枚举 Windows MIDI 端口。
- 配置写入 EXE 所在目录下的 `data\config.json`。
- WebSocket 握手成功，客户端可收到初始 `state` 消息。
- 启动时不再出现缺少 WebSocket library 的警告。
- 静态资源出现 `304 Not Modified` 时表示浏览器缓存命中，属于正常 HTTP 响应。
- 工作目录中不需要存在 HTML、CSS、JavaScript 或 Python 源文件。
