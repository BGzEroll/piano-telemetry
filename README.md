# Piano Telemetry

Windows 电钢琴 MIDI 低延迟透传和尽力而为的遥测基础服务。

当前已实现 Phase 0/1、Phase 2 录制和 Phase 3 Web 基础：

- MIDI 输入、输出端口枚举。
- 输入到 loopMIDI 的优先透传。
- 有界入口队列。
- 广播 Dispatcher。
- 每订阅者独立、有界队列。
- 订阅者过载丢弃和指标统计。
- Session 状态机和 JSONL 录制。
- 异常退出后的 `.part` Session 恢复。
- Session 结束后的 Standard MIDI 导出。
- 本地 Web 门户、设置页和可视化页面。
- 实时 WebSocket、MIDI 瀑布流和钢琴键盘。
- 输入/输出端口设置及 Web 启停 MIDI 路由。
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
- `设置`：端口枚举、端口保存以及 MIDI 路由启动/停止。

列出 MIDI 端口：

```powershell
& 'C:\software\miniconda3\miniconda3\Scripts\conda.exe' run -n piano-midi piano-telemetry ports
```

启动透传：

```powershell
& 'C:\software\miniconda3\miniconda3\Scripts\conda.exe' run -n piano-midi piano-telemetry route --input "电钢琴端口名" --output "Piano Telemetry Out"
```

启动透传并录制一个 Session：

```powershell
& 'C:\software\miniconda3\miniconda3\Scripts\conda.exe' run -n piano-midi piano-telemetry route `
  --input "电钢琴端口名" `
  --output "Piano Telemetry Out" `
  --record `
  --piece "练习曲名称" `
  --target-bpm 80
```

按 `Ctrl+C` 后，Session 默认写入 `%LOCALAPPDATA%\PianoTelemetry\sessions\<session_id>\`，其中包含 `session.json`、`events.jsonl`、`summary.json` 和 `session.mid`。

默认过滤 SysEx、MIDI Clock 和 Active Sensing。可以分别使用 `--receive-sysex`、`--receive-clock`、`--receive-active-sensing` 开启接收与透传。它们仍不会改变“先输出、后发布观察事件”的顺序。

设置保存在 `%APPDATA%\PianoTelemetry\config.json`，不依赖程序当前目录。

## 构建 EXE

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_exe.ps1
```

输出文件：

```text
dist\PianoTelemetry.exe
```

EXE 内置全部 HTML、CSS、JavaScript、Python 运行时和 Conda 所需 DLL，可以复制到其他目录运行。双击或不带参数启动时会打开 Web 门户。
