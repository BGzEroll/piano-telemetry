const elements = {
  input: document.querySelector('#input-port'),
  inputTrigger: document.querySelector('#input-port-trigger'),
  inputValue: document.querySelector('#input-port-value'),
  inputOptions: document.querySelector('#input-port-options'),
  output: document.querySelector('#output-port'),
  sysex: document.querySelector('#receive-sysex'),
  clock: document.querySelector('#receive-clock'),
  active: document.querySelector('#receive-active'),
  panic: document.querySelector('#panic-on-stop'),
  halfPedal: document.querySelector('#fixed-half-pedal-enabled'),
  pedalDepth: document.querySelector('#pedal-depth'),
  pedalDepthValue: document.querySelector('#pedal-depth-value'),
  portMessage: document.querySelector('#port-message'),
  actionMessage: document.querySelector('#action-message'),
  start: document.querySelector('#start-midi'),
  stop: document.querySelector('#stop-midi'),
  installLink: document.querySelector('#driver-install-link'),
  pushEnabled: document.querySelector('#push-enabled'),
  pushServerUrl: document.querySelector('#push-server-url'),
  pushToken: document.querySelector('#push-token'),
  pushTokenHint: document.querySelector('#push-token-hint'),
};
let driverAvailable = false;
let selectedInput = 'Piano Telemetry Input';
let selectedTonality = 'C_major';
let pushTokenConfigured = false;

function closeInputMenu({restoreFocus = false} = {}) {
  elements.inputOptions.hidden = true;
  elements.inputTrigger.setAttribute('aria-expanded', 'false');
  if (restoreFocus) elements.inputTrigger.focus();
}

function openInputMenu() {
  elements.inputOptions.hidden = false;
  elements.inputTrigger.setAttribute('aria-expanded', 'true');
  const selected = elements.inputOptions.querySelector('[aria-selected="true"]');
  (selected || elements.inputOptions.firstElementChild)?.focus();
}

function selectInput(name) {
  selectedInput = name;
  elements.inputValue.textContent = name;
  for (const option of elements.inputOptions.children) {
    option.setAttribute('aria-selected', String(option.dataset.value === name));
  }
}

function populateInputs(inputs, selectedInput) {
  const available = Array.isArray(inputs) ? [...inputs] : [];
  const discovered = new Set(available);
  if (!available.includes(selectedInput)) available.push(selectedInput);
  elements.inputOptions.replaceChildren();
  for (const name of available) {
    const option = document.createElement('button');
    option.type = 'button';
    option.className = 'select-option';
    option.setAttribute('role', 'option');
    option.dataset.value = name;
    option.textContent = discovered.has(name) ? name : `${name}（当前未连接）`;
    if (!discovered.has(name)) option.classList.add('unavailable');
    option.addEventListener('click', () => {
      selectInput(name);
      closeInputMenu({restoreFocus: true});
    });
    elements.inputOptions.append(option);
  }
  selectInput(selectedInput);
  closeInputMenu();
}

function showMessage(target, message, type = '') {
  target.textContent = message;
  target.className = target === elements.portMessage ? 'inline-message' : 'action-message';
  if (type) target.classList.add(`message-${type}`);
}

async function loadEverything() {
  showMessage(elements.portMessage, '正在检测 MIDI 驱动…');
  try {
    const [settingsResponse, portsResponse, statusResponse] = await Promise.all([
      fetch('/api/settings'), fetch('/api/midi/ports'), fetch('/api/status')
    ]);
    const settings = await settingsResponse.json();
    const ports = await portsResponse.json();
    const status = await statusResponse.json();
    if (!portsResponse.ok) throw new Error(ports.detail || '无法检测 teVirtualMIDI 驱动');
    populateInputs(ports.inputs, settings.input_port || ports.input_port);
    elements.output.textContent = ports.output_port;
    driverAvailable = Boolean(ports.available);
    elements.installLink.href = ports.install_url;
    elements.installLink.hidden = driverAvailable;
    elements.sysex.checked = settings.receive_sysex;
    elements.clock.checked = settings.receive_clock;
    elements.active.checked = settings.receive_active_sensing;
    elements.panic.checked = settings.panic_on_stop;
    elements.halfPedal.checked = Boolean(settings.fixed_half_pedal_enabled);
    elements.pedalDepth.value = settings.pedal_depth ?? 80;
    elements.pedalDepthValue.textContent = elements.pedalDepth.value;
    elements.pushEnabled.checked = Boolean(settings.push_enabled);
    elements.pushServerUrl.value = settings.push_server_url || 'http://192.168.114.103:8767';
    elements.pushToken.value = '';
    pushTokenConfigured = Boolean(settings.push_token_configured);
    elements.pushToken.placeholder = pushTokenConfigured ? '已配置，留空则不修改' : '请输入共享密钥';
    elements.pushTokenHint.textContent = pushTokenConfigured
      ? '密钥已配置；为安全起见不会在页面中回显。'
      : '尚未配置真实密钥。';
    selectedTonality = settings.tonality || 'C_major';
    const driverMessage = driverAvailable
      ? '驱动已就绪，端口将在启动 MIDI 时创建。'
      : '驱动未就绪，无法创建虚拟 MIDI 端口。';
    const scanMessage = ports.port_scan_error
      ? `输入端口枚举失败：${ports.port_scan_error}`
      : `发现 ${Math.max(0, ports.inputs.length - 1)} 个外部输入端口。`;
    showMessage(elements.portMessage, `${driverMessage}${scanMessage}`, driverAvailable ? 'success' : 'error');
    updateStatus(status);
  } catch (error) {
    driverAvailable = false;
    elements.installLink.hidden = false;
    showMessage(elements.portMessage, error.message, 'error');
    updateStatus({running: false});
  }
}

function currentSettings() {
  const settings = {
    input_port: selectedInput,
    tonality: selectedTonality,
    receive_sysex: elements.sysex.checked,
    receive_clock: elements.clock.checked,
    receive_active_sensing: elements.active.checked,
    panic_on_stop: elements.panic.checked,
    fixed_half_pedal_enabled: elements.halfPedal.checked,
    pedal_depth: Number(elements.pedalDepth.value),
    push_enabled: elements.pushEnabled.checked,
    push_server_url: elements.pushServerUrl.value.trim(),
  };
  if (elements.pushToken.value) settings.push_token = elements.pushToken.value;
  return settings;
}

async function saveSettings() {
  if (elements.pushEnabled.checked && !pushTokenConfigured && !elements.pushToken.value) {
    throw new Error('启用推送前请填写真实密钥');
  }
  const response = await fetch('/api/settings', {
    method: 'PUT', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(currentSettings())
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail || '保存失败');
  pushTokenConfigured = Boolean(result.push_token_configured);
  return result;
}

function updateStatus(status) {
  elements.start.disabled = !driverAvailable || status.running;
  elements.stop.disabled = !status.running;
}

document.querySelector('#refresh-ports').addEventListener('click', loadEverything);
elements.pedalDepth.addEventListener('input', () => {
  elements.pedalDepthValue.textContent = elements.pedalDepth.value;
});
elements.inputTrigger.addEventListener('click', () => {
  if (elements.inputOptions.hidden) openInputMenu();
  else closeInputMenu();
});
elements.inputTrigger.addEventListener('keydown', (event) => {
  if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(event.key)) {
    event.preventDefault();
    openInputMenu();
  }
});
elements.inputOptions.addEventListener('keydown', (event) => {
  const options = [...elements.inputOptions.children];
  const current = options.indexOf(document.activeElement);
  if (event.key === 'Escape') {
    event.preventDefault(); closeInputMenu({restoreFocus: true}); return;
  }
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault(); document.activeElement?.click(); return;
  }
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  let next = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1
    : event.key === 'ArrowDown' ? Math.min(options.length - 1, current + 1)
    : Math.max(0, current - 1);
  options[next]?.focus();
});
document.addEventListener('click', (event) => {
  if (!elements.input.contains(event.target)) closeInputMenu();
});
document.querySelector('#save-settings').addEventListener('click', async () => {
  try {
    const result = await saveSettings();
    await loadEverything();
    showMessage(
      elements.actionMessage,
      result.midi_restarted ? '设置已保存，MIDI 路由已重启' : '设置已保存',
      'success'
    );
  } catch (error) {
    await loadEverything();
    showMessage(elements.actionMessage, error.message, 'error');
  }
});
document.querySelector('#start-midi').addEventListener('click', async () => {
  try {
    await saveSettings();
    const response = await fetch('/api/midi/start', {method: 'POST'});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || '启动失败');
    if (result.input_port !== selectedInput) await loadEverything();
    updateStatus(result); showMessage(elements.actionMessage, 'MIDI 路由已启动', 'success');
  } catch (error) { showMessage(elements.actionMessage, error.message, 'error'); }
});
document.querySelector('#stop-midi').addEventListener('click', async () => {
  try {
    const response = await fetch('/api/midi/stop', {method: 'POST'});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || '停止失败');
    updateStatus(result); showMessage(elements.actionMessage, 'MIDI 路由已停止，虚拟端口已销毁', 'success');
  } catch (error) { showMessage(elements.actionMessage, error.message, 'error'); }
});

loadEverything();
