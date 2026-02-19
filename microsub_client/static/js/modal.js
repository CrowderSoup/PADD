/**
 * LCARS custom confirm dialog — replaces the browser's native htmx:confirm prompt.
 *
 * Intercepts htmx:confirm events and shows the accessible modal overlay instead.
 * Keyboard (Escape) and backdrop-click also dismiss the dialog.
 */

var _lcarsConfirm = {
  activeEvent: null,
  previousFocus: null,
};

function closeLcarsConfirm(confirmed) {
  var overlay = document.getElementById('lcars-confirm-overlay');
  if (!overlay || overlay.classList.contains('lcars-hidden')) return;

  overlay.classList.add('lcars-hidden');
  overlay.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('lcars-modal-open');

  var activeEvent = _lcarsConfirm.activeEvent;
  _lcarsConfirm.activeEvent = null;

  if (_lcarsConfirm.previousFocus && _lcarsConfirm.previousFocus.focus) {
    _lcarsConfirm.previousFocus.focus();
  }
  _lcarsConfirm.previousFocus = null;

  if (confirmed && activeEvent && activeEvent.detail && typeof activeEvent.detail.issueRequest === 'function') {
    activeEvent.detail.issueRequest(true);
  }
}

function openLcarsConfirm(evt) {
  var overlay = document.getElementById('lcars-confirm-overlay');
  var message = document.getElementById('lcars-confirm-message');
  var acceptBtn = document.getElementById('lcars-confirm-accept');
  if (!overlay || !message || !acceptBtn) return;

  _lcarsConfirm.activeEvent = evt;
  _lcarsConfirm.previousFocus = document.activeElement;

  message.textContent = evt.detail.question || 'Are you sure you want to continue?';
  overlay.classList.remove('lcars-hidden');
  overlay.setAttribute('aria-hidden', 'false');
  document.body.classList.add('lcars-modal-open');
  acceptBtn.focus();
}

document.body.addEventListener('htmx:confirm', function(evt) {
  if (!evt.detail || !evt.detail.question) return;
  evt.preventDefault();
  openLcarsConfirm(evt);
});

document.getElementById('lcars-confirm-cancel').addEventListener('click', function() {
  closeLcarsConfirm(false);
});

document.getElementById('lcars-confirm-accept').addEventListener('click', function() {
  closeLcarsConfirm(true);
});

document.getElementById('lcars-confirm-overlay').addEventListener('click', function(e) {
  if (e.target.id === 'lcars-confirm-overlay') closeLcarsConfirm(false);
});

document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') closeLcarsConfirm(false);
});
