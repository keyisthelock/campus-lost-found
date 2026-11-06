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
