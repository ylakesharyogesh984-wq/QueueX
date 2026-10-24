const themeToggle = document.getElementById('theme-toggle');
const savedTheme = localStorage.getItem('queuex-theme') || 'dark';
document.documentElement.setAttribute('data-theme', savedTheme);
themeToggle.textContent = savedTheme === 'dark' ? '🌙' : '☀️';

themeToggle.addEventListener('click', () => {
  const current = document.documentElement.getAttribute('data-theme');
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('queuex-theme', next);
  themeToggle.textContent = next === 'dark' ? '🌙' : '☀️';
});