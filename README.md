# Piano Telemetry

Windows 电钢琴 MIDI 低延迟透传和尽力而为的遥测基础服务。

当前已实现 Phase 0/1、Phase 2 录制和 Phase 3 Web 基础：

- MIDI 输入、输出端口枚举。
- teVirtualMIDI 托管的固定输入/输出端口和优先透传。
- 有界入口队列。
- 广播 Dispatcher。
- 每订阅者独立、有界队列。
- 订阅者过载丢弃和指标统计。
- Session 状态机和 JSONL 录制。
- 异常退出后的 `.part` Session 恢复。
- Session 结束后的 Standard MIDI 导出。
- 本地 Web 门户、设置页和可视化页面。
- 实时 WebSocket、MIDI 瀑布流和钢琴键盘。
- 固定虚拟端口展示、驱动检测及 Web 启停 MIDI 路由。
- 单文件 Windows EXE 打包。

## 环境

项目使用 Conda 环境 `piano-midi`：

```powershell
& 'C:\software\miniconda3\miniconda3\Scripts\conda.exe' run -n piano-midi python -m pip install -e '.[dev]'
```

## Web 门户

不带参数运行时会启动本地门户并打开浏览器：

```powershell
python -m piano_telemetry
```

也可以显式运行：

```powershell
python -m piano_telemetry serve --port 8765
```

访问地址为 `http://127.0.0.1:8765/`。门户包含：

- `可视化`：实时瀑布流、钢琴键盘、和弦、力度和 Sustain。
- `设置`：固定虚拟端口、驱动状态以及 MIDI 路由启动/停止。

启动 MIDI 后，程序动态创建以下端口，停止或退出时自动删除：

- `Piano Telemetry Input`：测试脚本或其他 MIDI 软件向这里发送。
- `Piano Telemetry Output`：NanoHost 从这里接收。

程序直接调用系统安装的 `teVirtualMIDI.dll`，不会将 SDK 或 DLL 打入 EXE。未安装驱动时，设置页会显示安装提示并禁止启动 MIDI。可通过安装 [loopMIDI](https://www.tobias-erichsen.de/software/loopmidi.html) 获得驱动；不需要运行 `loopMIDI.exe`。

列出 MIDI 端口：

```powershell
& 'C:\software\miniconda3\miniconda3\Scripts\conda.exe' run -n piano-midi piano-telemetry ports
```

启动透传：

```powershell
& 'C:\software\miniconda3\miniconda3\Scripts\conda.exe' run -n piano-midi piano-telemetry route
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

## 构建 EXE

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_exe.ps1
```

输出文件：

```text
dist\PianoTelemetry.exe
```

EXE 内置全部 HTML、CSS、JavaScript、Python 运行时和 Conda 所需 DLL，可以复制到其他目录运行。第三方 `teVirtualMIDI.dll` 不包含在内，必须由用户自行安装。双击或不带参数启动时会打开 Web 门户。

首次保存设置或录制时，EXE 会在自身所在目录创建 `data`。因此应将 EXE 放在当前用户有写入权限的位置，不建议直接放入 `Program Files`。

Uvicorn 的 WebSocket 运行库已作为正式依赖并打入 EXE。浏览器日志中的静态资源 `304 Not Modified` 表示资源缓存仍然有效，是正常响应，不是加载失败。
