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

const step1 = document.getElementById('step-1');
const step2 = document.getElementById('step-2');
const dot1 = document.getElementById('dot-1');
const dot2 = document.getElementById('dot-2');

document.getElementById('next-btn').addEventListener('click', () => {
  const inputs = step1.querySelectorAll('input');
  let valid = true;
  inputs.forEach(inp => { if (!inp.checkValidity()) valid = false; });
  if (!valid) {
    step1.querySelectorAll('input').forEach(inp => inp.reportValidity());
    return;
  }
  step1.classList.remove('active');
  step2.classList.add('active');
  dot1.classList.remove('active');
  dot2.classList.add('active');
});

document.getElementById('back-btn').addEventListener('click', () => {
  step2.classList.remove('active');
  step1.classList.add('active');
  dot2.classList.remove('active');
  dot1.classList.add('active');
});

function selectCounter(el, slug) {
  document.querySelectorAll('.counter-card').forEach(c => c.classList.remove('selected'));
  el.classList.add('selected');
  document.getElementById('selected-counter').value = slug;
  document.getElementById('get-token-btn').disabled = false;
}