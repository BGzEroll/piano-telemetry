const elements = {
  enabled: document.querySelector('#mapping-enabled'),
  message: document.querySelector('#mapping-message'),
  learn: document.querySelector('#learn-note'),
  selected: document.querySelector('#selected-note'),
  clear: document.querySelector('#clear-binding'),
  piano: document.querySelector('#mapping-piano'),
  pianoScroll: document.querySelector('#piano-scroll'),
  computerKeyboard: document.querySelector('#computer-keyboard'),
  bindingList: document.querySelector('#binding-list'),
  bindingCount: document.querySelector('#binding-count'),
};

const NOTE_MIN = 21;
const NOTE_MAX = 108;
const WHITE_WIDTH = 24;
const pitchNames = ['C', 'C♯', 'D', 'D♯', 'E', 'F', 'F♯', 'G', 'G♯', 'A', 'A♯', 'B'];
const blackPitchClasses = new Set([1, 3, 6, 8, 10]);
const keyRows = [
  ['Digit1', 'Digit2', 'Digit3', 'Digit4', 'Digit5', 'Digit6', 'Digit7', 'Digit8', 'Digit9', 'Digit0'],
  ['KeyQ', 'KeyW', 'KeyE', 'KeyR', 'KeyT', 'KeyY', 'KeyU', 'KeyI', 'KeyO', 'KeyP'],
  ['KeyA', 'KeyS', 'KeyD', 'KeyF', 'KeyG', 'KeyH', 'KeyJ', 'KeyK', 'KeyL'],
  ['KeyZ', 'KeyX', 'KeyC', 'KeyV', 'KeyB', 'KeyN', 'KeyM'],
];

let enabled = false;
let bindings = {};
let selectedNote = null;
let learning = false;
let saveChain = Promise.resolve();

function noteName(note) {
  return `${pitchNames[note % 12]}${Math.floor(note / 12) - 1}`;
}

function keyLabel(code) {
  return code.startsWith('Digit') ? code.slice(5) : code.slice(3);
}

function showMessage(text, kind = '') {
  elements.message.textContent = text;
  elements.message.className = `action-message ${kind ? `message-${kind}` : ''}`;
}

function renderPiano() {
  elements.piano.replaceChildren();
  let whiteIndex = 0;
  for (let note = NOTE_MIN; note <= NOTE_MAX; note += 1) {
    const black = blackPitchClasses.has(note % 12);
    const key = document.createElement('button');
    key.type = 'button';
    key.className = `mapping-piano-key ${black ? 'black' : 'white'}`;
    key.dataset.note = String(note);
    key.title = `${noteName(note)} · MIDI ${note}`;
    key.setAttribute('aria-label', key.title);
    if (black) {
      key.style.left = `${whiteIndex * WHITE_WIDTH - 8}px`;
    } else {
      key.style.left = `${whiteIndex * WHITE_WIDTH}px`;
      if (note % 12 === 0) key.textContent = noteName(note);
      whiteIndex += 1;
    }
    key.addEventListener('click', () => selectNote(note, {scroll: false}));
    elements.piano.append(key);
  }
  elements.piano.style.width = `${whiteIndex * WHITE_WIDTH}px`;
  updatePianoState();
  requestAnimationFrame(() => {
    const middleC = elements.piano.querySelector('[data-note="60"]');
    if (middleC) {
      elements.pianoScroll.scrollLeft = Math.max(
        0,
        middleC.offsetLeft - elements.pianoScroll.clientWidth / 2
      );
    }
  });
}

function renderComputerKeyboard() {
  elements.computerKeyboard.replaceChildren();
  const notesByKey = {};
  Object.entries(bindings).forEach(([note, code]) => {
    (notesByKey[code] ||= []).push(Number(note));
  });
  keyRows.forEach((row, rowIndex) => {
    const rowElement = document.createElement('div');
    rowElement.className = `computer-key-row row-${rowIndex}`;
    row.forEach(code => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'computer-key';
      const notes = (notesByKey[code] || []).sort((a, b) => a - b);
      if (notes.length) button.classList.add('assigned');
      if (selectedNote !== null && bindings[String(selectedNote)] === code) {
        button.classList.add('selected-binding');
      }
      const label = document.createElement('b');
      label.textContent = keyLabel(code);
      const detail = document.createElement('small');
      detail.textContent = notes.map(noteName).join(' · ');
      button.append(label, detail);
      button.title = notes.length ? `${keyLabel(code)}：${detail.textContent}` : keyLabel(code);
      button.addEventListener('click', () => bindSelectedNote(code));
      rowElement.append(button);
    });
    elements.computerKeyboard.append(rowElement);
  });
}

function renderBindingList() {
  const entries = Object.entries(bindings)
    .map(([note, code]) => [Number(note), code])
    .sort((left, right) => left[0] - right[0]);
  elements.bindingCount.textContent = `${entries.length} 个`;
  elements.bindingList.replaceChildren();
  if (!entries.length) {
    const empty = document.createElement('span');
    empty.className = 'binding-empty';
    empty.textContent = '尚未配置映射';
    elements.bindingList.append(empty);
    return;
  }
  entries.forEach(([note, code]) => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'binding-chip';
    item.innerHTML = `<span>${noteName(note)}</span><i>→</i><b>${keyLabel(code)}</b>`;
    item.title = '点击选择此钢琴键';
    item.addEventListener('click', () => selectNote(note));
    elements.bindingList.append(item);
  });
}

function updatePianoState() {
  elements.piano.querySelectorAll('.mapping-piano-key').forEach(key => {
    const note = Number(key.dataset.note);
    key.classList.toggle('selected', note === selectedNote);
    key.classList.toggle('bound', Object.hasOwn(bindings, String(note)));
  });
}

function renderAll() {
  elements.enabled.checked = enabled;
  elements.selected.textContent = selectedNote === null
    ? '未选择'
    : `${noteName(selectedNote)} · MIDI ${selectedNote}`;
  elements.clear.disabled = selectedNote === null || !Object.hasOwn(bindings, String(selectedNote));
  updatePianoState();
  renderComputerKeyboard();
  renderBindingList();
}

function selectNote(note, {scroll = true} = {}) {
  selectedNote = Math.max(NOTE_MIN, Math.min(NOTE_MAX, Number(note)));
  learning = false;
  elements.learn.classList.remove('learning');
  elements.learn.textContent = '按下电钢选键';
  renderAll();
  if (scroll) {
    elements.piano.querySelector(`[data-note="${selectedNote}"]`)?.scrollIntoView({
      behavior: 'smooth', block: 'nearest', inline: 'center'
    });
  }
}

function persist(message = '映射已保存') {
  const payload = {enabled, bindings: {...bindings}};
  saveChain = saveChain.then(async () => {
    const response = await fetch('/api/key-mapping', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || '保存失败');
    showMessage(message, 'success');
  }).catch(error => showMessage(error.message, 'error'));
  return saveChain;
}

function bindSelectedNote(code) {
  if (selectedNote === null) {
    showMessage('请先选择一个钢琴键', 'error');
    return;
  }
  bindings[String(selectedNote)] = code;
  renderAll();
  persist(`${noteName(selectedNote)} 已绑定到 ${keyLabel(code)}`);
}

async function loadMapping() {
  try {
    const response = await fetch('/api/key-mapping');
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || '读取映射失败');
    enabled = Boolean(result.enabled);
    bindings = result.bindings || {};
    renderAll();
  } catch (error) {
    showMessage(error.message, 'error');
  }
}

function connectWebSocket() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const socket = new WebSocket(`${protocol}//${location.host}/ws`);
  socket.addEventListener('message', message => {
    if (!learning) return;
    const payload = JSON.parse(message.data);
    const event = payload.event;
    if (payload.kind === 'telemetry' && event?.type === 'note_on' && event.velocity > 0) {
      selectNote(event.note);
      showMessage(`已选择 ${noteName(event.note)}，请点击要绑定的电脑按键`);
    }
  });
  socket.addEventListener('close', () => setTimeout(connectWebSocket, 1500));
}

elements.enabled.addEventListener('change', () => {
  enabled = elements.enabled.checked;
  persist(enabled ? '按键映射已启用' : '按键映射已关闭，已释放所有按键');
});

elements.learn.addEventListener('click', () => {
  learning = !learning;
  elements.learn.classList.toggle('learning', learning);
  elements.learn.textContent = learning ? '等待电钢输入…' : '按下电钢选键';
  showMessage(learning ? '请按下一个电钢琴键' : '已取消学习');
});

elements.clear.addEventListener('click', () => {
  if (selectedNote === null) return;
  delete bindings[String(selectedNote)];
  const name = noteName(selectedNote);
  renderAll();
  persist(`${name} 的映射已清除`);
});

renderPiano();
loadMapping();
connectWebSocket();
