const waterfall = document.querySelector('#waterfall');
const keyboard = document.querySelector('#keyboard');
const waterfallContext = waterfall.getContext('2d');
const keyboardContext = keyboard.getContext('2d');
const noteMin = 24;
const noteMax = 108;
const historyMs = 7000;
const notes = [];
const active = new Map();
const pitchNotation = [
  {letter: 0, accidental: ''}, {letter: 0, accidental: '♯'},
  {letter: 1, accidental: ''}, {letter: 1, accidental: '♯'},
  {letter: 2, accidental: ''}, {letter: 3, accidental: ''},
  {letter: 3, accidental: '♯'}, {letter: 4, accidental: ''},
  {letter: 4, accidental: '♯'}, {letter: 5, accidental: ''},
  {letter: 5, accidental: '♯'}, {letter: 6, accidental: ''}
];
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

function keyboardGeometry(width) {
  const blackPitchClasses = new Set([1, 3, 6, 8, 10]);
  const whiteNotes = [];
  for (let note = noteMin; note <= noteMax; note++) {
    if (!blackPitchClasses.has(note % 12)) whiteNotes.push(note);
  }
  const whiteWidth = width / whiteNotes.length;
  const whiteIndexes = new Map(whiteNotes.map((note, index) => [note, index]));

  return {
    whiteNotes,
    whiteWidth,
    keyRect(note) {
      if (!blackPitchClasses.has(note % 12)) {
        return {x: whiteIndexes.get(note) * whiteWidth, width: whiteWidth, isBlack: false};
      }
      const previousWhiteCount = whiteNotes.findIndex(value => value > note);
      const count = previousWhiteCount === -1 ? whiteNotes.length : previousWhiteCount;
      return {x: count * whiteWidth - whiteWidth * .32, width: whiteWidth * .64, isBlack: true};
    }
  };
}

function drawWaterfall(now) {
  const {width, height} = resizeCanvas(waterfall, waterfallContext);
  waterfallContext.clearRect(0, 0, width, height);
  waterfallContext.strokeStyle = 'rgba(44,168,137,.65)';
  waterfallContext.beginPath(); waterfallContext.moveTo(0, height - 2); waterfallContext.lineTo(width, height - 2); waterfallContext.stroke();

  drawCurrentStaff(width, height);
  const geometry = keyboardGeometry(width);
  const visible = notes.filter(item => now - item.end < historyMs);
  notes.length = 0; notes.push(...visible);
  for (const item of [...visible, ...active.values()]) drawNote(item, now, height, geometry);
  requestAnimationFrame(drawWaterfall);
}

function drawNote(item, now, height, geometry) {
  if (item.note < noteMin || item.note > noteMax) return;
  const end = item.end || now;
  const yBottom = height - ((now - end) / historyMs) * height;
  const yTop = height - ((now - item.start) / historyMs) * height;
  const y = Math.min(yTop, yBottom);
  const h = Math.max(4, Math.abs(yBottom - yTop));
  const key = geometry.keyRect(item.note);
  const alpha = .2 + Math.min(127, Math.max(0, item.velocity)) / 127 * .55;
  waterfallContext.fillStyle = `rgba(44,168,137,${alpha})`;
  waterfallContext.shadowColor = 'rgba(44,168,137,.45)'; waterfallContext.shadowBlur = item.end ? 0 : 12;
  const barWidth = Math.max(2, key.width - (key.isBlack ? 0 : 1));
  waterfallContext.beginPath();
  waterfallContext.roundRect(key.x, y, barWidth, h, Math.min(3, barWidth / 2, h / 2));
  waterfallContext.fill();
  waterfallContext.shadowBlur = 0;
}

function staffPitch(note) {
  const notation = pitchNotation[note % 12];
  const octave = Math.floor(note / 12) - 1;
  return {diatonic: octave * 7 + notation.letter, accidental: notation.accidental};
}

function drawStaffLines(startX, endX, bottomY, lineGap) {
  waterfallContext.beginPath();
  for (let line = 0; line < 5; line++) {
    const y = bottomY - line * lineGap;
    waterfallContext.moveTo(startX, y);
    waterfallContext.lineTo(endX, y);
  }
  waterfallContext.stroke();
}

function drawLedgerLines(noteX, staffStep, bottomY, lineGap) {
  waterfallContext.beginPath();
  for (let step = -2; step >= staffStep; step -= 2) {
    const y = bottomY - step * lineGap / 2;
    waterfallContext.moveTo(noteX - 11, y);
    waterfallContext.lineTo(noteX + 11, y);
  }
  for (let step = 10; step <= staffStep; step += 2) {
    const y = bottomY - step * lineGap / 2;
    waterfallContext.moveTo(noteX - 11, y);
    waterfallContext.lineTo(noteX + 11, y);
  }
  waterfallContext.stroke();
}

function drawStaffNotes(noteNumbers, {bottomY, referenceDiatonic, noteX, lineGap}, physicalNotes) {
  const pitches = noteNumbers
    .map(note => ({note, ...staffPitch(note)}))
    .sort((left, right) => left.diatonic - right.diatonic);
  let previousStep = null;
  let previousShift = 0;

  for (const pitch of pitches) {
    const staffStep = pitch.diatonic - referenceDiatonic;
    const adjacent = previousStep !== null && staffStep - previousStep === 1;
    const shift = adjacent && previousShift === 0 ? 9 : 0;
    const x = noteX + shift;
    const y = bottomY - staffStep * lineGap / 2;

    waterfallContext.lineWidth = 1.1;
    waterfallContext.strokeStyle = 'rgba(16,22,20,.76)';
    drawLedgerLines(x, staffStep, bottomY, lineGap);

    waterfallContext.save();
    waterfallContext.globalAlpha = physicalNotes.has(pitch.note) ? .96 : .46;
    waterfallContext.fillStyle = '#101614';
    waterfallContext.beginPath();
    waterfallContext.ellipse(x, y, 7.5, 5.2, -.24, 0, Math.PI * 2);
    waterfallContext.fill();
    if (pitch.accidental) {
      waterfallContext.fillStyle = '#101614';
      waterfallContext.font = '17px "Segoe UI Symbol", serif';
      waterfallContext.textAlign = 'center';
      waterfallContext.textBaseline = 'middle';
      waterfallContext.fillText(pitch.accidental, x - 15, y);
    }
    waterfallContext.restore();
    previousStep = staffStep;
    previousShift = shift;
  }
}

function drawCurrentStaff(width, height) {
  const horizontalMargin = width < 640 ? 18 : 46;
  const panelWidth = Math.min(260, width - horizontalMargin * 2);
  const panelHeight = Math.min(190, height - 24);
  if (panelWidth < 240 || panelHeight < 170) return;

  const left = (width - panelWidth) / 2;
  const top = (height - panelHeight) / 2;
  const right = left + panelWidth;
  const lineGap = 10;
  const trebleBottom = top + 68;
  const bassBottom = top + 146;
  const staffStart = left + 52;
  const staffEnd = right - 14;
  const noteX = staffStart + (staffEnd - staffStart) * .58;

  waterfallContext.save();
  waterfallContext.shadowColor = 'rgba(24,52,44,.08)';
  waterfallContext.shadowBlur = 18;
  waterfallContext.fillStyle = 'rgba(255,255,255,.9)';
  waterfallContext.beginPath();
  waterfallContext.roundRect(left, top, panelWidth, panelHeight, 16);
  waterfallContext.fill();
  waterfallContext.shadowBlur = 0;
  waterfallContext.strokeStyle = 'rgba(16,22,20,.14)';
  waterfallContext.lineWidth = 1;
  waterfallContext.stroke();

  waterfallContext.strokeStyle = 'rgba(16,22,20,.72)';
  waterfallContext.lineWidth = 1.35;
  drawStaffLines(staffStart, staffEnd, trebleBottom, lineGap);
  drawStaffLines(staffStart, staffEnd, bassBottom, lineGap);
  waterfallContext.beginPath();
  waterfallContext.moveTo(staffStart, trebleBottom - lineGap * 4);
  waterfallContext.lineTo(staffStart, bassBottom);
  waterfallContext.stroke();

  waterfallContext.fillStyle = '#101614';
  waterfallContext.textAlign = 'center';
  waterfallContext.textBaseline = 'middle';
  waterfallContext.font = '48px "Segoe UI Symbol", "Noto Music", serif';
  waterfallContext.fillText('𝄞', staffStart - 24, trebleBottom - lineGap * 2 + 1);
  waterfallContext.font = '38px "Segoe UI Symbol", "Noto Music", serif';
  waterfallContext.fillText('𝄢', staffStart - 24, bassBottom - lineGap * 2);

  const soundingNotes = [...new Set(state.sounding_notes || [])]
    .filter(note => Number.isInteger(note) && note >= noteMin && note <= noteMax)
    .sort((left, right) => left - right);
  const physicalNotes = new Set(state.physical_notes || []);
  drawStaffNotes(
    soundingNotes.filter(note => note >= 60),
    {bottomY: trebleBottom, referenceDiatonic: 30, noteX, lineGap},
    physicalNotes
  );
  drawStaffNotes(
    soundingNotes.filter(note => note < 60),
    {bottomY: bassBottom, referenceDiatonic: 18, noteX, lineGap},
    physicalNotes
  );
  waterfallContext.restore();
}

function drawKeyboard() {
  const {width, height} = resizeCanvas(keyboard, keyboardContext);
  keyboardContext.clearRect(0, 0, width, height);
  const geometry = keyboardGeometry(width);
  geometry.whiteNotes.forEach(note => {
    const key = geometry.keyRect(note);
    keyboardContext.fillStyle = state.physical_notes?.includes(note) ? '#55c9ae' : (state.sounding_notes?.includes(note) ? '#b9e9df' : '#ffffff');
    keyboardContext.fillRect(key.x, 0, key.width - 1, height);
  });
  for (let note = noteMin; note <= noteMax; note++) {
    if (![1,3,6,8,10].includes(note % 12)) continue;
    const key = geometry.keyRect(note);
    keyboardContext.fillStyle = state.physical_notes?.includes(note) ? '#39b99a' : (state.sounding_notes?.includes(note) ? '#78cfc3' : '#29463d');
    keyboardContext.fillRect(key.x, 0, key.width, height * .62);
  }
  requestAnimationFrame(drawKeyboard);
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
connectWebSocket(); requestAnimationFrame(drawWaterfall); requestAnimationFrame(drawKeyboard);
