const savedTheme = localStorage.getItem('queuex-theme') || 'dark';
document.documentElement.setAttribute('data-theme', savedTheme);
const themeToggle = document.getElementById('theme-toggle');
themeToggle.textContent = savedTheme === 'dark' ? '🌙' : '☀️';
themeToggle.addEventListener('click', () => {
  const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('queuex-theme', next);
  themeToggle.textContent = next === 'dark' ? '🌙' : '☀️';
});

const counterSlug = document.getElementById('data-counter').value;
const token = document.getElementById('data-token').value;

new QRCode(document.getElementById('qr-code'), {
  text: window.location.href,
  width: 140,
  height: 140
});

function updateUI(data) {
  document.getElementById('currently-serving').textContent = '#' + data.currently_serving;
  document.getElementById('people-ahead').textContent = data.people_ahead;
  document.getElementById('estimated-wait').textContent = data.estimated_wait + 'm';

  const badge = document.getElementById('status-badge');
  if (data.status === 'served') {
    badge.textContent = 'Served';
    badge.className = 'badge badge-served';
  } else {
    badge.textContent = 'Waiting';
    badge.className = 'badge badge-waiting';
  }

  document.getElementById('almost-turn').style.display =
    (data.people_ahead <= 2 && data.status !== 'served') ? 'block' : 'none';
}

function fetchStatus() {
  fetch(`/api/status?counter=${counterSlug}&token=${token}`)
    .then(res => res.json())
    .then(updateUI);
}

fetchStatus();

const socket = io();
socket.on('connect', () => {
  socket.emit('join', { room: counterSlug });
});
socket.on('queue_update', () => {
  fetchStatus();
});
