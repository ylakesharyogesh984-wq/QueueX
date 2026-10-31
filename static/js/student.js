// Student Token Selection & Submission Handler for QueueX
function selectCounter(el, slug) {
  document.querySelectorAll('.counter-card, .counter-card-rich').forEach(c => {
    c.classList.remove('selected');
  });
  if (el) {
    el.classList.add('selected');
  }
  const counterInput = document.getElementById('selected-counter');
  if (counterInput) {
    counterInput.value = slug;
  }
  const tokenBtn = document.getElementById('get-token-btn');
  if (tokenBtn) {
    tokenBtn.disabled = false;
    tokenBtn.classList.add('ready');
    tokenBtn.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('token-form');
  if (form) {
    form.addEventListener('submit', (e) => {
      const counterInput = document.getElementById('selected-counter');
      if (!counterInput || !counterInput.value) {
        e.preventDefault();
        alert('Please tap on a campus counter station before issuing your pass.');
        return false;
      }
      const tokenBtn = document.getElementById('get-token-btn');
      if (tokenBtn) {
        tokenBtn.disabled = true;
        tokenBtn.textContent = '⚡ Allocating Live Pass...';
      }
    });
  }
});
