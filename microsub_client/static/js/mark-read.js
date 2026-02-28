var _markReadQueue = { entries: [], channel: null, url: null, timer: null };

function _getCsrfToken() {
  var hxHeaders = document.body.getAttribute('hx-headers');
  if (hxHeaders) {
    try { return JSON.parse(hxHeaders)['X-CSRFToken']; } catch (e) {}
  }
  return '';
}

function _flushMarkReadQueue() {
  var q = _markReadQueue;
  if (!q.entries.length || !q.url) return;

  var entries = q.entries.slice();
  var channel = q.channel;
  var url = q.url;
  q.entries = [];
  q.timer = null;

  var fd = new FormData();
  fd.append('channel', channel);
  entries.forEach(function(eid) { fd.append('entry[]', eid); });

  fetch(url, {
    method: 'POST',
    body: fd,
    headers: { 'X-CSRFToken': _getCsrfToken() },
  }).then(function(resp) {
    return resp.text();
  }).then(function(html) {
    entries.forEach(function(eid) {
      var el = document.querySelector('[data-entry-read="' + CSS.escape(eid) + '"]');
      if (el) el.innerHTML = '<span class="lcars-read-status lcars-read">Read</span>';
    });
    // Process OOB swaps (channel nav unread count update)
    var tmp = document.createElement('div');
    tmp.innerHTML = html;
    tmp.querySelectorAll('[hx-swap-oob]').forEach(function(oob) {
      document.body.appendChild(oob);
      htmx.process(oob);
    });
  });
}

/**
 * Attaches mark-as-read behavior to the timeline based on its data-mark-read-behavior attribute.
 * - "scroll_past": marks entries read when scrolled past using IntersectionObserver
 * - "interaction": marks entries read when a micropub interaction (like/repost/reply) succeeds
 *
 * Safe to call multiple times on htmx:afterSwap — only attaches to new entries.
 *
 * @param {Document|HTMLElement} root
 */
function initMarkReadBehavior(root) {
  var timeline = (root.querySelector && root.querySelector('#timeline')) || document.getElementById('timeline');
  if (!timeline) return;

  if (timeline.dataset.markReadBehavior === 'scroll_past') {
    var observer = new IntersectionObserver(function(entries) {
      entries.forEach(function(ioEntry) {
        if (!ioEntry.isIntersecting && ioEntry.boundingClientRect.top < 0) {
          var el = ioEntry.target;
          observer.unobserve(el);
          _markReadQueue.channel = el.dataset.channel;
          _markReadQueue.url = el.dataset.markReadUrl;
          _markReadQueue.entries.push(el.dataset.entry);
          if (_markReadQueue.timer) clearTimeout(_markReadQueue.timer);
          _markReadQueue.timer = setTimeout(_flushMarkReadQueue, 500);
        }
      });
    }, { threshold: 0 });

    timeline.querySelectorAll('.lcars-entry-read-action').forEach(function(el) {
      observer.observe(el);
    });
  }
}

// Mark entries read on successful micropub interactions when behavior is "interaction"
document.addEventListener('htmx:afterRequest', function(evt) {
  var timeline = document.getElementById('timeline');
  if (!timeline || timeline.dataset.markReadBehavior !== 'interaction') return;

  var path = evt.detail.pathInfo.requestPath;
  if (path.match(/\/api\/micropub\/(like|repost|reply)\//) && evt.detail.successful) {
    var article = evt.detail.elt.closest('.lcars-entry');
    if (!article) return;
    var readAction = article.querySelector('.lcars-entry-read-action');
    if (readAction) {
      _markReadQueue.channel = readAction.dataset.channel;
      _markReadQueue.url = readAction.dataset.markReadUrl;
      _markReadQueue.entries.push(readAction.dataset.entry);
      if (_markReadQueue.timer) clearTimeout(_markReadQueue.timer);
      _markReadQueue.timer = setTimeout(_flushMarkReadQueue, 0);
    }
  }
});
