const elements = {
  input: document.querySelector('#input-port'),
  output: document.querySelector('#output-port'),
  sysex: document.querySelector('#receive-sysex'),
  clock: document.querySelector('#receive-clock'),
  active: document.querySelector('#receive-active'),
  panic: document.querySelector('#panic-on-stop'),
  portMessage: document.querySelector('#port-message'),
  actionMessage: document.querySelector('#action-message'),
  status: document.querySelector('#route-status'),
};

function showMessage(target, message, type = '') {
  target.textContent = message;
  target.className = target === elements.portMessage ? 'inline-message' : 'action-message';
  if (type) target.classList.add(`message-${type}`);
}

function fillSelect(select, values, selected, placeholder) {
  select.replaceChildren(new Option(placeholder, ''));
  for (const value of values) select.add(new Option(value, value));
  if (selected && !values.includes(selected)) {
    select.add(new Option(`${selected}（当前不可用）`, selected));
  }
  select.value = selected || '';
}

async function loadEverything() {
  showMessage(elements.portMessage, '正在扫描 MIDI 端口…');
  try {
    const [settingsResponse, portsResponse, statusResponse] = await Promise.all([
      fetch('/api/settings'), fetch('/api/midi/ports'), fetch('/api/status')
    ]);
    const settings = await settingsResponse.json();
    const ports = await portsResponse.json();
    const status = await statusResponse.json();
    if (!portsResponse.ok) throw new Error(ports.detail || '无法枚举 MIDI 端口');
    fillSelect(elements.input, ports.inputs, settings.input_port, '请选择电钢琴输入');
    fillSelect(elements.output, ports.outputs, settings.output_port, '请选择 loopMIDI 输出');
    elements.sysex.checked = settings.receive_sysex;
    elements.clock.checked = settings.receive_clock;
    elements.active.checked = settings.receive_active_sensing;
    elements.panic.checked = settings.panic_on_stop;
    showMessage(elements.portMessage,
      `发现 ${ports.inputs.length} 个输入端口，${ports.outputs.length} 个输出端口。`);
    updateStatus(status);
  } catch (error) {
    showMessage(elements.portMessage, error.message, 'error');
  }
}

function currentSettings() {
  return {
    input_port: elements.input.value || null,
    output_port: elements.output.value || null,
    receive_sysex: elements.sysex.checked,
    receive_clock: elements.clock.checked,
    receive_active_sensing: elements.active.checked,
    panic_on_stop: elements.panic.checked,
  };
}

async function saveSettings() {
  const response = await fetch('/api/settings', {
    method: 'PUT', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(currentSettings())
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail || '保存失败');
  return result;
}

function updateStatus(status) {
  elements.status.textContent = status.running ? '正在运行' : '未运行';
  elements.status.classList.toggle('online', status.running);
  elements.status.classList.toggle('offline', !status.running);
}

document.querySelector('#refresh-ports').addEventListener('click', loadEverything);
document.querySelector('#save-settings').addEventListener('click', async () => {
  try { await saveSettings(); showMessage(elements.actionMessage, '设置已保存', 'success'); }
  catch (error) { showMessage(elements.actionMessage, error.message, 'error'); }
});
document.querySelector('#start-midi').addEventListener('click', async () => {
  try {
    await saveSettings();
    const response = await fetch('/api/midi/start', {method: 'POST'});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || '启动失败');
    updateStatus(result); showMessage(elements.actionMessage, 'MIDI 路由已启动', 'success');
  } catch (error) { showMessage(elements.actionMessage, error.message, 'error'); }
});
document.querySelector('#stop-midi').addEventListener('click', async () => {
  try {
    const response = await fetch('/api/midi/stop', {method: 'POST'});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || '停止失败');
    updateStatus(result); showMessage(elements.actionMessage, 'MIDI 路由已停止', 'success');
  } catch (error) { showMessage(elements.actionMessage, error.message, 'error'); }
});

loadEverything();

