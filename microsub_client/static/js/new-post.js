/**
 * New Post page: EasyMDE editor, media upload, and location picker.
 *
 * Depends on editor.js and maps.js (loaded via base.html).
 * Reads the media upload URL from data-upload-url on the file input element.
 */
(function() {
  var ta = document.getElementById('post-content');
  if (!ta) return;

  var easymde = null;
  try {
    easymde = createLcarsEditor(ta, {
      placeholder: 'Write your post in Markdown...',
      minHeight: '420px',
    });

    // Restore draft content into EasyMDE if data-draft-content is set
    if (ta.dataset.draftContent) {
      easymde.value(ta.dataset.draftContent);
    }
  } catch (editorError) {
    console.warn('Editor init failed, falling back to plain textarea:', editorError);
  }

  // Sync editor value into the textarea before form submits or HTMX requests
  function syncEditorToTextarea() {
    if (easymde) ta.value = easymde.value();
  }

  var form = document.getElementById('new-post-form');
  if (form) {
    form.addEventListener('submit', function() {
      syncEditorToTextarea();
      var submitBtn = document.getElementById('post-submit-btn');
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Publishing\u2026';
      }
    });
  }

  // --- Autosave ---

  var csrfToken = JSON.parse(document.body.getAttribute('hx-headers') || '{}')['X-CSRFToken'] || '';
  var draftSaveUrl = form ? form.dataset.draftSaveUrl : '';
  var autosaveReady = false;
  var autosaveTimer = null;

  function setDraftStatus(text) {
    var el = document.getElementById('draft-save-status');
    if (el) el.textContent = text;
  }

  function scheduleAutosave() {
    if (!autosaveReady || !form || !draftSaveUrl) return;
    setDraftStatus('Saving\u2026');
    if (autosaveTimer) clearTimeout(autosaveTimer);
    autosaveTimer = setTimeout(performAutosave, 1500);
  }

  function applyDraftSaveResponse(html) {
    var oobMarker = '<input type="hidden" name="draft_id" id="draft-id"';
    var oobIdx = html.indexOf(oobMarker);
    var sidebarHtml = oobIdx === -1 ? html : html.slice(0, oobIdx);
    var sidebar = document.getElementById('compose-sidebar-nav');
    if (sidebar) sidebar.innerHTML = sidebarHtml;
    if (oobIdx !== -1) {
      var tmp = document.createElement('div');
      tmp.innerHTML = html.slice(oobIdx);
      var newIdInput = tmp.querySelector('#draft-id');
      var currentIdInput = document.getElementById('draft-id');
      if (newIdInput && currentIdInput) currentIdInput.value = newIdInput.value;
    }
  }

  function performAutosave() {
    autosaveTimer = null;
    syncEditorToTextarea();
    var formData = new FormData(form);
    fetch(draftSaveUrl, {
      method: 'POST',
      headers: { 'X-CSRFToken': csrfToken },
      body: formData,
    })
    .then(function(resp) {
      if (!resp.ok) throw new Error('draft save failed');
      return resp.text();
    })
    .then(function(html) {
      applyDraftSaveResponse(html);
      setDraftStatus('Saved');
    })
    .catch(function() {
      setDraftStatus('Draft error');
    });
  }

  // --- Post type badge ---

  var postNameInput = document.getElementById('post-name');
  var postTypeBadge = document.getElementById('post-type-badge');

  function updatePostTypeBadge() {
    if (!postTypeBadge) return;
    var hasTitle = !!(postNameInput && postNameInput.value.trim());
    postTypeBadge.textContent = hasTitle ? 'Article' : 'Note';
    postTypeBadge.classList.toggle('post-type-badge--article', hasTitle);
  }

  if (postNameInput) {
    updatePostTypeBadge();
    postNameInput.addEventListener('input', function() {
      updatePostTypeBadge();
      scheduleAutosave();
    });
  }

  // --- Compose toolbar ---

  var composeToolbar = document.getElementById('compose-toolbar');
  var composePanelScrim = document.getElementById('compose-panel-scrim');

  function focusEditor() {
    if (easymde) easymde.codemirror.focus();
    else if (ta) ta.focus();
  }

  if (composeToolbar) {
    var toolbarBtns = Array.prototype.slice.call(composeToolbar.querySelectorAll('.compose-toolbar-btn'));

    var closeAllPanels = function(returnFocus) {
      toolbarBtns.forEach(function(btn) {
        var panel = document.getElementById('compose-panel-' + btn.dataset.composePanel);
        if (panel) panel.hidden = true;
        btn.setAttribute('aria-expanded', 'false');
      });
      if (composePanelScrim) {
        composePanelScrim.hidden = true;
        composePanelScrim.classList.remove('compose-panel-scrim--location');
      }
      if (returnFocus) focusEditor();
    };

    toolbarBtns.forEach(function(btn) {
      var panel = document.getElementById('compose-panel-' + btn.dataset.composePanel);
      if (!panel) return;
      btn.addEventListener('click', function(e) {
        e.stopPropagation();
        var isOpen = !panel.hidden;
        closeAllPanels(isOpen);
        if (!isOpen) {
          panel.hidden = false;
          btn.setAttribute('aria-expanded', 'true');
          if (composePanelScrim) {
            composePanelScrim.hidden = false;
            composePanelScrim.classList.toggle('compose-panel-scrim--location', panel.id === 'compose-panel-location');
          }
          var focusEl = panel.querySelector('input:not([type="hidden"]), textarea');
          if (focusEl) focusEl.focus();
        }
      });
    });

    var locationSheetDone = document.getElementById('location-sheet-done');
    if (locationSheetDone) {
      locationSheetDone.addEventListener('click', function() { closeAllPanels(true); });
    }

    if (composePanelScrim) {
      composePanelScrim.addEventListener('click', function() { closeAllPanels(true); });
    }

    document.addEventListener('click', function(e) {
      if (composeToolbar.contains(e.target)) return;
      var openPanel = document.querySelector('.compose-panel:not([hidden])');
      if (openPanel && !openPanel.contains(e.target)) closeAllPanels(false);
    });

    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && document.querySelector('.compose-panel:not([hidden])')) {
        closeAllPanels(true);
      }
    });
  }

  // --- Character counter ---

  var charCounter = document.getElementById('char-counter');

  var SILOS = [
    { patterns: ['twitter.com', 'twitter', 't.co'], limit: 280, color: '#1d9bf0' },
    { patterns: ['bsky.app', 'bluesky', 'bsky'], limit: 300, color: '#0085ff' },
    { patterns: ['mastodon'], limit: 500, color: '#6364ff' },
  ];

  function matchSilo(uid, name) {
    var text = (uid + ' ' + name).toLowerCase();
    for (var i = 0; i < SILOS.length; i++) {
      var entry = SILOS[i];
      for (var j = 0; j < entry.patterns.length; j++) {
        if (text.indexOf(entry.patterns[j]) !== -1) return entry;
      }
    }
    return null;
  }

  function getSiloLimit(uid, name) {
    var silo = matchSilo(uid, name);
    return silo ? silo.limit : null;
  }

  function getActiveLimit() {
    var checkboxes = document.querySelectorAll('input[name="syndicate_to"]:checked');
    var min = null;
    checkboxes.forEach(function(cb) {
      var label = cb.closest('label') || cb.parentElement;
      var name = label ? label.textContent.trim() : '';
      var limit = getSiloLimit(cb.value, name);
      if (limit !== null && (min === null || limit < min)) {
        min = limit;
      }
    });
    return min;
  }

  function updateCharCounter() {
    if (!charCounter) return;
    var count = easymde ? easymde.value().length : ta.value.length;
    var limit = getActiveLimit();
    charCounter.className = 'lcars-char-counter';
    if (limit === null) {
      charCounter.textContent = count + ' characters';
    } else {
      var remaining = limit - count;
      charCounter.textContent = count + ' / ' + limit;
      if (remaining < 0) {
        charCounter.classList.add('lcars-char-counter--over');
      } else if (remaining <= 20) {
        charCounter.classList.add('lcars-char-counter--warn');
      }
    }
  }

  if (easymde) {
    easymde.codemirror.on('change', updateCharCounter);
    easymde.codemirror.on('change', scheduleAutosave);
    updateCharCounter();
  }

  document.querySelectorAll('input[name="syndicate_to"]').forEach(function(cb) {
    cb.addEventListener('change', updateCharCounter);

    var pillLabel = document.querySelector('label[for="' + cb.id + '"]');
    if (pillLabel) {
      var silo = matchSilo(cb.value, pillLabel.textContent);
      if (silo) pillLabel.style.setProperty('--syndicate-accent', silo.color);
    }
  });

  // --- Media upload ---

  var fileInput = document.getElementById('media-file-input');
  if (fileInput) {
    var uploadUrl = fileInput.dataset.uploadUrl;
    var convertUrl = fileInput.dataset.convertUrl;

    var photoEditor = createPhotoEditor({
      uploadUrl: uploadUrl,
      csrfToken: csrfToken,
      onUploadStart: function() {
        var uploading = document.getElementById('media-uploading');
        if (uploading) uploading.classList.remove('lcars-hidden');
      },
      onUploadEnd: function() {
        var uploading = document.getElementById('media-uploading');
        if (uploading) uploading.classList.add('lcars-hidden');
      },
      onUploaded: function(url, blob, filename) {
        addMediaThumbnail(url, blob, filename);
      }
    });

    // Web-native files go straight to the editor; everything else is sent to
    // the server for conversion first, then the returned JPEG opens the editor.
    fileInput.addEventListener('change', function() {
      var file = this.files[0];
      if (!file) return;
      this.value = '';
      if (isWebNative(file)) {
        photoEditor.openEditor(file);
      } else {
        convertAndEdit(file);
      }
    });
  }

  // MIME types every modern browser can decode natively (and display in a canvas).
  var WEB_NATIVE_TYPES = {
    'image/jpeg': true, 'image/png': true, 'image/gif': true,
    'image/webp': true, 'image/avif': true, 'image/svg+xml': true,
  };

  function isWebNative(file) {
    return !!WEB_NATIVE_TYPES[file.type];
  }

  // Send *file* to the server for conversion, receive a JPEG blob, then open
  // the photo editor with the result — identical UX to selecting a JPEG, but
  // the heavy lifting happens on the server instead of in the browser.
  function convertAndEdit(file) {
    var converting = document.getElementById('media-converting');
    if (converting) converting.classList.remove('lcars-hidden');

    var formData = new FormData();
    formData.append('file', file, file.name);

    fetch(convertUrl, {
      method: 'POST',
      headers: {'X-CSRFToken': csrfToken},
      body: formData,
    })
    .then(function(resp) {
      if (!resp.ok) {
        return resp.json().then(function(d) { throw new Error(d.error || resp.status); });
      }
      return resp.blob();
    })
    .then(function(blob) {
      if (converting) converting.classList.add('lcars-hidden');
      var stem = file.name.replace(/\.[^.]+$/, '');
      photoEditor.openEditor(new File([blob], stem + '.jpg', {type: 'image/jpeg'}));
    })
    .catch(function(err) {
      if (converting) converting.classList.add('lcars-hidden');
      alert('Could not convert image: ' + err);
    });
  }

  // Deterministic id derived from a photo's URL — mirrors
  // microsub_client/photo_id.py's FNV-1a implementation exactly (32-bit,
  // hex-encoded). Used to build a stable edit link for an already-uploaded
  // photo without a database Upload/Photo model. Keep the two in sync.
  function photoUrlHash(url) {
    var h = 0x811c9dc5;
    for (var i = 0; i < url.length; i++) {
      h ^= url.charCodeAt(i) & 0xFF;
      h = Math.imul(h, 0x01000193);
    }
    return (h >>> 0).toString(16).padStart(8, '0');
  }

  // Editing an already-uploaded photo requires a saved Draft to link back to
  // (see microsub_client/views.py's photo_edit_view) — until the first
  // autosave has run, #draft-id is empty and there's nothing to resolve the
  // edit link against, so the affordance is simply omitted until then.
  function buildPhotoEditLink(url) {
    var draftIdInput = document.getElementById('draft-id');
    var draftId = draftIdInput ? draftIdInput.value : '';
    if (!draftId) return null;
    var link = document.createElement('a');
    link.className = 'lcars-media-thumb-edit';
    link.title = 'Edit photo';
    link.setAttribute('aria-label', 'Edit photo');
    link.href = '/drafts/' + draftId + '/photo/' + photoUrlHash(url) + '/edit/';
    link.innerHTML = '<i class="fas fa-pencil-alt"></i>';
    return link;
  }

  function addPhotoFromUrl(url) {
    var container = document.getElementById('media-thumbnails');
    if (!container) return;
    var item = document.createElement('div');
    item.className = 'lcars-media-thumb';

    var img = document.createElement('img');
    img.src = url;
    img.alt = url;

    var removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'lcars-media-thumb-remove';
    removeBtn.innerHTML = '&times;';
    removeBtn.onclick = function() { item.remove(); scheduleAutosave(); };

    var copyBtn = document.createElement('button');
    copyBtn.type = 'button';
    copyBtn.className = 'lcars-media-thumb-copy';
    copyBtn.title = 'Copy URL';
    copyBtn.innerHTML = '<i class="fas fa-link"></i>';
    copyBtn.addEventListener('click', function() {
      var self = this;
      function showCopied() {
        self.innerHTML = '<i class="fas fa-check"></i>';
        self.classList.add('lcars-media-thumb-copy--done');
        setTimeout(function() {
          self.innerHTML = '<i class="fas fa-link"></i>';
          self.classList.remove('lcars-media-thumb-copy--done');
        }, 1500);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(showCopied);
      } else {
        window.prompt('Copy this URL:', url);
      }
    });

    var hidden = document.createElement('input');
    hidden.type = 'hidden';
    hidden.name = 'photo';
    hidden.value = url;

    var editLink = buildPhotoEditLink(url);

    item.appendChild(img);
    item.appendChild(removeBtn);
    item.appendChild(copyBtn);
    if (editLink) item.appendChild(editLink);
    item.appendChild(hidden);
    container.appendChild(item);
  }

  function addMediaThumbnail(url, blob, filename) {
    var container = document.getElementById('media-thumbnails');
    var item = document.createElement('div');
    item.className = 'lcars-media-thumb';

    // When no local blob is available (e.g. direct HEIC upload), fall back to
    // the server URL so the browser displays the converted JPEG instead.
    var objUrl = blob ? URL.createObjectURL(blob) : null;
    var img = document.createElement('img');
    img.src = objUrl || url;
    img.alt = filename || url;

    var removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'lcars-media-thumb-remove';
    removeBtn.innerHTML = '&times;';
    removeBtn.onclick = function() {
      if (objUrl) URL.revokeObjectURL(objUrl);
      item.remove();
      scheduleAutosave();
    };

    var copyBtn = document.createElement('button');
    copyBtn.type = 'button';
    copyBtn.className = 'lcars-media-thumb-copy';
    copyBtn.title = 'Copy URL';
    copyBtn.innerHTML = '<i class="fas fa-link"></i>';
    copyBtn.addEventListener('click', function() {
      var self = this;
      function showCopied() {
        self.innerHTML = '<i class="fas fa-check"></i>';
        self.classList.add('lcars-media-thumb-copy--done');
        setTimeout(function() {
          self.innerHTML = '<i class="fas fa-link"></i>';
          self.classList.remove('lcars-media-thumb-copy--done');
        }, 1500);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(showCopied);
      } else {
        window.prompt('Copy this URL:', url);
      }
    });

    var hidden = document.createElement('input');
    hidden.type = 'hidden';
    hidden.name = 'photo';
    hidden.value = url;

    // The edit link only resolves once this photo is actually persisted on the
    // draft (autosave below is debounced) — built here anyway since draft-id
    // itself may already exist from an earlier save; a click shortly after a
    // brand-new upload could 404 until that autosave lands.
    var editLink = buildPhotoEditLink(url);

    item.appendChild(img);
    item.appendChild(removeBtn);
    item.appendChild(copyBtn);
    if (editLink) item.appendChild(editLink);
    item.appendChild(hidden);
    container.appendChild(item);
    scheduleAutosave();
  }

  // --- Tag widget ---

  var tagField = document.getElementById('lcars-tag-field');
  var tagChipsEl = document.getElementById('lcars-tag-chips');
  var tagTextInput = document.getElementById('post-tag-input');
  var tagHiddenInput = document.getElementById('post-tags');

  if (tagField && tagChipsEl && tagTextInput && tagHiddenInput) {
    var TAG_COLORS = ['#f89a25', '#f1c86e', '#5fa8a0', '#8a8aed', '#b68abe'];
    var activeTags = [];
    var tagColorIdx = 0;

    tagField.addEventListener('click', function() { tagTextInput.focus(); });

    function syncTagHidden() {
      tagHiddenInput.value = activeTags.join(',');
      scheduleAutosave();
    }

    function addTag(value) {
      var val = value.trim().replace(/,/g, '').toLowerCase();
      if (!val || activeTags.indexOf(val) !== -1) return;
      activeTags.push(val);

      var color = TAG_COLORS[tagColorIdx % TAG_COLORS.length];
      tagColorIdx++;

      var chip = document.createElement('span');
      chip.className = 'lcars-tag-chip';
      chip.style.background = color;
      chip.dataset.tag = val;

      var labelEl = document.createElement('span');
      labelEl.textContent = val;

      var removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'lcars-tag-chip-remove';
      removeBtn.setAttribute('aria-label', 'Remove tag ' + val);
      removeBtn.innerHTML = '&times;';
      removeBtn.addEventListener('click', function() { removeTag(val, chip); });

      chip.appendChild(labelEl);
      chip.appendChild(removeBtn);
      tagChipsEl.insertBefore(chip, tagTextInput);
      syncTagHidden();
    }

    function removeTag(val, chip) {
      var idx = activeTags.indexOf(val);
      if (idx === -1) return;
      activeTags.splice(idx, 1);
      chip.classList.add('lcars-tag-removing');
      chip.addEventListener('animationend', function() { chip.remove(); }, { once: true });
      syncTagHidden();
    }

    tagTextInput.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' || e.key === ',' || e.key === 'Tab') {
        if (this.value.trim()) {
          e.preventDefault();
          addTag(this.value);
          this.value = '';
        }
      } else if (e.key === 'Backspace' && !this.value && activeTags.length) {
        var chips = tagChipsEl.querySelectorAll('.lcars-tag-chip');
        var lastChip = chips[chips.length - 1];
        if (lastChip) removeTag(lastChip.dataset.tag, lastChip);
      }
    });

    tagTextInput.addEventListener('blur', function() {
      if (this.value.trim()) {
        addTag(this.value);
        this.value = '';
      }
    });

    tagTextInput.addEventListener('paste', function(e) {
      var pasted = (e.clipboardData || window.clipboardData).getData('text');
      if (pasted.indexOf(',') !== -1) {
        e.preventDefault();
        pasted.split(',').forEach(function(t) { addTag(t); });
      }
    });

    // Restore draft tags if data-draft-tags is set on the hidden input
    if (tagHiddenInput.dataset.draftTags) {
      tagHiddenInput.dataset.draftTags.split(',').forEach(function(t) { addTag(t); });
    }
  }

  // --- Restore draft photos ---

  var draftPhotosEl = document.getElementById('draft-photos');
  if (draftPhotosEl) {
    try {
      var draftPhotos = JSON.parse(draftPhotosEl.textContent);
      if (Array.isArray(draftPhotos)) {
        draftPhotos.forEach(function(url) { addPhotoFromUrl(url); });
      }
    } catch (e) { /* ignore parse errors */ }
  }

  // --- Location picker ---

  var locationToggle = document.getElementById('location-toggle');
  var locationMap = null;

  if (locationToggle) {
    locationToggle.addEventListener('change', function() {
      var display = document.getElementById('location-display');

      if (this.checked) {
        display.classList.remove('lcars-hidden');

        if (!navigator.geolocation) {
          document.getElementById('location-coords').textContent = 'Geolocation not supported';
          locationToggle.checked = false;
          display.classList.add('lcars-hidden');
          return;
        }

        document.getElementById('location-coords').textContent = 'Getting location\u2026';
        navigator.geolocation.getCurrentPosition(function(pos) {
          var lat = pos.coords.latitude.toFixed(6);
          var lng = pos.coords.longitude.toFixed(6);
          document.getElementById('location-coords').textContent = lat + ', ' + lng;
          document.getElementById('location-input').value = 'geo:' + lat + ',' + lng;

          var mapEl = document.getElementById('location-map');
          mapEl.style.display = 'block';
          if (locationMap) locationMap.remove();
          locationMap = createLcarsMap(mapEl, parseFloat(lat), parseFloat(lng));
          scheduleAutosave();
        }, function() {
          document.getElementById('location-coords').textContent = 'Unable to get location';
          locationToggle.checked = false;
          display.classList.add('lcars-hidden');
        });
      } else {
        display.classList.add('lcars-hidden');
        document.getElementById('location-input').value = '';
        if (locationMap) {
          locationMap.remove();
          locationMap = null;
          document.getElementById('location-map').style.display = 'none';
        }
        scheduleAutosave();
      }
    });
  }

  // Restoration above (draft content/tags/photos) runs synchronously before
  // this point, so autosave can't fire on page load — only on real edits.
  autosaveReady = true;
})();
