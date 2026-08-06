/**
 * Dedicated full-screen photo edit page (/drafts/<id>/photo/<hash>/edit/).
 * Loads the already-uploaded photo into the shared photo-editor-core.js
 * editor, then on save re-uploads the edited result and swaps its URL into
 * the draft's photo list via photo_edit_view's POST handler.
 *
 * Requires window.PADD_PHOTO_EDIT (set inline by photo_edit.html) and
 * photo-gl.js + photo-editor-core.js loaded first.
 */
(function() {
  var config = window.PADD_PHOTO_EDIT;
  if (!config) return;

  var csrfToken = JSON.parse(document.body.getAttribute('hx-headers') || '{}')['X-CSRFToken'] || '';

  function goBack() {
    window.location.href = config.backUrl;
  }

  function showError(message) {
    var overlay = document.getElementById('photo-editor-overlay');
    if (!overlay) return;
    var banner = document.createElement('div');
    banner.className = 'lcars-error';
    banner.textContent = message;
    overlay.parentNode.insertBefore(banner, overlay);
  }

  var photoEditor = createPhotoEditor({
    uploadUrl: config.uploadUrl,
    csrfToken: csrfToken,
    onUploadStart: function() {
      var processingEl = document.getElementById('photo-editor-processing');
      var labelEl = document.getElementById('photo-editor-processing-label');
      if (labelEl) labelEl.textContent = 'Saving…';
      if (processingEl) processingEl.classList.remove('lcars-hidden');
    },
    onUploadEnd: function() {
      var processingEl = document.getElementById('photo-editor-processing');
      if (processingEl) processingEl.classList.add('lcars-hidden');
    },
    onUploaded: function(url) {
      var formData = new FormData();
      formData.append('new_url', url);
      fetch(config.saveUrl, {
        method: 'POST',
        headers: {'X-CSRFToken': csrfToken},
        body: formData,
      })
      .then(function(resp) {
        if (!resp.ok) throw new Error('Save failed (' + resp.status + ')');
        goBack();
      })
      .catch(function(err) {
        showError('Could not save the edited photo: ' + err);
      });
    },
    onClose: goBack
  });

  // Load the already-uploaded photo as a File so the editor can work with it
  // exactly like a fresh upload. photoUrl points at photo_proxy_view (same
  // origin as this page) rather than the photo's real home on the user's own
  // micropub media endpoint — that host has no obligation to send CORS
  // headers permissive enough for a cross-origin fetch() + canvas/WebGL use,
  // and proxying server-side (not subject to CORS at all) sidesteps that.
  fetch(config.photoUrl)
    .then(function(resp) {
      if (!resp.ok) throw new Error('Could not load photo (' + resp.status + ')');
      return resp.blob();
    })
    .then(function(blob) {
      var ext = (blob.type && blob.type.split('/')[1]) || 'jpg';
      photoEditor.openEditor(new File([blob], 'photo.' + ext, {type: blob.type || 'image/jpeg'}));
    })
    .catch(function(err) {
      showError('Could not load this photo for editing: ' + err);
    });
})();
