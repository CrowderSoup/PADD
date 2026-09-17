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

    // Django's default Referrer-Policy header ("same-origin") strips the
    // Referer header the browser would otherwise send on this cross-origin
    // request, and YouTube's player needs it to validate the embedding
    // site — without it playback fails with the undocumented "Error 153".
    // The origin query param alone isn't enough; the iframe's own
    // referrerpolicy attribute overrides the page-wide header for this
    // element's request, which is what actually lets the referrer through.
    var origin = encodeURIComponent(window.location.origin);
    var iframe = document.createElement('iframe');
    iframe.className = 'lcars-entry-video-el';
    iframe.src = 'https://www.youtube-nocookie.com/embed/' + encodeURIComponent(id) +
      '?autoplay=1&origin=' + origin;
    iframe.title = 'YouTube video player';
    iframe.frameBorder = '0';
    iframe.referrerPolicy = 'strict-origin-when-cross-origin';
    iframe.allow = 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share';
    iframe.allowFullscreen = true;

    container.innerHTML = '';
    container.appendChild(iframe);
  });
})();
