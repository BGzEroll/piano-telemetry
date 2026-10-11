# Piano Telemetry

Piano Telemetry 是一个面向 Windows 电钢琴的低延迟 MIDI 中间件。它将电钢输入优先透传到虚拟输出，同时提供实时可视化、录制、MIDI 到电脑键盘映射，以及可选的 OpenClaw 录制推送能力。

核心原则是：**绝不让可视化、录制、键盘映射或网络上传阻塞 MIDI 实时链路**。观察链路过载时允许丢弃数据，但 MIDI 透传优先执行。

## 主要功能

- 自由选择物理电钢或托管虚拟端口作为 MIDI 输入。
- 动态创建 `Piano Telemetry Input` 和 `Piano Telemetry Output`，停止 MIDI 或退出时自动销毁。
- 实时瀑布流、88 键钢琴键盘、当前谱表、调式、和弦、力度及延音显示。
- 录制 Session，并导出 JSON 元数据、JSONL 事件流和 Standard MIDI 文件。
- 电钢琴键映射到电脑主键盘数字键、字母键，支持随时启停。
- 中文名称映射预设，支持保存、加载、覆盖、删除和清空当前映射。
- 手动将录制四件套打包为 ZIP 并推送至 OpenClaw 接收服务。
- 历史录制补推、推送状态持久化，以及 401、409、网络不可达等错误提示。
- 单文件 Windows EXE、系统托盘、管理员权限启动及自动打开 WebUI。

## 系统要求

- Windows 10 或 Windows 11。
- 源码运行需要 Python 3.12，推荐使用 Miniconda。
- 需要安装 [loopMIDI / teVirtualMIDI 驱动](https://www.tobias-erichsen.de/software/loopmidi.html)。

程序只调用系统中已安装的 `teVirtualMIDI.dll`，不会分发或捆绑第三方 SDK、DLL。安装 loopMIDI 后无需保持 `loopMIDI.exe` 运行。

## 从源码运行

创建并启用 Conda 环境：

```powershell
conda create -n piano-midi python=3.12
conda activate piano-midi
python -m pip install -e ".[dev]"
```

启动本地 WebUI：

```powershell
python -m piano_telemetry
```

默认访问地址：

```text
http://127.0.0.1:8765/
```

也可以指定监听地址和端口：

```powershell
python -m piano_telemetry serve --host 127.0.0.1 --port 8765
```

## 使用 EXE

将 `Piano Telemetry.exe` 放在当前用户有写入权限的目录后双击运行。程序会请求管理员权限、启动本地服务、打开 WebUI，并最小化到系统托盘。

托盘菜单只有“退出”。桌面小窗口的关闭和最小化按钮都会隐藏到托盘，不会结束 MIDI 服务。

运行过程中产生的设置、预设和录制均保存在 EXE 同级的 `data` 目录，因此 EXE 不依赖启动时的当前工作目录。不建议放入 `Program Files` 等普通用户不可写目录。

## WebUI 页面

### 可视化

- 显示实时瀑布音条、钢琴键盘和当前五线谱。
- 可选择十二平均律中的大小调，谱表和和弦名称同步变化。
- 显示当前和弦、力度、延音、事件序号和实时连接状态。
- 可开始和结束录制，并为录制指定中文保存名称。

### 按键映射

- 将 MIDI 21–108 的钢琴键绑定到主键盘 `0–9`、`A–Z`。
- 支持点击钢琴键选键，也可以直接按下电钢琴键进行学习。
- 支持多个钢琴键映射到同一个电脑键，并使用引用计数避免提前松键。
- 映射功能每次启动软件时默认关闭。
- 预设是当前绑定的快照，不保存启用状态；加载预设会保留当前开关状态并安全释放旧按键。
- “清空当前映射”只清除当前绑定，不会删除已保存预设。

打包版以管理员权限运行，因此可以向同样以管理员身份运行的前台程序发送键盘事件。

### 录制记录

- 查看已经保存且四件套完整的 Session。
- OpenClaw 推送启用后，可以手动补推历史录制。
- 已推送状态按照“服务器地址 + Session ID”记录，更换服务器后仍可推送到新服务器。

### 设置

- 选择 MIDI 输入端口并查看固定的虚拟输出端口。
- 控制 SysEx、MIDI Clock、Active Sensing 和退出清音。
- 配置 OpenClaw 服务器地址、共享密钥和手动推送开关。
- 修改输入端口或系统消息配置时会重启路由；只修改踏板或推送配置不会重启 MIDI。

设置页的「固定半踏板模拟」默认关闭。开启后，所有通道的 CC64 踩下值（≥64）映射为「踏板深度」（64–127，默认 80），松开值（<64）映射为 0；其他 MIDI 消息不变。点击「保存设置」后立即应用并写入 `data/config.json`，重启后恢复。

踩住踏板时保存新深度会同步发送新的 CC64；关闭模拟会恢复该通道最后收到的原始踩下值。松开或尚未收到踏板消息的通道不会因修改设置产生延音。录制的 JSONL/MIDI、可视化和键盘映射统一使用实际输出消息，包含设置修改时补发的 CC64；这些观察功能仍为尽力处理，过载时可能丢弃事件。录制中开启模拟会记录处理后的踏板值，回放该 MIDI 时通常无需再次映射。

部分软音源仅将 CC64 识别为二值开关，因此 80 不一定比 127 产生更浅的延音。这取决于音源的连续踏板支持；此功能不模拟真实机械踏板或渐进释放。

## MIDI 路由

连接电钢时，在设置页面选择实际电钢输入端口。脚本或其他 MIDI 软件需要向程序发送数据时，可以选择 `Piano Telemetry Input`。

输出端口固定为：

```text
Piano Telemetry Output
```

NanoHost、DAW 或软音源应监听该输出端口。无论输入来自物理电钢还是虚拟输入，实时路径均为：

```text
MIDI 输入 → Piano Telemetry → Piano Telemetry Output → 音源
```

默认过滤 SysEx、MIDI Clock 和 Active Sensing，可在设置页面或 CLI 中按需开启。

## 录制格式

每次保存的录制位于：

```text
data/sessions/<保存名称>/
├── session.json
├── summary.json
├── events.jsonl
└── session.mid
```

录制使用独立有界队列。磁盘过慢或队列过载时，程序会丢弃部分录制事件并把 Session 标记为可能不完整，而不会反向阻塞 MIDI 透传。

## OpenClaw 手动推送

OpenClaw 推送默认关闭。启用前需要在设置页面填写远端 HTTP 服务地址和共享密钥。

保存录制后，页面会询问是否立即推送；也可以在“录制记录”页面补推。程序会临时创建一个包含四件套的 ZIP，上传完成或失败后立即删除临时 ZIP，本地 Session 始终保留。

ZIP 内部使用固定 ASCII 文件名且不包含嵌套目录。外层 ZIP 文件名支持中文，并会自动替换 Windows 不允许的字符。

共享密钥保存在本地 `data/config.json`，Web API 不会将密钥回显到页面。当前上传协议面向可信局域网使用 HTTP，不提供 HTTPS、自动重试或自动上传。

## 数据目录

```text
data/
├── config.json                  # MIDI、调式和 OpenClaw 设置
├── key_mapping.json             # 当前键盘映射
├── key_mapping_presets.json     # 映射预设
├── push_history.json            # 已推送 Session 记录
└── sessions/                    # 录制 Session
```

## CLI

列出 MIDI 端口：

```powershell
piano-telemetry ports
```

启动托管虚拟 MIDI 路由：

```powershell
piano-telemetry route
```

指定物理输入：

```powershell
piano-telemetry route --input "电钢端口名称"
```

启动路由并录制：

```powershell
piano-telemetry route `
  --record `
  --piece "练习曲名称" `
  --target-bpm 80
```

按 `Ctrl+C` 后，Session 会写入 `data/sessions/<session_id>/`。

系统消息选项：

```text
--receive-sysex
--receive-clock
--receive-active-sensing
--no-panic-on-stop
```

## 测试 MIDI 播放

先启动 MIDI 路由，并让音源监听 `Piano Telemetry Output`：

```powershell
conda activate piano-midi
python tests/play_demo_midi.py
```

脚本默认向 `Piano Telemetry Input` 发送。使用 `--list-ports` 查看端口，使用 `--port "完整端口名"` 指定端口，使用 `--bpm 90` 调整速度。

## 延迟基准

关闭正在运行的 Piano Telemetry 后执行：

```powershell
conda activate piano-midi
python tests/benchmark_midi_latency.py
```

若要测试已经运行的路由：

```powershell
python tests/benchmark_midi_latency.py --existing-router
```

基准结果包含测试客户端、两次 Windows 虚拟 MIDI 传递和中间件转发，不包含电钢 USB、音源处理和音频设备缓冲延迟。

## 构建 EXE

```powershell
conda activate piano-midi
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_exe.ps1
```

输出文件：

```text
dist/Piano Telemetry.exe
```

EXE 内置 Web 资源、Python 运行时及所需依赖，但不包含 `teVirtualMIDI.dll`。

## 项目结构

```text
piano_telemetry/
├── analyzer/        # 调式、和弦及演奏状态分析
├── core/            # 配置、事件分发、控制器和键盘映射
├── midi/            # MIDI 端口、路由及虚拟端口
├── push/            # OpenClaw ZIP 打包与上传
├── recorder/        # Session 录制和 MIDI 导出
├── web/             # WebUI 页面和静态资源
├── web_hub.py       # WebSocket 广播
└── web_server.py    # FastAPI 接口
```

更详细的架构和实时链路审计参见 `docs` 目录。
