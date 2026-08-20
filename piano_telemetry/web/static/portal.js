async function loadPortalStatus() {
  const dot = document.querySelector('#status-dot');
  const text = document.querySelector('#status-text');
  const summary = document.querySelector('#port-summary');
  try {
    const [statusResponse, settingsResponse] = await Promise.all([
      fetch('/api/status'), fetch('/api/settings')
    ]);
    const status = await statusResponse.json();
    const settings = await settingsResponse.json();
    dot.classList.add('online');
    text.textContent = status.running ? 'MIDI 路由正在运行' : '本地服务已就绪';
    summary.textContent = settings.input_port && settings.output_port
      ? `${settings.input_port} → ${settings.output_port}`
      : '尚未选择 MIDI 端口';
  } catch (error) {
    text.textContent = '无法连接本地服务';
  }
}
loadPortalStatus();

