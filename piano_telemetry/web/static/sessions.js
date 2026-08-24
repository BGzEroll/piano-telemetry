const list = document.querySelector('#sessions-list');
const notice = document.querySelector('#sessions-notice');
const refreshButton = document.querySelector('#refresh-sessions');

function formatDate(value) {
  if (!value) return '时间未知';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', {hour12: false});
}

function showNotice(message, kind = '') {
  notice.textContent = message;
  notice.className = `sessions-notice ${kind ? `message-${kind}` : ''}`;
}

function createSessionCard(session, pushEnabled) {
  const card = document.createElement('article');
  card.className = 'session-card';

  const main = document.createElement('div');
  main.className = 'session-card-main';
  const title = document.createElement('h2');
  title.textContent = session.save_name;
  const details = document.createElement('span');
  details.textContent = `${formatDate(session.started_at)} · ${session.event_count} 个事件`;
  main.append(title, details);

  const state = document.createElement('div');
  state.className = 'session-card-state';
  const completeness = document.createElement('span');
  completeness.className = `session-badge ${session.complete ? 'complete' : 'incomplete'}`;
  completeness.textContent = session.complete ? '完整' : '可能不完整';
  state.append(completeness);

  if (session.pushed) {
    const pushed = document.createElement('span');
    pushed.className = 'session-badge pushed';
    pushed.textContent = '已推送';
    state.append(pushed);
  } else if (pushEnabled) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'button primary compact';
    button.textContent = '推送';
    const message = document.createElement('small');
    message.className = 'session-push-message';
    button.addEventListener('click', async () => {
      button.disabled = true;
      button.textContent = '推送中…';
      message.textContent = '';
      message.classList.remove('error');
      try {
        const response = await fetch(`/api/sessions/${encodeURIComponent(session.session_id)}/push`, {method: 'POST'});
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || '推送失败');
        button.textContent = result.message || '已推送';
        button.classList.remove('primary');
        button.classList.add('success');
        message.textContent = result.duplicate ? '服务端已存在' : '';
      } catch (error) {
        button.disabled = false;
        button.textContent = '推送';
        message.textContent = error.message;
        message.classList.add('error');
      }
    });
    state.append(button, message);
  }

  card.append(main, state);
  return card;
}

async function loadSessions() {
  refreshButton.disabled = true;
  showNotice('正在读取录制记录…');
  try {
    const response = await fetch('/api/sessions');
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || '读取录制记录失败');
    list.replaceChildren();
    if (!result.push_enabled) {
      showNotice('OpenClaw 推送未启用；可在设置页面配置服务器和密钥。');
    } else {
      showNotice(`推送服务器：${result.server_url}`, 'success');
    }
    if (!result.sessions.length) {
      const empty = document.createElement('div');
      empty.className = 'sessions-empty';
      empty.textContent = '还没有可用的录制记录';
      list.append(empty);
      return;
    }
    result.sessions.forEach(session => list.append(createSessionCard(session, result.push_enabled)));
  } catch (error) {
    list.replaceChildren();
    showNotice(error.message, 'error');
  } finally {
    refreshButton.disabled = false;
  }
}

refreshButton.addEventListener('click', loadSessions);
loadSessions();
