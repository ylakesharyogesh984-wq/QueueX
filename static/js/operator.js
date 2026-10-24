const counterSelect = document.getElementById('counter-select');
const socket = io();
let currentRoom = null;
let lastQueue = [];

function showError(message) {
  alert(message || 'Something went wrong. Please try again.');
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
  if (currentRoom) socket.emit('leave', { room: currentRoom });
  socket.emit('join', { room: slug });
  currentRoom = slug;
}

function renderQueue(queueItems) {
  const list = document.getElementById('queue-list');
  list.innerHTML = '';
  queueItems.forEach(item => {
    const chip = document.createElement('div');
    chip.className = 'queue-chip';
    const name = item.student_name ? ' · ' + item.student_name : '';
    chip.textContent = '#' + item.token_number + name;
    list.appendChild(chip);
  });
}

function updateStatusBadge(status) {
  const badge = document.getElementById('counter-status-badge');
  const map = { open: '🟢 OPEN', paused: '🟡 PAUSED', closed: '🔴 CLOSED' };
  badge.textContent = map[status] || status.toUpperCase();
}

function loadQueue() {
  const slug = counterSelect.value;
  fetch(`/api/operator/queue?counter=${slug}`)
    .then(handleJson)
    .then(data => {
      document.getElementById('current-token').textContent = '#' + data.current_token;
      document.getElementById('waiting-count').textContent = data.waiting_count;
      document.getElementById('served-today').textContent = data.served_today;
      updateStatusBadge(data.counter_status);
      lastQueue = data.queue;
      renderQueue(lastQueue);
    })
    .catch(err => showError(err.message));
}

function callNext() {
  const formData = new FormData();
  formData.append('counter', counterSelect.value);
  fetch('/api/operator/call-next', { method: 'POST', body: formData })
    .then(handleJson)
    .then(() => loadQueue())
    .catch(err => showError(err.message));
}

function recallToken() {
  const formData = new FormData();
  formData.append('counter', counterSelect.value);
  fetch('/api/operator/recall', { method: 'POST', body: formData })
    .then(handleJson)
    .catch(err => showError(err.message));
}

function skipToken() {
  if (!confirm('Skip the next token in queue?')) return;
  const formData = new FormData();
  formData.append('counter', counterSelect.value);
  fetch('/api/operator/skip', { method: 'POST', body: formData })
    .then(handleJson)
    .then(() => loadQueue())
    .catch(err => showError(err.message));
}

function resetQueue() {
  if (!confirm('Reset this queue? All tokens for this counter will be deleted.')) return;
  const formData = new FormData();
  formData.append('counter', counterSelect.value);
  fetch('/api/operator/reset', { method: 'POST', body: formData })
    .then(handleJson)
    .then(() => loadQueue())
    .catch(err => showError(err.message));
}

function setStatus(newStatus) {
  const formData = new FormData();
  formData.append('counter', counterSelect.value);
  formData.append('status', newStatus);
  fetch('/api/operator/set-status', { method: 'POST', body: formData })
    .then(handleJson)
    .then(data => updateStatusBadge(data.status))
    .catch(err => showError(err.message));
}

document.getElementById('queue-search').addEventListener('input', (e) => {
  const term = e.target.value.toLowerCase();
  const filtered = lastQueue.filter(item =>
    String(item.token_number).includes(term) ||
    (item.student_name && item.student_name.toLowerCase().includes(term))
  );
  renderQueue(filtered);
});

counterSelect.addEventListener('change', () => {
  joinRoom(counterSelect.value);
  loadQueue();
});

socket.on('connect', () => {
  joinRoom(counterSelect.value);
  loadQueue();
});

socket.on('queue_update', (data) => {
  if (data.counter_slug === counterSelect.value) loadQueue();
});

socket.on('token_recalled', (data) => {
  if (data.counter_slug === counterSelect.value) {
    alert('🔔 Recalling token #' + data.current_token);
  }
});