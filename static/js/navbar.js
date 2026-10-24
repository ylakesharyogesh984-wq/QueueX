// Mobile Navigation Burger Menu Handler for QueueX
(function() {
  function initNavbar() {
    const navbar = document.querySelector('.navbar');
    if (!navbar) return;

    const burgerBtn = navbar.querySelector('.burger-btn');
    const navLinks = navbar.querySelector('.nav-links');
    const backdrop = document.getElementById('nav-backdrop') || createBackdrop();

    if (!burgerBtn || !navLinks) return;

    function openMenu() {
      burgerBtn.classList.add('active');
      burgerBtn.setAttribute('aria-expanded', 'true');
      navLinks.classList.add('open');
      if (backdrop) backdrop.classList.add('open');
      document.body.classList.add('nav-menu-open');
    }

    function closeMenu() {
      burgerBtn.classList.remove('active');
      burgerBtn.setAttribute('aria-expanded', 'false');
      navLinks.classList.remove('open');
      if (backdrop) backdrop.classList.remove('open');
      document.body.classList.remove('nav-menu-open');
    }

    function toggleMenu() {
      const isOpen = navLinks.classList.contains('open');
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

    // Close when clicking outside navbar
    document.addEventListener('click', (e) => {
      if (!navbar.contains(e.target) && navLinks.classList.contains('open')) {
        closeMenu();
      }
    });

    // Close when clicking any link/button inside navLinks
    navLinks.addEventListener('click', (e) => {
      const target = e.target.closest('a, button');
      if (target && target.id !== 'theme-toggle') {
        closeMenu();
      }
    });

    // Close on Escape key
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && navLinks.classList.contains('open')) {
        closeMenu();
        burgerBtn.focus();
      }
    });

    // Close on resize to desktop view
    window.addEventListener('resize', () => {
      if (window.innerWidth > 768 && navLinks.classList.contains('open')) {
        closeMenu();
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initNavbar);
  } else {
    initNavbar();
  }
})();
