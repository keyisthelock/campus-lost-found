document.querySelector('.nav-toggle')?.addEventListener('click', function () {
  const expanded = this.getAttribute('aria-expanded') !== 'true';
  this.setAttribute('aria-expanded', String(expanded));
  document.getElementById('main-nav').classList.toggle('is-open', expanded);
});
document.getElementById('image')?.addEventListener('change', function () {
  const image = document.getElementById('image-preview');
  if (image.dataset.url) URL.revokeObjectURL(image.dataset.url);
  const file = this.files[0];
  image.hidden = !file;
  if (file) {
    image.dataset.url = URL.createObjectURL(file);
    image.src = image.dataset.url;
  }
});
document.querySelectorAll('form[method="post"]').forEach(form => {
  form.addEventListener('submit', event => {
    if (form.dataset.submitting) { event.preventDefault(); return; }
    form.dataset.submitting = 'true';
    if (event.submitter) {
      event.submitter.setAttribute('aria-busy', 'true');
      event.submitter.textContent = 'Working…';
    }
  });
});

// Credential visibility never persists or sends the token anywhere.
const tokenInput = document.getElementById('token');
const tokenToggle = document.querySelector('.secret-toggle');
function hideToken() {
  if (!tokenInput || !tokenToggle) return;
  tokenInput.type = 'password';
  tokenToggle.textContent = 'Show';
  tokenToggle.setAttribute('aria-pressed', 'false');
}
tokenToggle?.addEventListener('click', () => {
  const reveal = tokenInput.type === 'password';
  tokenInput.type = reveal ? 'text' : 'password';
  tokenToggle.textContent = reveal ? 'Hide' : 'Show';
  tokenToggle.setAttribute('aria-pressed', String(reveal));
});
tokenInput?.form.addEventListener('reset', hideToken);
window.addEventListener('pageshow', () => {
  hideToken();
  if (tokenInput) tokenInput.value = '';
});

// PhishGuard-inspired staggered scroll reveals, without a motion dependency.
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
if (!reducedMotion.matches && 'IntersectionObserver' in window) {
  const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      const element = entry.target;
      const index = Array.from(element.parentElement.children).indexOf(element);
      const animation = element.animate([
        { opacity: 0, transform: 'translateY(24px)' },
        { opacity: 1, transform: 'translateY(0)' }
      ], { duration: 680, delay: Math.min(index % 4, 3) * 75, easing: 'cubic-bezier(.22,1,.36,1)', fill: 'backwards' });
      const cancel = event => { if (event.matches) animation.cancel(); };
      reducedMotion.addEventListener('change', cancel);
      animation.finished.catch(() => {}).finally(() => reducedMotion.removeEventListener('change', cancel));
      observer.unobserve(element);
    });
  }, { threshold: .08 });
  document.querySelectorAll('.stat-card, .item-card, .how-it-works > div, .analytics-grid > .panel, .claim-list > .panel, .credentials-panel, .integration-guidance > section').forEach(element => observer.observe(element));
  const art = document.querySelector('.hero-illustration');
  if (art && matchMedia('(hover: hover) and (pointer: fine)').matches) {
    let frame;
    let movement;
    function moveArt(x, y) {
      const current = getComputedStyle(art).translate;
      if (movement) movement.cancel();
      movement = art.animate([{ translate: current === 'none' ? '0px 0px' : current }, { translate: `${x}px ${y}px` }], { duration: 800, fill: 'forwards', easing: 'cubic-bezier(.22,1,.36,1)' });
    }
    art.addEventListener('pointermove', event => {
      if (reducedMotion.matches) return;
      cancelAnimationFrame(frame);
      const bounds = art.getBoundingClientRect();
      const x = (event.clientX - bounds.left - bounds.width / 2) * .025;
      const y = (event.clientY - bounds.top - bounds.height / 2) * .025;
      frame = requestAnimationFrame(() => moveArt(x, y));
    });
    art.addEventListener('pointerleave', () => { cancelAnimationFrame(frame); moveArt(0, 0); });
    reducedMotion.addEventListener('change', event => { if (event.matches && movement) movement.cancel(); });
  }
}
