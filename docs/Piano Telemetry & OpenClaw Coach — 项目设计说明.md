# Piano Telemetry & OpenClaw Coach

## 1. 项目目标

构建一套运行于 Windows 的电钢琴 MIDI 中间层系统，在**不影响正常实时演奏与 NanoHost 软音源使用**的前提下，对 MIDI 数据进行复制、记录、分析和网络分发，并提供 Web 实时可视化以及面向 OpenClaw 的练习分析接口。

系统主要用途：

1. 电钢琴 MIDI 无感透传至 NanoHost / VSTi。
2. 实时采集完整 MIDI 数据。
3. 浏览器显示钢琴瀑布流、当前按键、五线谱和和弦。
4. 保存每次练习 Session。
5. 为 OpenClaw 提供结构化数据接口。
6. 支持教材/曲目参考谱，对演奏节奏、力度、稳定性等进行分析。
7. 由 OpenClaw 负责长期练习管理、进度分析和和声学教学。

---

# 2. 核心设计原则

## 2.1 实时演奏优先级最高

必须保证：

> Web、TCP、磁盘写入、分析模块、OpenClaw 或其他功能发生卡顿、异常或断线时，不得影响 MIDI → NanoHost 的实时演奏链路。

核心实时路径：

```text
Digital Piano
      │
      ▼
 MIDI Input
      │
      ├──────────────→ Virtual MIDI Output → NanoHost → VSTi → Audio
      │
      └──→ Background Event Queue
```

MIDI 输入回调中原则上只执行：

1. 获取 MIDI event。
2. 记录高精度时间戳。
3. 立即发送至 Virtual MIDI Output。
4. 将事件副本放入后台队列。

MIDI callback 中禁止进行：

- 网络 I/O
- JSON 序列化
- 文件写入
- 数据库操作
- WebSocket 操作
- AI 调用
- 复杂音乐分析
- 阻塞式日志输出

---

# 3. 总体架构

```text
                            ┌─────────────┐
                            │   NanoHost  │
                            │    / VSTi   │
                            └──────▲──────┘
                                   │
                          Virtual MIDI OUT
                                   ▲
                                   │
┌──────────────┐          ┌────────┴────────┐
│Digital Piano │ ─MIDI─→  │    MIDI Core    │
└──────────────┘          │                  │
                           │ Input / Clock    │
                           │ Realtime Router  │
                           └────────┬─────────┘
                                    │
                              Event Queue
                                    │
                           ┌────────▼─────────┐
                           │    Event Bus     │
                           └────────┬─────────┘
                ┌───────────────────┼───────────────────┐
                │                   │                   │
                ▼                   ▼                   ▼
           Recorder             Analyzer            Network
         MIDI + JSONL        Music Analysis      TCP / HTTP / WS
                │                   │                   │
                └───────────┬───────┘             ┌─────┴─────┐
                            ▼                     ▼           ▼
                         Session                Web UI    OpenClaw
```

建议所有非实时模块消费统一事件结构，不直接互相耦合。

---

# 4. MIDI Event 数据模型

建议内部统一：

```text
MidiEvent
{
    seq
    timestamp_ns
    session_time_ns
    port
    type
    channel
    data1
    data2
}
```

例如：

```json
{
  "seq": 18322,
  "timestamp_ns": 83918273192831,
  "session_time_ns": 1283912231,
  "type": "note_on",
  "channel": 0,
  "data1": 64,
  "data2": 81
}
```

其中：

- `seq`：严格递增事件编号。
- `timestamp_ns`：建议使用 `time.perf_counter_ns()`。
- `session_time_ns`：当前练习 Session 开始后的相对时间。
- `data1/data2`：保存原始 MIDI 数据。

不要只保存 Note On / Note Off，应尽可能完整保留：

- Note On
- Note Off
- CC
- Sustain Pedal / CC64
- Pitch Bend
- Aftertouch
- Program Change
- 其他原始 MIDI message

特别需要保留踏板连续值，以兼容半踏板设备。

---

# 5. Session 系统

系统不能只有无限 MIDI stream，需要有明确的练习 Session。

```text
Session
├── id
├── start_time
├── end_time
├── duration
├── piece
├── reference_score
├── target_bpm
├── raw_midi
├── telemetry
├── summary
└── analysis
```

例如：

```json
{
  "session_id": "20260820_203518",
  "piece": {
    "collection": "Czerny Op.599",
    "number": 27
  },
  "target_bpm": 80
}
```

OpenClaw 后续应主要围绕 Session 工作，例如：

```text
比较今天和三天前的 Op.599 No.27。
```

而不是直接处理无限实时 MIDI 流。

---

# 6. 数据存储

每个 Session 建议至少保存两种格式。

## 6.1 Standard MIDI

```text
session.mid
```

用于：

- DAW
- 乐谱软件
- 回放
- MIDI 编辑

## 6.2 原始 Telemetry

建议：

```text
events.jsonl
```

例如：

```json
{"t_ns":0,"type":"note_on","note":60,"velocity":71}
{"t_ns":13218942,"type":"note_on","note":64,"velocity":82}
{"t_ns":21381892,"type":"note_on","note":67,"velocity":76}
{"t_ns":912381231,"type":"cc","cc":64,"value":127}
```

JSONL 主要服务于：

- Python 分析
- Pandas
- OpenClaw
- 后续 AI
- Debug
- 数据集构建

---

# 7. 本地 Analyzer

本地 Analyzer 应完成能够确定性计算的工作，而不是把所有原始数据交给 LLM。

建议模块化：

```text
Analyzer
├── ActiveNotes
├── SoundingNotes
├── ChordAnalyzer
├── TempoAnalyzer
├── TimingAnalyzer
├── DynamicsAnalyzer
├── PedalAnalyzer
├── ScoreFollower
└── PerformanceAnalyzer
```

---

# 8. 当前按键与五线谱

五线谱只用于：

> 显示当前正在按下的音。

不需要实现实时自动转录。

维护两个状态：

```text
physical_notes
sounding_notes
```

例如：

```text
按下 C4
踩 Sustain
松开 C4
```

此时：

```text
physical_notes = []
sounding_notes = [C4]
```

Web UI 可以视觉区分：

- 当前物理按住的音
- 已松开但被踏板保持的音

第一版本可以统一使用：

```text
C C# D D# E F F# G G# A A# B
```

以后根据调性再处理 `C# / Db` 等 enharmonic spelling。

---

# 9. 和弦识别

从当前 active/sounding notes 中获得 pitch class：

```text
note % 12
```

例如：

```text
60 64 67
→ {0,4,7}
→ C major
```

支持：

- Major
- Minor
- Dim
- Aug
- 7
- Maj7
- m7
- sus2
- sus4
- inversion

例如：

```text
E G C
→ C/E
```

和弦识别主要由确定性算法完成，不依赖 LLM。

---

# 10. Web 前端

服务端提供：

```text
HTTP
WebSocket
```

浏览器无需直接访问 MIDI 设备。

建议页面包含：

```text
┌──────────────────────────────────────────┐
│ Piece / Session / BPM / Sustain          │
├──────────────────────────────────────────┤
│                五线谱                    │
│                                          │
│ Current Chord: Cmaj7/E                   │
├──────────────────────────────────────────┤
│               MIDI 瀑布流                │
│                                          │
├──────────────────────────────────────────┤
│               Piano Keyboard             │
├──────────────────────────────────────────┤
│ Timing / Velocity / Tempo / Pedal        │
└──────────────────────────────────────────┘
```

瀑布流优先使用：

```text
HTML Canvas
```

而不是为每个 note 创建 DOM element。

---

# 11. TCP Server

TCP Server 主要服务：

> OpenClaw 及其他程序化客户端。

Web UI 使用 WebSocket。

TCP 协议建议使用：

```text
JSON Lines / NDJSON
```

即：

```text
一条 JSON = 一行
```

便于调试、扩展和 OpenClaw 接入。

协议至少提供三类数据。

## Event

实时原始事件：

```json
{
  "kind": "event",
  "seq": 11931,
  "t_ns": 29188291022,
  "event": "note_on",
  "note": 60,
  "velocity": 72
}
```

## State

实时音乐状态：

```json
{
  "kind": "state",
  "active_notes": [60,64,67],
  "sounding_notes": [60,64,67],
  "sustain": 93,
  "chord": "C"
}
```

## Summary

供 OpenClaw 使用：

```json
{
  "kind": "summary",
  "session_id": "20260820_203518",
  "duration_sec": 1238.4,
  "note_count": 8123,
  "avg_velocity": 70.8,
  "velocity_std": 11.4,
  "tempo": 88.2
}
```

---

# 12. OpenClaw API 思路

OpenClaw 不应该长期消费每一个 NoteOn，而应主要使用：

```text
Query / Control API
```

例如：

```json
{"cmd":"get_current_session"}
```

```json
{"cmd":"get_session_summary","session_id":"..."}
```

```json
{"cmd":"list_sessions","piece":"Czerny Op.599 No.27"}
```

```json
{"cmd":"get_measure_analysis","session_id":"...","measure":12}
```

```json
{"cmd":"start_session","piece":"Czerny Op.599 No.27"}
```

```json
{"cmd":"stop_session"}
```

必要时才允许 OpenClaw 拉取：

```text
raw events
```

或某一个时间段/小节的详细事件。

---

# 13. 教材模式 / Score Following

目标场景：

> “OpenClaw，我现在练车尔尼 599 第 27 条。”

系统加载对应参考谱：

```text
Czerny Op.599 No.27
```

然后将实际 MIDI 与参考谱进行对齐。

推荐参考格式：

```text
MusicXML
```

优先级：

```text
MusicXML > MIDI > PDF/Image
```

MusicXML 负责机器分析。

PDF 可以仅用于人类查看。

目录例如：

```text
scores/
└── czerny_op599/
    ├── 001.musicxml
    ├── 002.musicxml
    ├── ...
    └── 100.musicxml
```

---

# 14. Score Follower

Score Follower 负责回答：

> 用户当前弹到了哪一小节、哪一拍、哪个音。

例如：

```text
Expected:
m.12 beat 2
C4 E4 G4

Actual:
C4 +8 ms
E4 +47 ms
G4 +91 ms
```

输出结构化结果，例如：

```json
{
  "measure": 12,
  "beat": 2,
  "expected_notes": [60,64,67],
  "timing_errors_ms": [8,47,91]
}
```

第一阶段不要求极其复杂的自动跟谱，可以先假定：

- 从曲首开始
- 演奏顺序基本正确
- 不处理大量跳奏/重复/从中间开始

后续再逐步增强容错。

---

# 15. 演奏分析

## 节奏

可计算：

- Tempo
- BPM drift
- IOI consistency
- Beat deviation
- Timing error
- Note duration
- 左右手同步
- 和弦同时性
- 连续音型均匀性

例如：

```text
m.12
Beat 1: +11 ms
Beat 2: +17 ms
Beat 3: +51 ms
Beat 4: +73 ms
```

可判断：

```text
后半小节存在逐步拖拍趋势。
```

注意：

> 不应简单把“距离机械节拍越近”定义为演奏越好。

算法层负责描述事实，OpenClaw 再结合音乐语境解释。

---

# 16. 力度分析

根据 MIDI velocity 分析：

- 平均力度
- 标准差
- 最大/最小值
- 同音型力度一致性
- 左右手力度平衡
- 非预期重音
- crescendo / diminuendo 趋势

例如：

```text
expected pattern:
pp

velocity:
52 49 51 67 50 48 53 70
         ↑           ↑
```

本地 Analyzer 可以输出：

```text
第4、8音出现明显突出。
```

OpenClaw 再解释：

```text
可能存在换指或拇指导致的机械性重音。
```

这里必须避免把 MIDI velocity 直接等同于真实声学响度，它主要用于相对比较和长期趋势分析。

---

# 17. OpenClaw Piano Coach

OpenClaw 主要负责高级解释和长期记忆。

不要让 LLM 做：

```text
NoteOn → 实时数值计算
```

而是：

```text
Raw MIDI
    ↓
Local Analyzer
    ↓
Structured Metrics
    ↓
OpenClaw
    ↓
Natural-language Coaching
```

例如：

```text
8/12
BPM 74
Timing std 31 ms

8/16
BPM 80
Timing std 26 ms

8/20
BPM 86
Timing std 19 ms
```

OpenClaw 可以总结：

```text
速度持续提升，同时节奏离散度明显下降。
建议暂时保持约 85 BPM，不继续提速，
下一阶段重点处理力度均匀性。
```

---

# 18. 长期练习管理

建议为每个曲目维护：

```text
PieceProgress
├── piece
├── status
├── current_bpm
├── target_bpm
├── recent_sessions
├── known_problems
├── mastered_sections
├── focus_sections
└── next_goal
```

例如：

```text
Czerny Op.599 No.21

状态：
基本完成

当前：
84 BPM

问题：
左手力度略大
16分音符偶尔抢拍

下一目标：
保持84 BPM，提高力度均匀性
```

OpenClaw 可以据此回答：

```text
今天练什么？
```

或者：

```text
最近 Op.599 的进步怎么样？
```

---

# 19. 和声学学习

系统应尽量把：

```text
正在弹的实际音乐
```

与：

```text
和声理论
```

连接起来。

例如：

```text
Key: C major

m.7:
G B D F
→ G7
→ V7

m.8:
C E G
→ C
→ I
```

OpenClaw 可以解释：

```text
V7 → I
```

并进一步教学：

- 和弦构成
- 级数
- 和声功能
- 转位
- 属功能
- 导音解决
- 七音解决
- 正格终止
- 半终止
- 经过和弦
- 离调
- 转调
- 声部进行

最好支持互动式教学，而不仅是直接给答案。

例如：

```text
“你刚才弹的第7小节是 G-B-D-F。
在 C 大调中，你觉得它是什么级数？”
```

用户回答以后再继续解释。

---

# 20. 功能边界

仅依赖 MIDI 可以较可靠分析：

- 音高
- 错音/漏音
- 节奏
- 音符时值
- velocity
- tempo
- 左右手 timing
- 和弦同步
- 踏板
- 重复稳定性
- 和声结构

不能仅靠 MIDI 可靠判断：

- 手型
- 指法是否正确
- 手腕状态
- 手臂是否僵硬
- 坐姿
- 触键动作

后续如需分析这些内容，可增加：

```text
Camera + MIDI
```

形成多模态分析，但不属于当前版本范围。

---

# 21. 推荐项目结构

```text
piano_telemetry/
├── app.py
│
├── midi/
│   ├── input.py
│   ├── output.py
│   ├── router.py
│   ├── clock.py
│   └── event.py
│
├── core/
│   ├── event_bus.py
│   ├── session.py
│   └── config.py
│
├── recorder/
│   ├── midi_recorder.py
│   └── jsonl_recorder.py
│
├── analyzer/
│   ├── active_notes.py
│   ├── chord.py
│   ├── tempo.py
│   ├── timing.py
│   ├── dynamics.py
│   ├── pedal.py
│   ├── score_follower.py
│   └── performance.py
│
├── score/
│   ├── musicxml.py
│   └── library.py
│
├── network/
│   ├── tcp_server.py
│   ├── websocket.py
│   └── http.py
│
├── web/
│   ├── index.html
│   ├── app.js
│   ├── waterfall.js
│   ├── piano.js
│   └── score.js
│
├── data/
│   ├── sessions/
│   └── scores/
│
└── tests/
```

---

# 22. 开发阶段建议

## Phase 1 — MIDI Core

先完成：

- MIDI Input
- Virtual MIDI Output
- NanoHost 正常工作
- 高精度 timestamp
- Event Queue
- 基础异常处理

验收标准：

> Python 程序开启后，正常弹琴体验与原来直接连接 NanoHost 基本无差异。

---

## Phase 2 — Telemetry

加入：

- JSONL recorder
- MIDI recorder
- Session
- TCP Server
- 基础状态查询

---

## Phase 3 — Web UI

加入：

- HTTP
- WebSocket
- Piano keyboard
- Waterfall
- 当前按键五线谱
- Sustain
- 当前和弦

---

## Phase 4 — Local Analysis

加入：

- Tempo
- Timing
- Dynamics
- Pedal
- Chord
- Session summary

---

## Phase 5 — Score Mode

加入：

- MusicXML parser
- 教材库
- Score follower
- 小节定位
- expected vs actual
- timing/dynamics comparison

首先以：

```text
Czerny Op.599
```

作为测试教材。

---

## Phase 6 — OpenClaw Integration

向 OpenClaw 暴露：

- 当前 Session
- 历史 Session
- Summary
- Measure Analysis
- Piece Progress
- 查询 API
- Session control

OpenClaw 负责：

- 练习点评
- 历史趋势
- 问题归纳
- 下一次练习建议
- 曲目进度管理
- 和声学解释
- 互动式乐理教学

---

# 23. 技术选型建议

Python 后端可考虑：

```text
Python 3.12+
mido
python-rtmidi
FastAPI
uvicorn
websockets
asyncio
```

其中 MIDI realtime thread 与 asyncio 网络线程必须合理隔离。

Virtual MIDI 在 Windows 下需要评估可用方案，例如：

```text
loopMIDI
```

或其他可创建 Virtual MIDI Port 的方案。

前端：

```text
HTML
CSS
JavaScript / TypeScript
Canvas
WebSocket
```

第一版尽量避免引入大型前端框架。

乐谱显示可以选成熟的 MusicXML / notation library，但“当前按键五线谱”功能本身应保持简单。

---

# 24. 第一版 MVP

Codex 首先只实现：

```text
Digital Piano
      ↓
Python MIDI Core
      ├──→ Virtual MIDI → NanoHost
      └──→ Event Queue
                │
                ├──→ JSONL Recorder
                ├──→ TCP Server
                └──→ WebSocket
                          ↓
                       Web UI
```

Web UI 第一版：

- 当前按键
- Piano keyboard
- MIDI waterfall
- 当前 velocity
- Sustain
- 当前 chord
- 当前按键五线谱

第一阶段暂时不要实现：

- AI
- OpenClaw
- MusicXML
- Score following
- 复杂乐谱转录
- 摄像头
- 数据库

但架构必须预留这些模块。

---

# 25. 最终系统定位

整个项目分为三层：

```text
Level 1 — Piano Telemetry
────────────────────────
准确、低延迟地采集“弹了什么”

              ↓

Level 2 — Music Intelligence
────────────────────────────
分析“弹得怎么样”
识别当前谱面位置
计算节奏、力度、和弦等结构化信息

              ↓

Level 3 — OpenClaw Piano Coach
──────────────────────────────
管理长期练习历史
发现持续存在的问题
安排练习目标
比较练习进步
结合实际曲目教授和声学
```

其中最重要的工程原则始终是：

> **MIDI Core 属于实时演奏系统；Web、Recorder、Analyzer 和 OpenClaw 都只是观察者。任何观察者故障都不能影响演奏链路。**