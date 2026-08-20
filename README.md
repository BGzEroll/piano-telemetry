# Piano Telemetry

Windows 电钢琴 MIDI 低延迟透传和尽力而为的遥测基础服务。

当前已实现 Phase 0/1 和 Phase 2 录制基础：

- MIDI 输入、输出端口枚举。
- 输入到 loopMIDI 的优先透传。
- 有界入口队列。
- 广播 Dispatcher。
- 每订阅者独立、有界队列。
- 订阅者过载丢弃和指标统计。
- Session 状态机和 JSONL 录制。
- 异常退出后的 `.part` Session 恢复。
- Session 结束后的 Standard MIDI 导出。

## 环境

项目使用 Conda 环境 `piano-midi`：

```powershell
& 'C:\software\miniconda3\miniconda3\Scripts\conda.exe' run -n piano-midi python -m pip install -e '.[dev]'
```

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

按 `Ctrl+C` 后，Session 会写入 `data/sessions/<session_id>/`，其中包含 `session.json`、`events.jsonl`、`summary.json` 和 `session.mid`。

默认过滤 SysEx、MIDI Clock 和 Active Sensing。可以分别使用 `--receive-sysex`、`--receive-clock`、`--receive-active-sensing` 开启接收与透传。它们仍不会改变“先输出、后发布观察事件”的顺序。
