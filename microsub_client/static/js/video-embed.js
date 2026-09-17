(function () {
  // Swap the thumbnail facade for a live YouTube iframe on click, so
  // timeline entries don't load an iframe per video up front.
  document.body.addEventListener('click', function (e) {
    var btn = e.target.closest('.lcars-video-play-btn');
    if (!btn) return;
    var container = btn.closest('.lcars-yt-facade');
    if (!container) return;
    var id = container.dataset.ytId;
    if (!id) return;

    // YouTube's player validates the embedding origin itself when the
    // Referrer-Policy header (Django defaults to "same-origin") keeps the
    // browser from sending a referrer to this cross-origin iframe. Without
    // either one, playback fails with the undocumented "Error 153".
    var origin = encodeURIComponent(window.location.origin);
    var iframe = document.createElement('iframe');
    iframe.className = 'lcars-entry-video-el';
    iframe.src = 'https://www.youtube-nocookie.com/embed/' + encodeURIComponent(id) +
      '?autoplay=1&origin=' + origin;
    iframe.title = 'YouTube video player';
    iframe.frameBorder = '0';
    iframe.allow = 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share';
    iframe.allowFullscreen = true;

    container.innerHTML = '';
    container.appendChild(iframe);
  });
})();
