# Piano Telemetry

Windows 电钢琴 MIDI 低延迟透传和尽力而为的遥测基础服务。

当前已实现 Phase 0/1、Phase 2 录制和 Phase 3 Web 基础：

- MIDI 输入、输出端口枚举。
- 可选物理/虚拟 MIDI 输入、固定虚拟输出和优先透传。
- 有界入口队列。
- 广播 Dispatcher。
- 每订阅者独立、有界队列。
- 订阅者过载丢弃和指标统计。
- Session 状态机和 JSONL 录制。
- 异常退出后的 `.part` Session 恢复。
- Session 结束后的 Standard MIDI 导出。
- 默认可视化首页和设置页。
- 实时 WebSocket、MIDI 瀑布流、当前音符谱表和钢琴键盘。
- Web Session 录制控制及实时录制时长。
- 输入端口选择、固定虚拟输出、驱动检测及 Web 启停 MIDI 路由。
- 单文件 Windows EXE 打包。

## 环境

项目使用 Conda 环境 `piano-midi`：

```powershell
& 'C:\software\miniconda3\miniconda3\Scripts\conda.exe' run -n piano-midi python -m pip install -e '.[dev]'
```

## Web 界面

不带参数运行时会启动本地 Web 界面并直接打开可视化页面：

```powershell
python -m piano_telemetry
```

也可以显式运行：

```powershell
python -m piano_telemetry serve --port 8765
```

访问地址为 `http://127.0.0.1:8765/`：

- `可视化`：实时瀑布流、当前音符谱表、钢琴键盘、演奏指标和录制控制。
- `设置`：输入端口选择、固定虚拟输出、驱动状态以及 MIDI 路由启动/停止。

路由运行时点击“保存设置”，程序会关闭并重启 MIDI 路由，以应用输入端口和系统消息选项。

点击可视化页面右上角的“开始录制”即可创建 Session；录制期间按钮显示已录制时长。再次点击会弹出“保存名称”窗口：选择“保存”后完成 JSONL、摘要和 Standard MIDI 导出，并写入程序目录下的 `data\sessions\<保存名称>\`；选择“不保存”则删除本次录制。录制使用独立有界队列，写盘过载时会丢弃录制事件并将 Session 标记为不完整，不会阻塞实时 MIDI 路由。点击“停止 MIDI”或退出程序时，正在进行的录制也会自动完成并以 Session ID 保存，避免意外丢失。

程序启动后会读取已保存的输入端口并自动启动 MIDI。若该端口已断开或不存在，会将设置回退并写回为 `Piano Telemetry Input`，然后使用托管虚拟输入启动。

输入端口可以在设置页自由选择：连接电钢时选择电钢端口，运行测试脚本时选择 `Piano Telemetry Input`。输出固定为 `Piano Telemetry Output`。

选择 `Piano Telemetry Input` 并启动 MIDI 后，程序会动态创建以下输入端口，停止或退出时自动删除：

- `Piano Telemetry Input`：测试脚本或其他 MIDI 软件向这里发送。

无论选择哪个输入，程序都会动态创建 `Piano Telemetry Output`，NanoHost 应监听此端口。

点击“停止 MIDI”或退出程序时，程序会关闭 teVirtualMIDI 端口句柄；本次创建的 `Piano Telemetry Input`（如有）和 `Piano Telemetry Output` 会随即从系统中消失。

程序直接调用系统安装的 `teVirtualMIDI.dll`，不会将 SDK 或 DLL 打入 EXE。未安装驱动时，设置页会显示安装提示并禁止启动 MIDI。可通过安装 [loopMIDI](https://www.tobias-erichsen.de/software/loopmidi.html) 获得驱动；不需要运行 `loopMIDI.exe`。

列出 MIDI 端口：

```powershell
& 'C:\software\miniconda3\miniconda3\Scripts\conda.exe' run -n piano-midi piano-telemetry ports
```

启动透传：

```powershell
& 'C:\software\miniconda3\miniconda3\Scripts\conda.exe' run -n piano-midi piano-telemetry route
```

从指定电钢输入端口启动透传：

```powershell
& 'C:\software\miniconda3\miniconda3\Scripts\conda.exe' run -n piano-midi piano-telemetry route --input "电钢端口名称"
```

启动透传并录制一个 Session：

```powershell
& 'C:\software\miniconda3\miniconda3\Scripts\conda.exe' run -n piano-midi piano-telemetry route `
  --record `
  --piece "练习曲名称" `
  --target-bpm 80
```

按 `Ctrl+C` 后，Session 默认写入程序目录下的 `data\sessions\<session_id>\`，其中包含 `session.json`、`events.jsonl`、`summary.json` 和 `session.mid`。EXE 模式下，“程序目录”就是 `PianoTelemetry.exe` 所在目录；源码模式下则是启动命令时的当前目录。

默认过滤 SysEx、MIDI Clock 和 Active Sensing。可以分别使用 `--receive-sysex`、`--receive-clock`、`--receive-active-sensing` 开启接收与透传。它们仍不会改变“先输出、后发布观察事件”的顺序。

设置保存在程序目录下的 `data\config.json`。

## NanoHost 联调曲目

先在设置页启动 MIDI，再让 NanoHost 监听 `Piano Telemetry Output`，然后播放内置的原创 MIDI 测试曲：

```powershell
conda activate piano-midi
python tests\play_demo_midi.py
```

脚本默认向 `Piano Telemetry Input` 发送。可使用 `--list-ports` 查看端口，或通过 `--port "完整端口名"`、`--bpm 90` 调整目标端口和速度。播放过程中按 `Ctrl+C` 会发送延音关闭、All Notes Off 和 All Sound Off。

## MIDI 延迟基准

关闭正在运行的 Piano Telemetry，然后从项目根目录运行本机闭环基准：

```powershell
conda activate piano-midi
python tests\benchmark_midi_latency.py
```

脚本会自行创建托管虚拟端口，预热后逐条发送 MIDI 消息，并统计端到端的 min、median、mean、P95、P99 和 max。若 Web UI 或 CLI 已经启动 MIDI，可改用 `--existing-router` 连接现有端口。可通过 `--samples 5000`、`--warmup 500`、`--interval-ms 1` 调整样本数和发送节奏。

该结果包含测试客户端、两次 Windows 虚拟 MIDI 传递以及中间件转发，不包含电钢琴 USB、NanoHost/VST 处理和音频设备缓冲延迟。

## 构建 EXE

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_exe.ps1
```

输出文件：

```text
dist\PianoTelemetry.exe
```

EXE 内置全部 HTML、CSS、JavaScript、Python 运行时和 Conda 所需 DLL，可以复制到其他目录运行。第三方 `teVirtualMIDI.dll` 不包含在内，必须由用户自行安装。双击或不带参数启动时会直接打开可视化页面。

首次保存设置或录制时，EXE 会在自身所在目录创建 `data`。因此应将 EXE 放在当前用户有写入权限的位置，不建议直接放入 `Program Files`。

Uvicorn 的 WebSocket 运行库已作为正式依赖并打入 EXE。浏览器日志中的静态资源 `304 Not Modified` 表示资源缓存仍然有效，是正常响应，不是加载失败。
