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

document.body.addEventListener('htmx:afterSwap', function(e) {
  initCollapsibles(e.target);
  initEntryMaps(e.target);
  initMarkReadBehavior(e.target);
  // Close mobile sidebar after navigating to a channel
  var sidebar = document.getElementById('channel-sidebar');
  if (sidebar) sidebar.classList.remove('lcars-sidebar-open');
});

// Close user dropdown when clicking outside of it
document.addEventListener('click', function(e) {
  document.querySelectorAll('.lcars-user-menu-open').forEach(function(menu) {
    if (!menu.contains(e.target)) menu.classList.remove('lcars-user-menu-open');
  });
});

// Close channel action menus when clicking outside
document.addEventListener('click', function(e) {
  document.querySelectorAll('.lcars-channel-actions.lcars-actions-open').forEach(function(menu) {
    if (!menu.contains(e.target)) menu.classList.remove('lcars-actions-open');
  });
});

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js');
}
