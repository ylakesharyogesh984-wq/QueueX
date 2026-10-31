// Mobile Navigation Burger Menu, Theme Handler & Dashboard Sidebar Controller for QueueX
(function() {
  // Global CSRF fetch interceptor
  if (typeof window !== 'undefined' && window.fetch) {
    const _originalFetch = window.fetch;
    window.fetch = function(url, options = {}) {
      const method = (options.method || 'GET').toUpperCase();
      if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
        const token = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
        if (token) {
          if (!options.headers) {
            options.headers = {};
          }
          if (options.headers instanceof Headers) {
            if (!options.headers.has('X-CSRFToken')) {
              options.headers.set('X-CSRFToken', token);
            }
          } else if (Array.isArray(options.headers)) {
            options.headers.push(['X-CSRFToken', token]);
          } else {
            if (!options.headers['X-CSRFToken']) {
              options.headers['X-CSRFToken'] = token;
            }
          }
        }
      }
      return _originalFetch.call(this, url, options);
    };
  }

  // Theme initialization
  function initTheme() {
    const savedTheme = localStorage.getItem('queuex-theme') || 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle && !themeToggle.dataset.themeBound) {
      themeToggle.dataset.themeBound = 'true';
      themeToggle.textContent = savedTheme === 'dark' ? '🌙' : '☀️';
      themeToggle.addEventListener('click', () => {
        const current = document.documentElement.getAttribute('data-theme') || 'dark';
        const next = current === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem('queuex-theme', next);
        themeToggle.textContent = next === 'dark' ? '🌙' : '☀️';

        // Trigger chart theme re-renders if charts exist
        if (typeof counterChart !== 'undefined' && counterChart) {
          const gridColor = next === 'light' ? 'rgba(0, 0, 0, 0.06)' : 'rgba(255, 255, 255, 0.08)';
          const textColor = next === 'light' ? '#475569' : '#94A3B8';
          counterChart.options.scales.x.ticks.color = textColor;
          counterChart.options.scales.y.ticks.color = textColor;
          counterChart.options.scales.y.grid.color = gridColor;
          counterChart.update();
        }
        if (typeof peakChart !== 'undefined' && peakChart) {
          const gridColor = next === 'light' ? 'rgba(0, 0, 0, 0.06)' : 'rgba(255, 255, 255, 0.08)';
          const textColor = next === 'light' ? '#475569' : '#94A3B8';
          peakChart.options.scales.x.ticks.color = textColor;
          peakChart.options.scales.y.ticks.color = textColor;
          peakChart.options.scales.y.grid.color = gridColor;
          peakChart.update();
        }
      });
    }
  }

  function initNavbar() {
    initTheme();

    const navbar = document.querySelector('.navbar');
    if (!navbar) return;

    const burgerBtn = navbar.querySelector('.burger-btn');
    const navLinks = navbar.querySelector('.nav-links');
    const sidebar = document.querySelector('.dashboard-sidebar');
    const backdrop = document.getElementById('nav-backdrop') || createBackdrop();

    if (!burgerBtn || !navLinks) return;

    function openMenu() {
      burgerBtn.classList.add('active');
      burgerBtn.setAttribute('aria-expanded', 'true');
      navLinks.classList.add('open');
      if (sidebar) sidebar.classList.add('open');
      if (backdrop) backdrop.classList.add('open');
      document.body.classList.add('nav-menu-open');
    }

    function closeMenu() {
      burgerBtn.classList.remove('active');
      burgerBtn.setAttribute('aria-expanded', 'false');
      navLinks.classList.remove('open');
      if (sidebar) sidebar.classList.remove('open');
      if (backdrop) backdrop.classList.remove('open');
      document.body.classList.remove('nav-menu-open');
    }

    function toggleMenu() {
      const isOpen = navLinks.classList.contains('open') || (sidebar && sidebar.classList.contains('open'));
      if (isOpen) {
        closeMenu();
      } else {
        openMenu();
      }
    }

    function createBackdrop() {
      let bd = document.querySelector('.nav-backdrop');
      if (!bd) {
        bd = document.createElement('div');
        bd.className = 'nav-backdrop';
        bd.id = 'nav-backdrop';
        document.body.appendChild(bd);
      }
      return bd;
    }

    burgerBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      toggleMenu();
    });

    if (backdrop) {
      backdrop.addEventListener('click', closeMenu);
    }

    // Close when clicking outside navbar & sidebar
    document.addEventListener('click', (e) => {
      const clickedInsideNav = navbar.contains(e.target);
      const clickedInsideSidebar = sidebar && sidebar.contains(e.target);
      if (!clickedInsideNav && !clickedInsideSidebar && (navLinks.classList.contains('open') || (sidebar && sidebar.classList.contains('open')))) {
        closeMenu();
      }
    });

    // Close when clicking any link/button inside navLinks or sidebar
    navLinks.addEventListener('click', (e) => {
      const target = e.target.closest('a, button');
      if (target && target.id !== 'theme-toggle') {
        closeMenu();
      }
    });

    if (sidebar) {
      sidebar.addEventListener('click', (e) => {
        const target = e.target.closest('a');
        if (target) {
          closeMenu();
        }
      });
    }

    // Close on Escape key
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && (navLinks.classList.contains('open') || (sidebar && sidebar.classList.contains('open')))) {
        closeMenu();
        burgerBtn.focus();
      }
    });

    // Close on resize to desktop view
    window.addEventListener('resize', () => {
      if (window.innerWidth > 960 && (navLinks.classList.contains('open') || (sidebar && sidebar.classList.contains('open')))) {
        closeMenu();
      }
    });
  }

  initTheme();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initNavbar);
  } else {
    initNavbar();
  }
})();
