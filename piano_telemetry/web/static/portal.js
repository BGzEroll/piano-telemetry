async function loadPortalStatus() {
  const dot = document.querySelector('#status-dot');
  const text = document.querySelector('#status-text');
  const summary = document.querySelector('#port-summary');
  try {
    const statusResponse = await fetch('/api/status');
    const status = await statusResponse.json();
    dot.classList.add('online');
    text.textContent = status.running ? 'MIDI 路由正在运行' : '本地服务已就绪';
    summary.textContent = status.driver?.available
      ? `${status.input_port} → ${status.output_port}`
      : '尚未安装 teVirtualMIDI 驱动';
  } catch (error) {
    text.textContent = '无法连接本地服务';
  }
}
loadPortalStatus();
