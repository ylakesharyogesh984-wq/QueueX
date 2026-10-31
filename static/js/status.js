// QueueX Live Student Pass Controller
const counterSlugEl = document.getElementById('data-counter');
const tokenEl = document.getElementById('data-token');
const counterSlug = counterSlugEl ? counterSlugEl.value : '';
const token = tokenEl ? tokenEl.value : '';

let previousAhead = null;

// Sound synthesizer
function playAlertChime() {
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();

    osc.type = 'triangle';
    osc.frequency.setValueAtTime(523.25, ctx.currentTime); // C5
    osc.frequency.exponentialRampToValueAtTime(783.99, ctx.currentTime + 0.18); // G5

    gain.gain.setValueAtTime(0.3, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.7);

    osc.connect(gain);
    gain.connect(ctx.destination);

    osc.start();
    osc.stop(ctx.currentTime + 0.75);
  } catch (e) {
    // browser auto-play policy
  }
}

// QR Code generation with error protection
const qrContainer = document.getElementById('qr-code');
if (qrContainer && typeof QRCode !== 'undefined') {
  try {
    new QRCode(qrContainer, {
      text: window.location.href,
      width: 140,
      height: 140,
      colorDark: '#0B0F19',
      colorLight: '#FFFFFF',
      correctLevel: QRCode.CorrectLevel.M
    });
  } catch (err) {
    console.error('QR Code render warning:', err);
  }
}

function updateUI(data) {
  const servingEl = document.getElementById('currently-serving');
  const aheadEl = document.getElementById('people-ahead');
  const waitEl = document.getElementById('estimated-wait');
  const badge = document.getElementById('status-badge');
  const alertEl = document.getElementById('almost-turn');

  if (servingEl) servingEl.textContent = '#' + data.currently_serving;
  if (aheadEl) aheadEl.textContent = data.people_ahead;
  if (waitEl) waitEl.textContent = data.estimated_wait + 'm';

  if (badge) {
    if (data.status === 'served') {
      badge.textContent = 'Served ✓';
      badge.className = 'badge badge-served';
    } else if (data.status === 'skipped') {
      badge.textContent = 'Skipped';
      badge.className = 'badge badge-skipped';
    } else if (data.status === 'cancelled') {
      badge.textContent = 'Cancelled';
      badge.className = 'badge badge-skipped';
    } else {
      badge.textContent = 'Waiting in Line';
      badge.className = 'badge badge-waiting';
    }
  }

  const isAlmost = data.people_ahead <= 2 && data.status === 'waiting';
  if (alertEl) {
    alertEl.style.display = isAlmost ? 'block' : 'none';
  }

  // Chime if we just moved into the top 2
  if (previousAhead !== null && previousAhead > 2 && data.people_ahead <= 2 && data.status === 'waiting') {
    playAlertChime();
  }
  previousAhead = data.people_ahead;
}

function fetchStatus() {
  if (!counterSlug || !token) return;
  fetch(`/api/status?counter=${encodeURIComponent(counterSlug)}&token=${encodeURIComponent(token)}`)
    .then(res => res.json())
    .then(updateUI)
    .catch(console.error);
}

fetchStatus();

// Polling interval
setInterval(fetchStatus, 7000);

if (typeof io !== 'undefined') {
  const socket = io();
  socket.on('connect', () => {
    socket.emit('join', { room: counterSlug });
  });
  socket.on('queue_update', () => {
    fetchStatus();
  });
  socket.on('token_recalled', (data) => {
    if (String(data.current_token) === String(token)) {
      playAlertChime();
      alert(`🔔 Reminder: Your token #${token} is being recalled at the counter!`);
    }
  });
}
