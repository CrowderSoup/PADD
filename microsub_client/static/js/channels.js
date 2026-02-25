/**
 * Channel management: inline rename and drag-to-reorder.
 *
 * Requires window.PADD_URLS.channelMarkRead, window.PADD_URLS.channelRename,
 * and window.PADD_URLS.channelOrder
 * to be set before this script runs (injected by the base template).
 */

/**
 * Activates an inline rename input for a channel.
 * Submits via HTMX on Enter or blur; cancels on Escape.
 *
 * @param {HTMLElement} btn - The rename button that was clicked.
 * @param {string} uid - The channel UID.
 * @param {string} currentName - The channel's current display name.
 */
function startChannelRename(btn, uid, currentName) {
  btn.closest('.lcars-channel-actions').classList.remove('lcars-actions-open');

  var wrapper = btn.closest('.lcars-channel-wrapper');
  var nameEl = wrapper.querySelector('.lcars-channel-item .lcars-channel-name');
  var oldText = nameEl.textContent;

  var input = document.createElement('input');
  input.type = 'text';
  input.value = currentName;
  input.className = 'lcars-input lcars-channel-rename-input';

  nameEl.textContent = '';
  nameEl.appendChild(input);
  input.focus();
  input.select();

  function submitRename() {
    var newName = input.value.trim();
    if (newName && newName !== currentName) {
      htmx.ajax('POST', window.PADD_URLS.channelRename, {
        values: { channel: uid, name: newName },
        target: '#channel-nav',
        swap: 'innerHTML',
      });
    } else {
      nameEl.textContent = oldText;
    }
  }

  input.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') { e.preventDefault(); submitRename(); }
    if (e.key === 'Escape') { nameEl.textContent = oldText; }
  });
  input.addEventListener('blur', submitRename);
}

// Refresh visible timeline after successful "Mark as read" channel action.
document.body.addEventListener('htmx:afterRequest', function(evt) {
  var timeline = document.getElementById('timeline');
  if (!timeline) return;
  if (!window.PADD_URLS || evt.detail.pathInfo.requestPath !== window.PADD_URLS.channelMarkRead) return;
  if (!evt.detail.successful) return;

  htmx.ajax('GET', window.location.pathname + window.location.search, {
    target: '#main-content',
    swap: 'innerHTML',
    pushURL: false,
  });
});

// Drag-to-reorder channels
(function() {
  var dragSrc = null;

  document.addEventListener('dragstart', function(e) {
    var wrapper = e.target.closest('.lcars-channel-wrapper');
    if (!wrapper) return;
    dragSrc = wrapper;
    wrapper.classList.add('lcars-dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', wrapper.dataset.channelUid);
  });

  document.addEventListener('dragover', function(e) {
    var wrapper = e.target.closest('.lcars-channel-wrapper');
    if (!wrapper || wrapper === dragSrc) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    var midY = wrapper.getBoundingClientRect().top + wrapper.getBoundingClientRect().height / 2;
    wrapper.classList.toggle('lcars-drag-above', e.clientY < midY);
    wrapper.classList.toggle('lcars-drag-below', e.clientY >= midY);
  });

  document.addEventListener('dragleave', function(e) {
    var wrapper = e.target.closest('.lcars-channel-wrapper');
    if (wrapper) wrapper.classList.remove('lcars-drag-above', 'lcars-drag-below');
  });

  document.addEventListener('drop', function(e) {
    var target = e.target.closest('.lcars-channel-wrapper');
    if (!target || !dragSrc || target === dragSrc) return;
    e.preventDefault();

    var nav = document.getElementById('channel-nav');
    var midY = target.getBoundingClientRect().top + target.getBoundingClientRect().height / 2;
    nav.insertBefore(dragSrc, e.clientY < midY ? target : target.nextSibling);
    target.classList.remove('lcars-drag-above', 'lcars-drag-below');

    var uids = Array.from(nav.querySelectorAll('.lcars-channel-wrapper')).map(function(w) {
      return w.dataset.channelUid;
    });
    htmx.ajax('POST', window.PADD_URLS.channelOrder, {
      values: { 'channels[]': uids },
      target: '#channel-nav',
      swap: 'innerHTML',
    });
  });

  document.addEventListener('dragend', function() {
    if (dragSrc) dragSrc.classList.remove('lcars-dragging');
    document.querySelectorAll('.lcars-drag-above, .lcars-drag-below').forEach(function(el) {
      el.classList.remove('lcars-drag-above', 'lcars-drag-below');
    });
    dragSrc = null;
  });
})();
