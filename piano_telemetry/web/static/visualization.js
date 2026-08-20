const waterfall = document.querySelector('#waterfall');
const keyboard = document.querySelector('#keyboard');
const waterfallContext = waterfall.getContext('2d');
const keyboardContext = keyboard.getContext('2d');
const noteMin = 24;
const noteMax = 108;
const historyMs = 7000;
const notes = [];
const active = new Map();
let state = {physical_notes: [], sounding_notes: [], sustain: 0, last_velocity: 0, chord: null};

function noteKey(channel, note) { return `${channel ?? 0}:${note}`; }

function applyTelemetry(payload) {
  const event = payload.event;
  state = payload.state || state;
  const now = performance.now();
  if (event.type === 'note_on' && event.velocity > 0) {
    active.set(noteKey(event.channel, event.note), {
      note: event.note, channel: event.channel || 0, start: now,
      velocity: event.velocity || 0
    });
  } else if (event.type === 'note_off' || (event.type === 'note_on' && event.velocity === 0)) {
    const key = noteKey(event.channel, event.note);
    const item = active.get(key);
    if (item) { item.end = now; notes.push(item); active.delete(key); }
  }
  updateMetrics(payload.gap);
}

function updateMetrics(gap) {
  document.querySelector('#chord').textContent = state.chord || '—';
  document.querySelector('#velocity').textContent = state.last_velocity || 0;
  document.querySelector('#sustain').textContent = state.sustain || 0;
  document.querySelector('#sequence').textContent = state.seq ?? '—';
  document.querySelector('#note-list').textContent = state.physical_notes?.length
    ? `当前按键：${state.physical_notes.map(noteName).join('  ')}` : '当前没有按键';
  document.querySelector('#data-warning').textContent = gap
    ? `数据缺口 ${gap.from_seq}–${gap.to_seq}` : (state.valid === false ? '状态可能不完整' : '');
}

function noteName(note) {
  const names = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];
  return `${names[note % 12]}${Math.floor(note / 12) - 1}`;
}

function resizeCanvas(canvas, context) {
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(1, canvas.clientWidth);
  const height = Math.max(1, canvas.clientHeight);
  if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
    canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
  }
  return {width, height};
}

function noteX(note, width) { return ((note - noteMin) / (noteMax - noteMin + 1)) * width; }

function drawWaterfall(now) {
  const {width, height} = resizeCanvas(waterfall, waterfallContext);
  waterfallContext.clearRect(0, 0, width, height);
  waterfallContext.fillStyle = '#f9fcfb'; waterfallContext.fillRect(0, 0, width, height);
  const noteWidth = width / (noteMax - noteMin + 1);
  for (let note = noteMin; note <= noteMax; note++) {
    const x = noteX(note, width);
    waterfallContext.fillStyle = [1,3,6,8,10].includes(note % 12)
      ? 'rgba(24,52,44,.018)' : 'rgba(24,52,44,.04)';
    waterfallContext.fillRect(x, 0, Math.max(1, noteWidth - 1), height);
  }
  waterfallContext.strokeStyle = 'rgba(44,168,137,.65)';
  waterfallContext.beginPath(); waterfallContext.moveTo(0, height - 2); waterfallContext.lineTo(width, height - 2); waterfallContext.stroke();

  const visible = notes.filter(item => now - item.end < historyMs);
  notes.length = 0; notes.push(...visible);
  for (const item of [...visible, ...active.values()]) drawNote(item, now, width, height, noteWidth);
  requestAnimationFrame(drawWaterfall);
}

function drawNote(item, now, width, height, noteWidth) {
  if (item.note < noteMin || item.note > noteMax) return;
  const end = item.end || now;
  const yBottom = height - ((now - end) / historyMs) * height;
  const yTop = height - ((now - item.start) / historyMs) * height;
  const y = Math.max(0, Math.min(yTop, yBottom));
  const h = Math.max(4, Math.abs(yBottom - yTop));
  const x = noteX(item.note, width);
  const alpha = .55 + (item.velocity / 127) * .45;
  waterfallContext.fillStyle = `rgba(44,168,137,${alpha})`;
  waterfallContext.shadowColor = 'rgba(44,168,137,.45)'; waterfallContext.shadowBlur = item.end ? 0 : 12;
  const barWidth = Math.max(2, noteWidth - 2);
  waterfallContext.beginPath();
  waterfallContext.roundRect(x + 1, y, barWidth, h, Math.min(3, barWidth / 2, h / 2));
  waterfallContext.fill();
  waterfallContext.shadowBlur = 0;
}

function drawKeyboard() {
  const {width, height} = resizeCanvas(keyboard, keyboardContext);
  keyboardContext.clearRect(0, 0, width, height);
  const whiteNotes = [];
  for (let note = noteMin; note <= noteMax; note++) if (![1,3,6,8,10].includes(note % 12)) whiteNotes.push(note);
  const whiteWidth = width / whiteNotes.length;
  whiteNotes.forEach((note, index) => {
    keyboardContext.fillStyle = state.physical_notes?.includes(note) ? '#55c9ae' : (state.sounding_notes?.includes(note) ? '#b9e9df' : '#ffffff');
    keyboardContext.fillRect(index * whiteWidth, 0, whiteWidth - 1, height);
  });
  for (let note = noteMin; note <= noteMax; note++) {
    if (![1,3,6,8,10].includes(note % 12)) continue;
    const previousWhite = whiteNotes.filter(value => value < note).length;
    const x = previousWhite * whiteWidth - whiteWidth * .32;
    keyboardContext.fillStyle = state.physical_notes?.includes(note) ? '#39b99a' : (state.sounding_notes?.includes(note) ? '#78cfc3' : '#29463d');
    keyboardContext.fillRect(x, 0, whiteWidth * .64, height * .62);
  }
  requestAnimationFrame(drawKeyboard);
}

async function loadRouteStatus() {
  try {
    const response = await fetch('/api/status'); const status = await response.json();
    document.querySelector('#route-label').textContent = status.running
      ? `${status.input_port} → ${status.output_port}` : '未运行 · 请前往设置';
  } catch (_) { document.querySelector('#route-label').textContent = '服务不可用'; }
}

function connectWebSocket() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const socket = new WebSocket(`${protocol}//${location.host}/ws`);
  const dot = document.querySelector('#ws-dot'); const label = document.querySelector('#ws-status');
  socket.onopen = () => { dot.classList.add('online'); label.textContent = '实时连接'; };
  socket.onmessage = message => {
    const payload = JSON.parse(message.data);
    if (payload.kind === 'telemetry') applyTelemetry(payload);
    else if (payload.kind === 'state') { state = payload; updateMetrics(); }
  };
  socket.onclose = () => {
    dot.classList.remove('online'); label.textContent = '正在重连';
    setTimeout(connectWebSocket, 1500);
  };
}

window.addEventListener('resize', () => {});
loadRouteStatus(); connectWebSocket(); requestAnimationFrame(drawWaterfall); requestAnimationFrame(drawKeyboard);
