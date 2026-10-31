// QueueX Operator Terminal Controller
const counterSelect = document.getElementById('counter-select');
const socket = (typeof io !== 'undefined') ? io() : null;
let currentRoom = null;
let lastQueue = [];

function getCounterSlug() {
  const hidden = document.getElementById('assigned-counter-slug');
  if (hidden && hidden.value) return hidden.value.trim();
  if (counterSelect && counterSelect.value) return counterSelect.value.trim();
  return '';
}

// Lightweight Web Audio Chime Generator
function playChime() {
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();

    osc.type = 'sine';
    osc.frequency.setValueAtTime(587.33, ctx.currentTime); // D5
    osc.frequency.exponentialRampToValueAtTime(880, ctx.currentTime + 0.15); // A5

    gain.gain.setValueAtTime(0.25, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.6);

    osc.connect(gain);
    gain.connect(ctx.destination);

    osc.start();
    osc.stop(ctx.currentTime + 0.65);
  } catch (e) {
    // AudioContext blocked by browser policy until gesture
  }
}

function showToast(message, type = 'info') {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.classList.add('show'), 10);
  setTimeout(() => {
    toast.classList.remove('show');
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

function showError(message) {
  showToast(message || 'Something went wrong. Please try again.', 'error');
}

function handleJson(response) {
  return response.json().then(data => {
    if (!response.ok) {
      throw new Error(data.error || 'Request failed');
    }
    return data;
  });
}

function joinRoom(slug) {
  if (!socket || !slug) return;
  if (currentRoom && currentRoom !== slug) {
    socket.emit('leave', { room: currentRoom });
  }
  socket.emit('join', { room: slug });
  currentRoom = slug;
}

function renderServingStudent(servingStudent) {
  const infoBlock = document.getElementById('serving-info-block');
  const emptyBlock = document.getElementById('serving-empty-block');
  const indicator = document.getElementById('serving-status-indicator');
  if (!infoBlock || !emptyBlock) return;

  if (servingStudent && servingStudent.token_number) {
    infoBlock.style.display = 'block';
    emptyBlock.style.display = 'none';
    if (indicator) indicator.style.display = 'inline-block';

    const tokEl = document.getElementById('serving-token-number');
    if (tokEl) tokEl.textContent = '#' + servingStudent.token_number;

    const nameEl = document.getElementById('serving-student-name');
    if (nameEl) nameEl.textContent = servingStudent.student_name || 'Student';

    const rollEl = document.getElementById('serving-roll-no');
    if (rollEl) rollEl.textContent = servingStudent.roll_no || servingStudent.student_uid || '—';

    const phoneEl = document.getElementById('serving-phone');
    if (phoneEl) phoneEl.textContent = servingStudent.phone || '—';

    const fatherEl = document.getElementById('serving-father-name');
    if (fatherEl) fatherEl.textContent = servingStudent.father_name || '—';

    const calledEl = document.getElementById('serving-called-at');
    if (calledEl) {
      let dt = servingStudent.called_at;
      if (dt) {
        try {
          const parsed = new Date(dt);
          if (!isNaN(parsed.getTime())) {
            dt = parsed.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
          }
        } catch (_) {}
      }
      calledEl.textContent = dt || 'Just now';
    }
  } else {
    infoBlock.style.display = 'none';
    emptyBlock.style.display = 'block';
    if (indicator) indicator.style.display = 'none';
  }
}

function renderQueue(queueItems) {
  const list = document.getElementById('queue-list');
  if (!list) return;
  list.innerHTML = '';

  if (!queueItems || queueItems.length === 0) {
    const emptyNotice = document.createElement('div');
    emptyNotice.className = 'empty-state-compact';
    emptyNotice.style.margin = '20px auto';
    emptyNotice.style.width = '100%';
    emptyNotice.innerHTML = `
      <span style="font-size:24px; display:block; margin-bottom:6px;">☕</span>
      <p style="margin:0; font-size:13px; color:var(--text-muted);">Queue is currently empty — all students attended.</p>
    `;
    list.appendChild(emptyNotice);
    return;
  }

  queueItems.forEach((item, index) => {
    const card = document.createElement('div');
    card.className = 'queue-card' + (index === 0 ? ' next-in-line' : '');

    const left = document.createElement('div');
    left.style.display = 'flex';
    left.style.alignItems = 'center';
    left.style.gap = '12px';

    const posBadge = document.createElement('span');
    posBadge.className = 'queue-pos-badge';
    posBadge.textContent = index === 0 ? 'NEXT' : `#${index + 1}`;
    left.appendChild(posBadge);

    const tokenNum = document.createElement('div');
    tokenNum.className = 'queue-card-token';
    tokenNum.textContent = '#' + item.token_number;
    left.appendChild(tokenNum);

    const details = document.createElement('div');
    details.className = 'queue-card-details';

    const name = document.createElement('div');
    name.className = 'queue-card-name';
    name.textContent = item.student_name || 'Student';
    details.appendChild(name);

    const meta = document.createElement('div');
    meta.className = 'queue-card-meta';
    const rollPart = item.roll_no ? `Roll: ${item.roll_no}` : '';
    const phonePart = item.phone ? `Ph: ${item.phone}` : '';
    meta.textContent = [rollPart, phonePart].filter(Boolean).join(' • ');
    details.appendChild(meta);

    left.appendChild(details);
    card.appendChild(left);

    const right = document.createElement('div');
    right.className = 'queue-card-right';
    if (item.created_at) {
      const timeSpan = document.createElement('span');
      timeSpan.className = 'queue-card-time';
      try {
        const d = new Date(item.created_at);
        if (!isNaN(d.getTime())) {
          timeSpan.textContent = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        } else {
          timeSpan.textContent = item.created_at;
        }
      } catch (_) {
        timeSpan.textContent = item.created_at;
      }
      right.appendChild(timeSpan);
    }
    card.appendChild(right);

    list.appendChild(card);
  });
}

function updateStatusBadge(status) {
  const badge = document.getElementById('counter-status-badge');
  const sel = document.getElementById('status-select');
  const current = status || 'open';
  if (sel) sel.value = current;
  if (badge) {
    const map = {
      open: '🟢 OPEN',
      paused: '🟡 PAUSED',
      closed: '🔴 CLOSED'
    };
    badge.textContent = map[current] || current.toUpperCase();
    badge.className = `badge-status-pill status-${current}`;
  }

  // Sync quick action buttons state
  ['open', 'paused', 'closed'].forEach(st => {
    const btn = document.getElementById(`btn-status-${st}`);
    if (btn) {
      if (st === current) {
        btn.classList.add('btn-primary');
        btn.classList.remove('btn-outline');
      } else {
        btn.classList.remove('btn-primary');
        btn.classList.add('btn-outline');
      }
    }
  });
}

function loadQueue() {
  const slug = getCounterSlug();
  if (!slug) return;
  fetch(`/api/operator/queue?counter=${encodeURIComponent(slug)}`)
    .then(handleJson)
    .then(data => {
      const curEl = document.getElementById('current-token');
      if (curEl) curEl.textContent = '#' + data.current_token;

      const waitEl = document.getElementById('waiting-count');
      if (waitEl) waitEl.textContent = data.waiting_count;

      const servedEl = document.getElementById('served-today');
      if (servedEl) servedEl.textContent = data.served_today;

      updateStatusBadge(data.counter_status);
      renderServingStudent(data.serving_student);

      lastQueue = data.queue || [];
      renderQueue(lastQueue);
    })
    .catch(err => showError(err.message));
}

function callNext() {
  const slug = getCounterSlug();
  if (!slug) return;
  const formData = new FormData();
  formData.append('counter', slug);
  fetch('/api/operator/call-next', { method: 'POST', body: formData })
    .then(handleJson)
    .then(data => {
      playChime();
      showToast(`Called token #${data.current_token} (${data.student_name || 'Student'})`, 'success');
      loadQueue();
    })
    .catch(err => showError(err.message));
}

function recallToken() {
  const slug = getCounterSlug();
  if (!slug) return;
  const formData = new FormData();
  formData.append('counter', slug);
  fetch('/api/operator/recall', { method: 'POST', body: formData })
    .then(handleJson)
    .then(data => {
      playChime();
      showToast(`🔔 Recalled token #${data.current_token} (${data.student_name || 'Student'})`, 'info');
    })
    .catch(err => showError(err.message));
}

function skipToken() {
  const slug = getCounterSlug();
  if (!slug) return;
  if (!confirm('Skip the next token in queue?')) return;
  const formData = new FormData();
  formData.append('counter', slug);
  fetch('/api/operator/skip', { method: 'POST', body: formData })
    .then(handleJson)
    .then(data => {
      showToast(`Token skipped. Now at token #${data.current_token}`, 'warning');
      loadQueue();
    })
    .catch(err => showError(err.message));
}

function resetQueue() {
  const slug = getCounterSlug();
  if (!slug) return;
  if (!confirm('Reset this queue? All tokens for this counter will be cleared.')) return;
  const formData = new FormData();
  formData.append('counter', slug);
  fetch('/api/operator/reset', { method: 'POST', body: formData })
    .then(handleJson)
    .then(() => {
      showToast('Queue has been reset', 'info');
      loadQueue();
    })
    .catch(err => showError(err.message));
}

function setStatus(newStatus) {
  const slug = getCounterSlug();
  if (!slug) return;
  const formData = new FormData();
  formData.append('counter', slug);
  formData.append('status', newStatus);
  fetch('/api/operator/set-status', { method: 'POST', body: formData })
    .then(handleJson)
    .then(data => {
      updateStatusBadge(data.status);
      showToast(`Counter status changed to ${data.status.toUpperCase()}`, 'info');
      loadQueue();
    })
    .catch(err => showError(err.message));
}

const queueSearch = document.getElementById('queue-search');
if (queueSearch) {
  queueSearch.addEventListener('input', (e) => {
    const term = e.target.value.toLowerCase().trim();
    if (!term) {
      renderQueue(lastQueue);
      return;
    }
    const filtered = lastQueue.filter(item =>
      String(item.token_number).includes(term) ||
      (item.student_name && item.student_name.toLowerCase().includes(term)) ||
      (item.roll_no && item.roll_no.toLowerCase().includes(term)) ||
      (item.phone && item.phone.toLowerCase().includes(term))
    );
    renderQueue(filtered);
  });
}

if (counterSelect) {
  counterSelect.addEventListener('change', () => {
    const slug = getCounterSlug();
    joinRoom(slug);
    loadQueue();
  });
}

if (socket) {
  socket.on('connect', () => {
    const slug = getCounterSlug();
    if (slug) {
      joinRoom(slug);
      loadQueue();
    }
  });

  socket.on('queue_update', (data) => {
    const slug = getCounterSlug();
    if (slug && data.counter_slug === slug) {
      loadQueue();
    }
  });

  socket.on('token_recalled', (data) => {
    const slug = getCounterSlug();
    if (slug && data.counter_slug === slug) {
      playChime();
      showToast(`🔔 Recalling token #${data.current_token} (${data.student_name || 'Student'})`, 'warning');
      loadQueue();
    }
  });
}

// Initial load
document.addEventListener('DOMContentLoaded', () => {
  const slug = getCounterSlug();
  if (slug) {
    joinRoom(slug);
    loadQueue();
  }
});
