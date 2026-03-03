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
 * Auto-expands collapsible entry content that is already short enough to show in full.
 * Safe to call multiple times — skips already-initialized elements.
 *
 * @param {Document|HTMLElement} root
 */
function initCollapsibles(root) {
  root.querySelectorAll('.lcars-entry-collapsible:not([data-init])').forEach(function(el) {
    el.dataset.init = '1';
    var inner = el.querySelector('.lcars-entry-collapse-inner');
    var btn = el.querySelector('.lcars-expand-btn');
    if (inner.scrollHeight <= 200) {
      el.classList.add('lcars-expanded');
      btn.style.display = 'none';
    }
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
