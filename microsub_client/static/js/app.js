/**
 * PADD application bootstrap.
 *
 * Wires up UI behaviors that need to run on page load and after every HTMX swap:
 * collapsible content, entry maps, mark-read behavior, sidebar, and dropdowns.
 *
 * Depends on: editor.js, maps.js, mark-read.js (loaded before this file).
 */

/**
 * Toggles the reply editor for an entry. Creates the EasyMDE instance on first open.
 *
 * @param {HTMLElement} btn - The reply toggle button.
 */
function toggleReplyEditor(btn) {
  var form = btn.closest('.lcars-entry-content').querySelector('.lcars-reply-form');
  form.classList.toggle('lcars-hidden');

  if (!form.classList.contains('lcars-hidden') && !form._easymde) {
    form._easymde = createLcarsEditor(form.querySelector('textarea[name=content]'), {
      placeholder: 'Write a reply...',
      minHeight: '120px',
    });
    form._easymde.codemirror.focus();
  } else if (form._easymde && !form.classList.contains('lcars-hidden')) {
    form._easymde.codemirror.refresh();
    form._easymde.codemirror.focus();
  }
}

/**
 * Injects the EasyMDE editor value into the HTMX request parameters.
 *
 * @param {HTMLFormElement} form - The reply form element.
 * @param {CustomEvent} event - The htmx:configRequest event.
 */
function replyFormConfigRequest(form, event) {
  if (form._easymde) {
    event.detail.parameters.content = form._easymde.value();
  }
}

/**
 * Guards against submitting an empty reply; adds error styling if blank.
 *
 * @param {HTMLFormElement} form - The reply form element.
 * @param {CustomEvent} event - The htmx:beforeRequest event.
 */
function replyFormBeforeRequest(form, event) {
  form.classList.remove('lcars-reply-error');
  var content = event.detail.requestConfig.parameters.content;
  if (!content || !content.trim()) {
    event.preventDefault();
    form.classList.add('lcars-reply-error');
  }
}

/**
 * Handles the reply form response: updates the UI on success or shows an
 * inline error message on failure.
 *
 * @param {HTMLFormElement} form - The reply form element.
 * @param {CustomEvent} event - The htmx:afterRequest event.
 */
function replyFormAfterRequest(form, event) {
  if (event.detail.successful) {
    var c = form.closest('.lcars-entry-content');
    var t = document.createElement('div');
    t.innerHTML = event.detail.xhr.responseText;
    var btn = t.querySelector('[data-reply-button]');
    var sent = t.querySelector('[data-reply-sent]');
    if (!btn || !sent) {
      var err = form.querySelector('.lcars-reply-error-msg');
      if (!err) {
        err = document.createElement('div');
        err.className = 'lcars-reply-error-msg';
        form.insertBefore(err, form.querySelector('button[type=submit]'));
      }
      err.textContent = 'Something went wrong';
      return;
    }
    c.querySelector('.lcars-reply-wrapper').innerHTML = btn.innerHTML;
    c.querySelector('.lcars-interactions').insertAdjacentHTML('afterend', sent.innerHTML);
    form.remove();
  } else {
    var err = form.querySelector('.lcars-reply-error-msg');
    if (!err) {
      err = document.createElement('div');
      err.className = 'lcars-reply-error-msg';
      form.insertBefore(err, form.querySelector('button[type=submit]'));
    }
    err.textContent = event.detail.xhr.responseText || 'Something went wrong';
  }
}

var COLLAPSIBLE_PREVIEW_HEIGHT = 200;

function syncCollapsibleButton(el) {
  var btn = el.querySelector('.lcars-expand-btn');
  if (!btn) return;
  var expanded = el.classList.contains('lcars-expanded');
  btn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
  btn.textContent = expanded ? 'Collapse' : 'Expand';
}

function clearCollapsibleTransition(inner) {
  if (inner._collapseTransitionHandler) {
    inner.removeEventListener('transitionend', inner._collapseTransitionHandler);
    inner._collapseTransitionHandler = null;
  }
}

function setCollapsibleExpanded(el, expanded, immediate) {
  var inner = el.querySelector('.lcars-entry-collapse-inner');
  if (!inner) return;

  var reduceMotion = window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var skipAnimation = immediate || reduceMotion;

  clearCollapsibleTransition(inner);

  if (skipAnimation) {
    el.classList.toggle('lcars-expanded', expanded);
    inner.style.maxHeight = expanded ? 'none' : COLLAPSIBLE_PREVIEW_HEIGHT + 'px';
    syncCollapsibleButton(el);
    return;
  }

  var currentHeight = inner.getBoundingClientRect().height;
  inner.style.maxHeight = currentHeight + 'px';
  inner.offsetHeight;

  el.classList.toggle('lcars-expanded', expanded);
  syncCollapsibleButton(el);

  if (expanded) {
    inner.style.maxHeight = inner.scrollHeight + 'px';
    inner._collapseTransitionHandler = function(event) {
      if (event.target !== inner || event.propertyName !== 'max-height') return;
      clearCollapsibleTransition(inner);
      if (el.classList.contains('lcars-expanded')) {
        inner.style.maxHeight = 'none';
      }
    };
    inner.addEventListener('transitionend', inner._collapseTransitionHandler);
    return;
  }

  inner.style.maxHeight = COLLAPSIBLE_PREVIEW_HEIGHT + 'px';
}

/**
 * Auto-expands collapsible entry content that is already short enough to show in full
 * and initializes the button state for longer entries. Safe to call multiple times.
 *
 * @param {Document|HTMLElement} root
 */
function initCollapsibles(root) {
  var collapsibles = [];
  if (root.matches && root.matches('.lcars-entry-collapsible:not([data-init])')) {
    collapsibles.push(root);
  }
  root.querySelectorAll('.lcars-entry-collapsible:not([data-init])').forEach(function(el) {
    collapsibles.push(el);
  });

  collapsibles.forEach(function(el) {
    el.dataset.init = '1';
    var inner = el.querySelector('.lcars-entry-collapse-inner');
    var btn = el.querySelector('.lcars-expand-btn');
    if (!inner || !btn) return;

    if (inner.scrollHeight <= COLLAPSIBLE_PREVIEW_HEIGHT) {
      el.classList.add('lcars-expanded');
      inner.style.maxHeight = 'none';
      btn.hidden = true;
      btn.setAttribute('aria-hidden', 'true');
      return;
    }

    btn.hidden = false;
    btn.removeAttribute('aria-hidden');
    setCollapsibleExpanded(el, el.classList.contains('lcars-expanded'), true);
  });
}

// --- Boot ---

initCollapsibles(document);
initEntryMaps(document);
initMarkReadBehavior(document);

function adjustAlertsPreviewPosition() {
  var panel = document.getElementById('header-notifications-preview');
  if (!panel || panel.classList.contains('lcars-hidden')) return;
  panel.style.transform = 'translateX(0)';
  var rect = panel.getBoundingClientRect();
  var gutter = 8;
  var shift = 0;
  if (rect.left < gutter) {
    shift = gutter - rect.left;
  } else if (rect.right > window.innerWidth - gutter) {
    shift = (window.innerWidth - gutter) - rect.right;
  }
  if (shift !== 0) {
    panel.style.transform = 'translateX(' + shift + 'px)';
  }
}

document.body.addEventListener('htmx:afterSwap', function(e) {
  initCollapsibles(e.target);
  initEntryMaps(e.target);
  initMarkReadBehavior(e.target);

  // If header controls get swapped, force alerts preview to lazy-load again.
  if (e.target.id === 'header-notifications-button') {
    var wrap = document.getElementById('header-notifications-wrap');
    var panel = document.getElementById('header-notifications-preview');
    if (wrap && panel) {
      wrap.classList.remove('lcars-notifications-open');
      panel.classList.add('lcars-hidden');
      panel.dataset.loaded = '0';
    }
  }

  if (e.target.id === 'main-content') {
    var alertsWrap = document.getElementById('header-notifications-wrap');
    var alertsPanel = document.getElementById('header-notifications-preview');
    if (alertsWrap && alertsPanel) {
      alertsWrap.classList.remove('lcars-notifications-open');
      alertsPanel.classList.add('lcars-hidden');
    }
  }

  if (e.target.id === 'header-notifications-preview') {
    adjustAlertsPreviewPosition();
  }

  // Infinite scroll swaps stale the notifications panel — reset it so it reloads on next open.
  if (e.target.classList.contains('lcars-load-more-sentinel') || e.target.classList.contains('lcars-load-more')) {
    var scrollPanel = document.getElementById('header-notifications-preview');
    if (scrollPanel) scrollPanel.dataset.loaded = '0';
  }

  // Close mobile sidebar after navigating to a channel, but not when
  // opening the feed panel (which lives inside the sidebar itself).
  if (e.target.id !== 'feed-panel' && e.target.id !== 'feed-current-list' && e.target.id !== 'feed-search-results') {
    var sidebar = document.getElementById('channel-sidebar');
    if (sidebar) sidebar.classList.remove('lcars-sidebar-open');
  }
});

// Close user dropdown when clicking outside of it
document.addEventListener('click', function(e) {
  document.querySelectorAll('.lcars-user-menu-open').forEach(function(menu) {
    if (!menu.contains(e.target)) menu.classList.remove('lcars-user-menu-open');
  });
});

document.addEventListener('pointerdown', function(e) {
  var btn = e.target.closest('.lcars-expand-btn[data-collapsible-toggle]');
  if (btn) btn.dataset.pointerActivatedAt = String(Date.now());
});

document.addEventListener('click', function(e) {
  var btn = e.target.closest('.lcars-expand-btn[data-collapsible-toggle]');
  if (!btn || btn.hidden) return;

  e.preventDefault();

  var collapsible = btn.closest('.lcars-entry-collapsible');
  if (!collapsible) return;

  setCollapsibleExpanded(
    collapsible,
    !collapsible.classList.contains('lcars-expanded'),
    false
  );

  var pointerActivatedAt = Number(btn.dataset.pointerActivatedAt || 0);
  btn.removeAttribute('data-pointer-activated-at');
  if (pointerActivatedAt && Date.now() - pointerActivatedAt < 1000) {
    btn.blur();
  }
});

// Alerts dropdown toggle and lazy-load preview.
document.addEventListener('click', function(e) {
  var trigger = e.target.closest('[data-alerts-trigger]');
  var wrap = document.getElementById('header-notifications-wrap');
  var panel = document.getElementById('header-notifications-preview');
  if (!wrap || !panel) return;

  if (trigger) {
    e.preventDefault();
    e.stopPropagation();

    var isOpen = wrap.classList.toggle('lcars-notifications-open');
    trigger.setAttribute('aria-expanded', isOpen ? 'true' : 'false');

    panel.classList.toggle('lcars-hidden', !isOpen);
    if (isOpen && panel.dataset.loaded !== '1' && panel.dataset.url) {
      htmx.ajax('GET', panel.dataset.url, {
        target: '#header-notifications-preview',
        swap: 'innerHTML',
      });
      panel.dataset.loaded = '1';
    }
    if (isOpen) adjustAlertsPreviewPosition();
    return;
  }

  if (!wrap.contains(e.target)) {
    wrap.classList.remove('lcars-notifications-open');
    panel.classList.add('lcars-hidden');
    var openTrigger = wrap.querySelector('[data-alerts-trigger]');
    if (openTrigger) openTrigger.setAttribute('aria-expanded', 'false');
  }
});

window.addEventListener('resize', adjustAlertsPreviewPosition);

// Close channel action menus when clicking outside
document.addEventListener('click', function(e) {
  document.querySelectorAll('.lcars-channel-actions.lcars-actions-open').forEach(function(menu) {
    if (!menu.contains(e.target)) menu.classList.remove('lcars-actions-open');
  });
});

// Close mobile sidebar when clicking outside of it
document.addEventListener('click', function(e) {
  var sidebar = document.getElementById('channel-sidebar');
  if (!sidebar || !sidebar.classList.contains('lcars-sidebar-open')) return;
  if (!sidebar.contains(e.target) && !e.target.closest('.lcars-header-bracket')) {
    sidebar.classList.remove('lcars-sidebar-open');
  }
});

// Author actions dropdown toggle
document.addEventListener('click', function(e) {
  var btn = e.target.closest('.lcars-author-actions-btn');
  if (btn) {
    e.stopPropagation();
    var container = btn.closest('.lcars-author-actions');
    container.classList.toggle('lcars-open');
    return;
  }
  // Close all open author action menus when clicking outside
  document.querySelectorAll('.lcars-author-actions.lcars-open').forEach(function(menu) {
    if (!menu.contains(e.target)) menu.classList.remove('lcars-open');
  });
});

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js');
}

var _toastTimer = null;

function showToast(message, type, duration) {
  type = type || 'error';
  duration = duration || 3000;
  var toast = document.getElementById('lcars-toast');
  if (!toast) return;
  toast.textContent = message;
  toast.classList.remove('lcars-toast-success', 'lcars-toast-error', 'lcars-hidden');
  toast.classList.add('lcars-toast-' + type);
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(function() {
    toast.classList.add('lcars-hidden');
    _toastTimer = null;
  }, duration);
}

var _errorPaths = [
  '/api/micropub/',
  '/api/timeline/remove/',
  '/api/mute/',
  '/api/unmute/',
  '/api/block/',
  '/api/mark-read/',
  '/api/mark-unread/',
];

function getRequestErrorMessage(xhr) {
  if (!xhr || typeof xhr.responseText !== 'string') return '';
  var text = xhr.responseText.trim();
  if (!text || text.charAt(0) === '<') return '';
  if (text.length <= 180) return text;
  return text.slice(0, 177) + '...';
}

document.body.addEventListener('htmx:afterRequest', function(evt) {
  var path = evt.detail.pathInfo && evt.detail.pathInfo.requestPath;
  if (!path) return;
  var requestConfig = evt.detail.requestConfig || {};
  var method = (requestConfig.verb || '').toLowerCase();
  var sourceEl = evt.detail.elt;

  if (!evt.detail.successful) {
    var isReplyFormRequest = sourceEl && sourceEl.closest && sourceEl.closest('.lcars-reply-form');
    if (isReplyFormRequest && path.indexOf('/api/micropub/reply/') !== -1) return;

    var isInteractionPath = _errorPaths.some(function(p) { return path.indexOf(p) !== -1; });
    if (isInteractionPath) {
      showToast(
        getRequestErrorMessage(evt.detail.xhr) || 'Something went wrong. Please try again.',
        'error'
      );
    }
  } else {
    var isSettingsSave = path.indexOf('/settings/') !== -1 && method === 'post';
    if (isSettingsSave) {
      showToast('Settings saved', 'success');
    }
  }
});
