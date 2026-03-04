(function () {
  // Build the lightbox DOM once and append to body.
  var lb = document.createElement('div');
  lb.id = 'lcars-lightbox';
  lb.setAttribute('role', 'dialog');
  lb.setAttribute('aria-modal', 'true');
  lb.setAttribute('aria-label', 'Photo viewer');
  lb.innerHTML =
    '<div class="lcars-lightbox-backdrop"></div>' +
    '<div class="lcars-lightbox-inner">' +
    '  <button class="lcars-lightbox-prev" aria-label="Previous photo">&#8249;</button>' +
    '  <img class="lcars-lightbox-img" src="" alt="">' +
    '  <button class="lcars-lightbox-next" aria-label="Next photo">&#8250;</button>' +
    '</div>' +
    '<button class="lcars-lightbox-close" aria-label="Close">&times;</button>' +
    '<div class="lcars-lightbox-counter"></div>';
  document.body.appendChild(lb);

  var imgs = [];
  var idx = 0;

  function show(newIdx) {
    idx = newIdx;
    lb.querySelector('.lcars-lightbox-img').src = imgs[idx];
    lb.querySelector('.lcars-lightbox-prev').hidden = idx === 0;
    lb.querySelector('.lcars-lightbox-next').hidden = idx === imgs.length - 1;
    var counter = lb.querySelector('.lcars-lightbox-counter');
    counter.textContent = imgs.length > 1 ? (idx + 1) + ' / ' + imgs.length : '';
  }

  function open(container, startIdx) {
    imgs = Array.from(container.querySelectorAll('.lcars-entry-photo')).map(function (img) {
      return img.src;
    });
    if (!imgs.length) return;
    lb.classList.add('lcars-lightbox-open');
    document.body.classList.add('lcars-modal-open');
    show(startIdx);
    lb.querySelector('.lcars-lightbox-close').focus();
  }

  function close() {
    lb.classList.remove('lcars-lightbox-open');
    document.body.classList.remove('lcars-modal-open');
    // Clear src after transition so previous image doesn't flash on next open
    setTimeout(function () {
      lb.querySelector('.lcars-lightbox-img').src = '';
    }, 150);
  }

  // Open on photo button click (works for HTMX-loaded content via delegation)
  document.body.addEventListener('click', function (e) {
    var btn = e.target.closest('.lcars-photo-btn');
    if (!btn) return;
    var container = btn.closest('.lcars-entry-photos');
    open(container, parseInt(btn.dataset.index, 10) || 0);
  });

  lb.querySelector('.lcars-lightbox-close').addEventListener('click', close);
  lb.querySelector('.lcars-lightbox-backdrop').addEventListener('click', close);

  lb.querySelector('.lcars-lightbox-prev').addEventListener('click', function () {
    if (idx > 0) show(idx - 1);
  });

  lb.querySelector('.lcars-lightbox-next').addEventListener('click', function () {
    if (idx < imgs.length - 1) show(idx + 1);
  });

  document.addEventListener('keydown', function (e) {
    if (!lb.classList.contains('lcars-lightbox-open')) return;
    if (e.key === 'Escape') close();
    if (e.key === 'ArrowLeft' && idx > 0) show(idx - 1);
    if (e.key === 'ArrowRight' && idx < imgs.length - 1) show(idx + 1);
  });
})();
