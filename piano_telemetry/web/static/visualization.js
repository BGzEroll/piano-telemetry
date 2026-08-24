const waterfall = document.querySelector('#waterfall');
const keyboard = document.querySelector('#keyboard');
const waterfallContext = waterfall.getContext('2d');
const keyboardContext = keyboard.getContext('2d');
const noteMin = 24;
const noteMax = 108;
const historyMs = 7000;
const notes = [];
const active = new Map();
const recordButton = document.querySelector('#record-toggle');
const recordLabel = document.querySelector('#record-label');
const recordMessage = document.querySelector('#record-message');
const recordDialogBackdrop = document.querySelector('#record-dialog-backdrop');
const recordDialog = document.querySelector('#record-dialog');
const recordSaveName = document.querySelector('#record-save-name');
const recordDialogError = document.querySelector('#record-dialog-error');
const recordSaveButton = document.querySelector('#record-save');
const recordDiscardButton = document.querySelector('#record-discard');
const pushDialogBackdrop = document.querySelector('#push-dialog-backdrop');
const pushDialogDescription = document.querySelector('#push-dialog-description');
const pushDialogMessage = document.querySelector('#push-dialog-message');
const pushNowButton = document.querySelector('#push-now');
const pushLaterButton = document.querySelector('#push-later');
const tonalitySelect = document.querySelector('#tonality-select');
const tonalityTrigger = document.querySelector('#tonality-trigger');
const tonalityValue = document.querySelector('#tonality-value');
const tonalityOptions = document.querySelector('#tonality-options');
const naturalPitchClasses = [0, 2, 4, 5, 7, 9, 11];
const sharpNotation = [
  {letter: 0, accidental: 0}, {letter: 0, accidental: 1},
  {letter: 1, accidental: 0}, {letter: 1, accidental: 1},
  {letter: 2, accidental: 0}, {letter: 3, accidental: 0},
  {letter: 3, accidental: 1}, {letter: 4, accidental: 0},
  {letter: 4, accidental: 1}, {letter: 5, accidental: 0},
  {letter: 5, accidental: 1}, {letter: 6, accidental: 0}
];
const flatNotation = [
  {letter: 0, accidental: 0}, {letter: 1, accidental: -1},
  {letter: 1, accidental: 0}, {letter: 2, accidental: -1},
  {letter: 2, accidental: 0}, {letter: 3, accidental: 0},
  {letter: 4, accidental: -1}, {letter: 4, accidental: 0},
  {letter: 5, accidental: -1}, {letter: 5, accidental: 0},
  {letter: 6, accidental: -1}, {letter: 6, accidental: 0}
];
let tonalities = [{
  value: 'C_major', label: 'C 大调', tonic_pitch_class: 0,
  tonic_letter: 0, mode: 'major', fifths: 0
}];
let selectedTonality = tonalities[0];
let keySpelling = new Map();
let keyAccidentals = new Map();
let state = {
  physical_notes: [], sounding_notes: [], sustain: 0, last_velocity: 0,
  chord: null, tonality: 'C_major'
};
let recordingState = {recording: false, finalizing: false, started_at: null};
let recordingDialogOpen = false;
let pendingPushResult = null;

function noteKey(channel, note) { return `${channel ?? 0}:${note}`; }

function rebuildKeySpelling() {
  const intervals = selectedTonality.mode === 'minor'
    ? [0, 2, 3, 5, 7, 8, 10]
    : [0, 2, 4, 5, 7, 9, 11];
  keySpelling = new Map();
  keyAccidentals = new Map();
  intervals.forEach((interval, degree) => {
    const pitchClass = (selectedTonality.tonic_pitch_class + interval) % 12;
    const letter = (selectedTonality.tonic_letter + degree) % 7;
    let accidental = (pitchClass - naturalPitchClasses[letter] + 12) % 12;
    if (accidental > 6) accidental -= 12;
    const spelling = {letter, accidental};
    keySpelling.set(pitchClass, spelling);
    keyAccidentals.set(letter, accidental);
  });
}

function setTonality(value) {
  selectedTonality = tonalities.find(item => item.value === value) || tonalities[0];
  state.tonality = selectedTonality.value;
  tonalityValue.textContent = selectedTonality.label;
  for (const option of tonalityOptions.children) {
    option.setAttribute('aria-selected', String(option.dataset.value === selectedTonality.value));
  }
  rebuildKeySpelling();
}

function closeTonalityMenu({restoreFocus = false} = {}) {
  tonalityOptions.hidden = true;
  tonalityTrigger.setAttribute('aria-expanded', 'false');
  if (restoreFocus) tonalityTrigger.focus();
}

function openTonalityMenu() {
  tonalityOptions.hidden = false;
  tonalityTrigger.setAttribute('aria-expanded', 'true');
  const selected = tonalityOptions.querySelector('[aria-selected="true"]');
  (selected || tonalityOptions.firstElementChild)?.focus();
}

async function saveTonality(value) {
  const previous = selectedTonality.value;
  setTonality(value);
  closeTonalityMenu({restoreFocus: true});
  try {
    const response = await fetch('/api/tonality', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({tonality: value}),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || '无法保存调式');
    if (result.state) state = result.state;
    setTonality(result.tonality);
    updateMetrics();
  } catch (error) {
    setTonality(previous);
    document.querySelector('#data-warning').textContent = error.message;
  }
}

function populateTonalities(options, current) {
  tonalities = Array.isArray(options) && options.length ? options : tonalities;
  tonalityOptions.replaceChildren();
  tonalities.forEach((item, index) => {
    const option = document.createElement('button');
    option.type = 'button';
    option.className = 'select-option';
    if (index > 0 && item.mode !== tonalities[index - 1].mode) {
      option.classList.add('mode-start');
    }
    option.setAttribute('role', 'option');
    option.dataset.value = item.value;
    option.textContent = item.label;
    option.addEventListener('click', () => saveTonality(item.value));
    tonalityOptions.append(option);
  });
  setTonality(current);
  closeTonalityMenu();
}

async function loadTonality() {
  try {
    const response = await fetch('/api/tonality');
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || '无法读取调式');
    populateTonalities(result.options, result.tonality);
  } catch (error) {
    populateTonalities(tonalities, selectedTonality.value);
    document.querySelector('#data-warning').textContent = error.message;
  }
}

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
  if (state.tonality && state.tonality !== selectedTonality.value) setTonality(state.tonality);
  document.querySelector('#chord').textContent = (state.chord || '—')
    .replaceAll('#', '♯').replaceAll('b', '♭');
  document.querySelector('#velocity').textContent = state.last_velocity || 0;
  document.querySelector('#sustain').textContent = state.sustain || 0;
  document.querySelector('#sequence').textContent = state.seq ?? '—';
  document.querySelector('#note-list').textContent = state.physical_notes?.length
    ? `当前按键：${state.physical_notes.map(noteName).join('  ')}` : '当前没有按键';
  document.querySelector('#data-warning').textContent = gap
    ? `数据缺口 ${gap.from_seq}–${gap.to_seq}` : (state.valid === false ? '状态可能不完整' : '');
}

function noteName(note) {
  const pitch = pitchSpelling(note);
  const accidental = pitch.accidental > 0 ? '♯' : pitch.accidental < 0 ? '♭' : '';
  return `${['C','D','E','F','G','A','B'][pitch.letter]}${accidental}${pitch.octave}`;
}

function recordingDuration() {
  if (!recordingState.started_at) return '00:00';
  const elapsed = Math.max(0, Date.now() - Date.parse(recordingState.started_at));
  const seconds = Math.floor(elapsed / 1000);
  const minutes = Math.floor(seconds / 60).toString().padStart(2, '0');
  return `${minutes}:${(seconds % 60).toString().padStart(2, '0')}`;
}

function renderRecordingState(status) {
  recordingState = status;
  recordButton.classList.toggle('recording', Boolean(status.recording));
  recordButton.disabled = Boolean(status.finalizing) || recordingDialogOpen;
  if (status.finalizing) recordLabel.textContent = '正在保存';
  else if (status.recording) recordLabel.textContent = `结束录制 · ${recordingDuration()}`;
  else recordLabel.textContent = '开始录制';
}

function defaultRecordingName() {
  const now = new Date();
  const pad = value => value.toString().padStart(2, '0');
  return `录制 ${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
}

function openRecordingDialog() {
  recordingDialogOpen = true;
  recordDialogBackdrop.hidden = false;
  recordDialogError.textContent = '';
  recordSaveName.value = defaultRecordingName();
  recordButton.disabled = true;
  requestAnimationFrame(() => { recordSaveName.focus(); recordSaveName.select(); });
}

function closeRecordingDialog() {
  recordingDialogOpen = false;
  recordDialogBackdrop.hidden = true;
  recordButton.disabled = Boolean(recordingState.finalizing);
}

function openPushDialog(result) {
  pendingPushResult = result;
  const displayName = result.save_name || `session_${result.session_id.slice(0, 8)}`;
  pushDialogDescription.textContent = `录制“${displayName}”已保存，是否立即推送到 OpenClaw？`;
  pushDialogMessage.textContent = '';
  pushDialogMessage.className = 'push-dialog-message';
  pushNowButton.disabled = false;
  pushNowButton.textContent = '推送';
  pushNowButton.classList.add('primary');
  pushNowButton.classList.remove('success');
  pushLaterButton.disabled = false;
  pushLaterButton.textContent = '暂不推送';
  pushDialogBackdrop.hidden = false;
}

function closePushDialog() {
  pendingPushResult = null;
  pushDialogBackdrop.hidden = true;
}

async function pushSavedRecording() {
  if (!pendingPushResult) return;
  const sessionId = pendingPushResult.session_id;
  pushNowButton.disabled = true;
  pushLaterButton.disabled = true;
  pushNowButton.textContent = '推送中…';
  pushDialogMessage.textContent = '';
  pushDialogMessage.className = 'push-dialog-message';
  try {
    const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/push`, {method: 'POST'});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || '推送失败');
    const message = result.message || '已推送';
    pushNowButton.textContent = message;
    pushNowButton.classList.remove('primary');
    pushNowButton.classList.add('success');
    pushDialogMessage.textContent = result.duplicate ? '服务端已存在，本地已记录为已推送。' : '录制已成功推送。';
    pushDialogMessage.classList.add('message-success');
    recordMessage.textContent = result.duplicate ? '服务端已有这次录制' : '录制已推送';
    recordMessage.classList.remove('error');
    pushLaterButton.disabled = false;
    pushLaterButton.textContent = '关闭';
  } catch (error) {
    pushNowButton.disabled = false;
    pushLaterButton.disabled = false;
    pushNowButton.textContent = '重试';
    pushDialogMessage.textContent = error.message;
    pushDialogMessage.classList.add('message-error');
  }
}

async function loadRecordingState() {
  try {
    const response = await fetch('/api/recording');
    const status = await response.json();
    if (!response.ok) throw new Error(status.detail || '无法读取录制状态');
    renderRecordingState(status);
  } catch (error) {
    recordButton.disabled = true;
    recordMessage.textContent = error.message;
    recordMessage.classList.add('error');
  }
}

async function toggleRecording() {
  if (recordingState.recording) {
    openRecordingDialog();
    return;
  }
  recordButton.disabled = true;
  recordMessage.textContent = '';
  recordMessage.classList.remove('error');
  try {
    const response = await fetch('/api/recording/start', {method: 'POST'});
    const status = await response.json();
    if (!response.ok) throw new Error(status.detail || '录制操作失败');
    renderRecordingState(status);
    recordMessage.textContent = '正在录制';
  } catch (error) {
    recordButton.disabled = false;
    recordMessage.textContent = error.message;
    recordMessage.classList.add('error');
  }
}

async function finishRecording(choice) {
  recordSaveName.disabled = true;
  recordSaveButton.disabled = true;
  recordDiscardButton.disabled = true;
  recordDialogError.textContent = '';
  try {
    const response = await fetch('/api/recording/stop', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(choice),
    });
    const status = await response.json();
    if (!response.ok) throw new Error(status.detail || '无法结束录制');
    renderRecordingState(status);
    closeRecordingDialog();
    if (status.result.discarded) {
      recordMessage.textContent = '本次录制未保存';
      recordMessage.classList.remove('error');
    } else {
      const suffix = status.result.complete ? '' : '，数据可能不完整';
      recordMessage.textContent = `录制已保存，共 ${status.result.event_count} 个事件${suffix}`;
      recordMessage.classList.toggle('error', !status.result.complete);
      if (status.push_enabled) openPushDialog(status.result);
    }
  } catch (error) {
    recordDialogError.textContent = error.message;
  } finally {
    recordSaveName.disabled = false;
    recordSaveButton.disabled = false;
    recordDiscardButton.disabled = false;
  }
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

function pitchSpelling(note) {
  const pitchClass = note % 12;
  const notation = keySpelling.get(pitchClass)
    || (selectedTonality.fifths < 0 ? flatNotation[pitchClass] : sharpNotation[pitchClass]);
  let octave = Math.floor(note / 12) - 1;
  let writtenMidi = (octave + 1) * 12
    + naturalPitchClasses[notation.letter] + notation.accidental;
  while (writtenMidi > note) { writtenMidi -= 12; octave -= 1; }
  while (writtenMidi < note) { writtenMidi += 12; octave += 1; }
  return {letter: notation.letter, accidental: notation.accidental, octave};
}

function staffPitch(note) {
  const spelling = pitchSpelling(note);
  const signatureAccidental = keyAccidentals.get(spelling.letter) || 0;
  let accidental = '';
  if (spelling.accidental !== signatureAccidental) {
    accidental = spelling.accidental > 0 ? '♯'
      : spelling.accidental < 0 ? '♭' : '♮';
  }
  return {
    diatonic: spelling.octave * 7 + spelling.letter,
    accidental,
  };
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

function drawKeySignature(startX, bottomY, lineGap, clef) {
  const fifths = selectedTonality.fifths || 0;
  if (!fifths) return startX;
  const sharpSteps = clef === 'treble' ? [8, 5, 9, 6, 3, 7, 4] : [6, 3, 7, 4, 1, 5, 2];
  const flatSteps = clef === 'treble' ? [4, 7, 3, 6, 2, 5, 1] : [2, 5, 1, 4, 0, 3, -1];
  const steps = fifths > 0 ? sharpSteps : flatSteps;
  const symbol = fifths > 0 ? '♯' : '♭';
  const count = Math.abs(fifths);
  waterfallContext.save();
  waterfallContext.fillStyle = 'rgba(16,22,20,.9)';
  waterfallContext.font = '18px "Segoe UI Symbol", "Noto Music", serif';
  waterfallContext.textAlign = 'center';
  waterfallContext.textBaseline = 'middle';
  for (let index = 0; index < count; index++) {
    const x = startX + index * 9;
    const y = bottomY - steps[index] * lineGap / 2;
    waterfallContext.fillText(symbol, x, y);
  }
  waterfallContext.restore();
  return startX + count * 9;
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
  if (panelWidth < 230 || panelHeight < 170) return;

  const left = (width - panelWidth) / 2;
  const top = (height - panelHeight) / 2;
  const right = left + panelWidth;
  const lineGap = 10;
  const trebleBottom = top + 68;
  const bassBottom = top + 146;
  const staffStart = left + 52;
  const staffEnd = right - 14;
  const clefX = staffStart - 24;
  const signatureStart = staffStart + 8;
  const signatureEnd = signatureStart + Math.abs(selectedTonality.fifths || 0) * 9;
  const noteX = Math.max(signatureEnd + 18, staffEnd - 42);

  waterfallContext.save();
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
  waterfallContext.fillText('𝄞', clefX, trebleBottom - lineGap * 2 + 1);
  waterfallContext.font = '38px "Segoe UI Symbol", "Noto Music", serif';
  waterfallContext.fillText('𝄢', clefX, bassBottom - lineGap * 2);
  drawKeySignature(signatureStart, trebleBottom, lineGap, 'treble');
  drawKeySignature(signatureStart, bassBottom, lineGap, 'bass');

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
    else if (payload.kind === 'state') {
      state = payload;
      if (payload.tonality) setTonality(payload.tonality);
      updateMetrics();
    }
  };
  socket.onclose = () => {
    dot.classList.remove('online'); label.textContent = '正在重连';
    setTimeout(connectWebSocket, 1500);
  };
}

window.addEventListener('resize', () => {});
tonalityTrigger.addEventListener('click', () => {
  if (tonalityOptions.hidden) openTonalityMenu();
  else closeTonalityMenu();
});
tonalityTrigger.addEventListener('keydown', event => {
  if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(event.key)) {
    event.preventDefault();
    openTonalityMenu();
  }
});
tonalityOptions.addEventListener('keydown', event => {
  const options = [...tonalityOptions.children];
  const current = options.indexOf(document.activeElement);
  if (event.key === 'Escape') {
    event.preventDefault(); closeTonalityMenu({restoreFocus: true}); return;
  }
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault(); document.activeElement?.click(); return;
  }
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1
    : event.key === 'ArrowDown' ? Math.min(options.length - 1, current + 1)
    : Math.max(0, current - 1);
  options[next]?.focus();
});
document.addEventListener('click', event => {
  if (!tonalitySelect.contains(event.target)) closeTonalityMenu();
});
recordButton.addEventListener('click', toggleRecording);
recordDialog.addEventListener('submit', event => {
  event.preventDefault();
  const saveName = recordSaveName.value.trim();
  if (!saveName) {
    recordDialogError.textContent = '请输入保存名称';
    recordSaveName.focus();
    return;
  }
  finishRecording({save_name: saveName});
});
recordDiscardButton.addEventListener('click', () => finishRecording({discard: true}));
pushNowButton.addEventListener('click', pushSavedRecording);
pushLaterButton.addEventListener('click', closePushDialog);
setInterval(() => {
  if (recordingState.recording) renderRecordingState(recordingState);
}, 1000);
setInterval(loadRecordingState, 5000);
rebuildKeySpelling();
loadTonality(); loadRecordingState(); connectWebSocket(); requestAnimationFrame(drawWaterfall); requestAnimationFrame(drawKeyboard);
