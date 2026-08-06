/**
 * Photo editor core: shared by the compose-form modal (new-post.js) and the
 * dedicated full-screen edit page (photo-edit-page.js). Operates entirely on
 * the DOM ids defined in the `photo-editor-*` markup partial — both callers
 * render that same markup (as a modal overlay or as a full page), so no
 * DOM-id configuration is needed here.
 *
 * config:
 *   uploadUrl       — micropub media upload endpoint
 *   csrfToken       — CSRF token for the upload POST
 *   onUploaded(url, blob, filename) — called after a successful upload
 *   onUploadStart()  — optional, called right before the upload POST fires
 *   onUploadEnd()    — optional, called after the upload settles (success or error)
 *   onClose()        — optional, called at the end of closeEditor() (Cancel, Escape,
 *                       clicking the backdrop) — e.g. to navigate away on a dedicated page
 *
 * Returns { openEditor(file), closeEditor() }.
 *
 * Depends on photo-gl.js (createPhotoGL) being loaded first.
 */
function createPhotoEditor(config) {
  var uploadUrl = config.uploadUrl;
  var csrfToken = config.csrfToken;
  var onUploaded = config.onUploaded || function() {};
  var onUploadStart = config.onUploadStart || function() {};
  var onUploadEnd = config.onUploadEnd || function() {};
  var onClose = config.onClose || function() {};

  // --- Photo editor state ---

  var editorState = {
    file: null, image: null, filter: 'none',
    cropActive: false, cropRatio: null, cropRect: null,
    dragging: false, dragStart: {x: 0, y: 0}, dragOrigin: null,
    _objectUrl: null, _rafId: 0,
    adjustMode: false,
    adjustments: { brightness: 1, contrast: 1, saturation: 1, warmth: 0, hue: 0,
                   highlights: 0, shadows: 0, vignette: 0, sharpness: 0 },
    rotateAngle: 0,
    cwAngle: 0
  };

  // --- Undo/redo history ---
  // Snapshots hold only the edit-relevant fields (filter/adjustments/angles/crop),
  // never `image`/`file`/object URLs — those stay constant across an edit session.
  var editorHistory = [];
  var historyIndex = -1;
  var HISTORY_LIMIT = 50;

  var FILTERS = {
    none: '',
    vivid: 'contrast(1.16) saturate(1.32)',
    warm: 'sepia(0.35) saturate(1.15) brightness(1.03)',
    cool: 'hue-rotate(12deg) saturate(0.92) brightness(1.01)',
    bw: 'grayscale(1)',
    fade: 'contrast(0.92) brightness(1.08) saturate(0.88) opacity(0.9)',
    // Dramatic high-contrast cinematic B&W — distinct from flat 'bw'
    noir: 'grayscale(1) contrast(1.5) brightness(0.9)',
    // Warm sunset dusk: keeps evening depth without a cool green cast in blues
    dusk: 'sepia(0.38) hue-rotate(335deg) saturate(1.18) brightness(0.94) contrast(1.08)',
    // Film matte: SVG feComponentTransfer lifts blacks (output = 0.80×input + 0.10)
    // distinct from 'fade' which uses opacity blending against white
    matte: 'url(#photo-editor-matte-filter) saturate(0.78)',
    // Hyper-saturated HDR pop — aggressively different from subtle 'vivid'
    chrome: 'contrast(1.28) saturate(1.95) brightness(1.05) hue-rotate(3deg)'
  };

  // GL uniform equivalents of FILTERS for the WebGL rendering path.
  // hue values are in degrees; getUniformsFromState() converts to radians.
  // matte: (col-0.5)*0.80+0.5 = 0.80*col+0.10 matches the SVG feComponentTransfer.
  var FILTER_UNIFORMS = {
    none:   { brightness:1,    contrast:1,    saturation:1,    sepia:0,    hue:0,   opacity:1   },
    vivid:  { brightness:1,    contrast:1.16, saturation:1.32, sepia:0,    hue:0,   opacity:1   },
    warm:   { brightness:1.03, contrast:1,    saturation:1.15, sepia:0.35, hue:0,   opacity:1   },
    cool:   { brightness:1.01, contrast:1,    saturation:0.92, sepia:0,    hue:12,  opacity:1   },
    bw:     { brightness:1,    contrast:1,    saturation:0,    sepia:0,    hue:0,   opacity:1   },
    fade:   { brightness:1.08, contrast:0.92, saturation:0.88, sepia:0,    hue:0,   opacity:0.9 },
    noir:   { brightness:0.9,  contrast:1.5,  saturation:0,    sepia:0,    hue:0,   opacity:1   },
    dusk:   { brightness:0.94, contrast:1.08, saturation:1.18, sepia:0.38, hue:-25, opacity:1   },
    matte:  { brightness:1,    contrast:0.80, saturation:0.78, sepia:0,    hue:0,   opacity:1   },
    chrome: { brightness:1.05, contrast:1.28, saturation:1.95, sepia:0,    hue:3,   opacity:1   }
  };

  function getUniformsFromState() {
    if (editorState.adjustMode) {
      var a = editorState.adjustments;
      return {
        brightness: a.brightness,
        contrast:   a.contrast,
        saturation: a.saturation,
        sepia:      a.warmth,
        hue:        a.hue * Math.PI / 180,
        opacity:    1.0,
        highlights: a.highlights,
        shadows:    a.shadows,
        vignette:   a.vignette,
        sharpness:  a.sharpness
      };
    }
    var f = FILTER_UNIFORMS[editorState.filter] || FILTER_UNIFORMS.none;
    return {
      brightness: f.brightness,
      contrast:   f.contrast,
      saturation: f.saturation,
      sepia:      f.sepia,
      hue:        f.hue * Math.PI / 180,
      opacity:    f.opacity,
      highlights: 0,
      shadows:    0,
      vignette:   0,
      sharpness:  0
    };
  }

  function buildFilterString() {
    if (editorState.adjustMode) {
      var a = editorState.adjustments;
      var parts = [];
      if (a.brightness !== 1) parts.push('brightness(' + a.brightness + ')');
      if (a.contrast !== 1) parts.push('contrast(' + a.contrast + ')');
      if (a.saturation !== 1) parts.push('saturate(' + a.saturation + ')');
      if (a.warmth !== 0) parts.push('sepia(' + a.warmth + ')');
      if (a.hue !== 0) parts.push('hue-rotate(' + a.hue + 'deg)');
      return parts.join(' ');
    }
    return FILTERS[editorState.filter] || '';
  }

  function formatAdjVal(key, val) {
    if (key === 'hue') {
      if (val === 0) return '0°';
      return (val > 0 ? '+' : '') + Math.round(val) + '°';
    }
    if (key === 'warmth' || key === 'highlights' || key === 'shadows') {
      var pct = Math.round(val * 100);
      return pct === 0 ? '0' : (pct > 0 ? '+' : '') + pct + '%';
    }
    if (key === 'vignette' || key === 'sharpness') {
      return Math.round(val * 100) + '%';
    }
    var pct = Math.round((val - 1) * 100);
    return pct === 0 ? '0' : (pct > 0 ? '+' : '') + pct + '%';
  }

  var overlay = document.getElementById('photo-editor-overlay');
  var canvas = document.getElementById('photo-editor-canvas');
  var glRenderer = canvas ? createPhotoGL(canvas) : null;
  var ctx = (!glRenderer && canvas) ? canvas.getContext('2d') : null;
  var cropCanvas = document.getElementById('photo-editor-crop-canvas');
  var cropCtx = cropCanvas ? cropCanvas.getContext('2d') : null;
  var canvasWrap = canvas ? canvas.closest('.photo-editor-canvas-wrap') : null;

  function getCanvasCoords(e) {
    var rect = canvas.getBoundingClientRect();
    return {x: e.clientX - rect.left, y: e.clientY - rect.top};
  }

  function sizeCanvas() {
    if (!editorState.image || !canvasWrap) return;
    var maxW = canvasWrap.clientWidth || 520;
    var maxH = canvasWrap.clientHeight || 420;
    var isSwapped = (editorState.cwAngle % 180 !== 0);
    var imgW = isSwapped ? editorState.image.naturalHeight : editorState.image.naturalWidth;
    var imgH = isSwapped ? editorState.image.naturalWidth : editorState.image.naturalHeight;
    var ratio = imgW / imgH;
    var w = maxW;
    var h = w / ratio;
    if (h > maxH) { h = maxH; w = h * ratio; }
    canvas.width = Math.round(w);
    canvas.height = Math.round(h);
    if (cropCanvas) { cropCanvas.width = canvas.width; cropCanvas.height = canvas.height; }
  }

  // overrideEmpty renders the literal, unedited original (no filter/adjustments/
  // rotation/crop mask) without touching editorState — used for before/after compare.
  var EMPTY_UNIFORMS = { brightness: 1, contrast: 1, saturation: 1, sepia: 0, hue: 0, opacity: 1 };

  function renderCanvas(overrideEmpty) {
    if (!editorState.image) return;
    if (glRenderer) {
      var totalAngle = overrideEmpty ? 0 : (editorState.cwAngle + editorState.rotateAngle);
      var uniforms = overrideEmpty ? EMPTY_UNIFORMS : getUniformsFromState();
      glRenderer.render(editorState.image, uniforms, totalAngle);
      // Draw crop overlay on the separate 2D canvas (can't mix GL + 2D on same element)
      if (cropCtx) {
        cropCtx.clearRect(0, 0, cropCanvas.width, cropCanvas.height);
        if (!overrideEmpty && editorState.cropRect) {
          var r = editorState.cropRect;
          cropCtx.fillStyle = 'rgba(0,0,0,0.45)';
          cropCtx.fillRect(0, 0, cropCanvas.width, r.y);
          cropCtx.fillRect(0, r.y + r.h, cropCanvas.width, cropCanvas.height - r.y - r.h);
          cropCtx.fillRect(0, r.y, r.x, r.h);
          cropCtx.fillRect(r.x + r.w, r.y, cropCanvas.width - r.x - r.w, r.h);
          cropCtx.strokeStyle = '#f89a25';
          cropCtx.lineWidth = 2;
          cropCtx.strokeRect(r.x, r.y, r.w, r.h);
        }
      }
    } else {
      // 2D fallback (WebGL unavailable)
      if (!ctx) return;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      var totalAngle = overrideEmpty ? 0 : (editorState.cwAngle + editorState.rotateAngle);
      var isSwapped = (!overrideEmpty && editorState.cwAngle % 180 !== 0);
      if (totalAngle) {
        ctx.save();
        ctx.translate(canvas.width / 2, canvas.height / 2);
        ctx.rotate(totalAngle * Math.PI / 180);
        ctx.filter = overrideEmpty ? 'none' : buildFilterString();
        if (isSwapped) {
          ctx.drawImage(editorState.image, -canvas.height / 2, -canvas.width / 2, canvas.height, canvas.width);
        } else {
          ctx.drawImage(editorState.image, -canvas.width / 2, -canvas.height / 2, canvas.width, canvas.height);
        }
        ctx.filter = 'none';
        ctx.restore();
      } else {
        ctx.filter = overrideEmpty ? 'none' : buildFilterString();
        ctx.drawImage(editorState.image, 0, 0, canvas.width, canvas.height);
        ctx.filter = 'none';
      }
      if (!overrideEmpty && editorState.cropRect) {
        var r = editorState.cropRect;
        ctx.fillStyle = 'rgba(0,0,0,0.45)';
        ctx.fillRect(0, 0, canvas.width, r.y);
        ctx.fillRect(0, r.y + r.h, canvas.width, canvas.height - r.y - r.h);
        ctx.fillRect(0, r.y, r.x, r.h);
        ctx.fillRect(r.x + r.w, r.y, canvas.width - r.x - r.w, r.h);
        ctx.strokeStyle = '#f89a25';
        ctx.lineWidth = 2;
        ctx.strokeRect(r.x, r.y, r.w, r.h);
      }
    }
  }

  function renderFilterPreviews() {
    if (!overlay || !editorState.image) return;
    var btns = Array.from(overlay.querySelectorAll('.photo-editor-filter-btn'));
    var img = editorState.image;
    var idx = 0;

    if (glRenderer) {
      // GL path: one shared offscreen GL canvas stamps into each 48×48 2D preview canvas
      var glPrev = createPhotoGL(48, 48);
      if (glPrev) {
        var renderGLNext = function() {
          if (idx >= btns.length || editorState.image !== img) { glPrev.destroy(); return; }
          var btn = btns[idx++];
          var pc = btn.querySelector('canvas');
          if (pc) {
            var f = FILTER_UNIFORMS[btn.dataset.filter] || FILTER_UNIFORMS.none;
            glPrev.render(img, {
              brightness: f.brightness, contrast: f.contrast, saturation: f.saturation,
              sepia: f.sepia, hue: f.hue * Math.PI / 180, opacity: f.opacity
            }, 0);
            var pctx = pc.getContext('2d');
            pctx.clearRect(0, 0, 48, 48);
            pctx.drawImage(glPrev.canvas, 0, 0);
          }
          requestAnimationFrame(renderGLNext);
        };
        requestAnimationFrame(renderGLNext);
        return;
      }
    }

    // 2D fallback
    var renderNext = function() {
      if (idx >= btns.length || editorState.image !== img) return;
      var btn = btns[idx++];
      var pc = btn.querySelector('canvas');
      if (pc) {
        var pctx = pc.getContext('2d');
        pctx.imageSmoothingQuality = 'low';
        pctx.clearRect(0, 0, 48, 48);
        pctx.filter = FILTERS[btn.dataset.filter] || '';
        pctx.drawImage(img, 0, 0, 48, 48);
        pctx.filter = 'none';
      }
      requestAnimationFrame(renderNext);
    };
    requestAnimationFrame(renderNext);
  }

  function snapshotState() {
    var a = editorState.adjustments;
    var r = editorState.cropRect;
    return {
      filter: editorState.filter,
      adjustMode: editorState.adjustMode,
      adjustments: {
        brightness: a.brightness, contrast: a.contrast, saturation: a.saturation,
        warmth: a.warmth, hue: a.hue, highlights: a.highlights,
        shadows: a.shadows, vignette: a.vignette, sharpness: a.sharpness
      },
      cwAngle: editorState.cwAngle,
      rotateAngle: editorState.rotateAngle,
      cropActive: editorState.cropActive,
      cropRatio: editorState.cropRatio,
      cropRect: r ? {x: r.x, y: r.y, w: r.w, h: r.h} : null
    };
  }

  function restoreSnapshot(snap) {
    editorState.filter = snap.filter;
    editorState.adjustMode = snap.adjustMode;
    editorState.adjustments = {
      brightness: snap.adjustments.brightness, contrast: snap.adjustments.contrast,
      saturation: snap.adjustments.saturation, warmth: snap.adjustments.warmth,
      hue: snap.adjustments.hue, highlights: snap.adjustments.highlights,
      shadows: snap.adjustments.shadows, vignette: snap.adjustments.vignette,
      sharpness: snap.adjustments.sharpness
    };
    editorState.cwAngle = snap.cwAngle;
    editorState.rotateAngle = snap.rotateAngle;
    editorState.cropActive = snap.cropActive;
    editorState.cropRatio = snap.cropRatio;
    editorState.cropRect = snap.cropRect ?
      {x: snap.cropRect.x, y: snap.cropRect.y, w: snap.cropRect.w, h: snap.cropRect.h} : null;
  }

  function updateHistoryButtons() {
    var undoBtn = document.getElementById('photo-editor-undo');
    var redoBtn = document.getElementById('photo-editor-redo');
    if (undoBtn) undoBtn.disabled = historyIndex <= 0;
    if (redoBtn) redoBtn.disabled = historyIndex >= editorHistory.length - 1;
  }

  // Called after each discrete user action (not on every drag/slider-input
  // frame) — filter select, slider release, crop preset/drag, rotate step.
  function pushHistory() {
    editorHistory.length = historyIndex + 1;
    editorHistory.push(snapshotState());
    if (editorHistory.length > HISTORY_LIMIT) editorHistory.shift();
    historyIndex = editorHistory.length - 1;
    updateHistoryButtons();
  }

  // Re-applies every control's UI (buttons/sliders/labels/panel visibility)
  // to match editorState — used after undo/redo since those mutate state
  // directly rather than through the normal UI event handlers.
  function syncControlsToState() {
    if (!overlay) return;
    overlay.querySelectorAll('.photo-editor-filter-btn').forEach(function(btn) {
      btn.classList.toggle('photo-editor-filter-btn--active', btn.dataset.filter === editorState.filter);
    });
    overlay.querySelectorAll('.photo-editor-crop-preset-btn').forEach(function(btn) {
      var btnRatio = btn.dataset.ratio !== '' ? parseFloat(btn.dataset.ratio) : null;
      btn.classList.toggle('photo-editor-crop-preset-btn--active',
        editorState.cropActive && btnRatio === editorState.cropRatio);
    });
    var hint = overlay.querySelector('.photo-editor-crop-hint');
    if (hint) hint.classList.toggle('lcars-hidden', !editorState.cropActive);
    var cropActions = overlay.querySelector('.photo-editor-crop-actions');
    if (cropActions) cropActions.classList.toggle('lcars-hidden', !editorState.cropActive);
    if (canvas) canvas.style.cursor = editorState.cropActive ? 'crosshair' : 'default';

    var adjustBtnEl = document.getElementById('photo-editor-adjust-btn');
    if (adjustBtnEl) adjustBtnEl.classList.toggle('photo-editor-adjust-btn--active', editorState.adjustMode);
    var filterStripEl = overlay.querySelector('.photo-editor-filter-strip');
    if (filterStripEl) filterStripEl.classList.toggle('lcars-hidden', editorState.adjustMode);
    var adjustPanelEl = document.getElementById('photo-editor-adjustments');
    if (adjustPanelEl) adjustPanelEl.classList.toggle('lcars-hidden', !editorState.adjustMode);
    var modeLabelEl = document.getElementById('photo-editor-mode-label');
    if (modeLabelEl) modeLabelEl.textContent = editorState.adjustMode ? 'Adjust' : 'Filters';

    ['brightness', 'contrast', 'saturation', 'warmth', 'hue',
     'highlights', 'shadows', 'vignette', 'sharpness'].forEach(function(key) {
      var sliderEl = document.getElementById('adj-' + key);
      if (sliderEl) sliderEl.value = editorState.adjustments[key];
      var valEl = document.getElementById('adj-' + key + '-val');
      if (valEl) valEl.textContent = formatAdjVal(key, editorState.adjustments[key]);
    });

    var rotateSliderEl = document.getElementById('photo-editor-rotate-slider');
    if (rotateSliderEl) rotateSliderEl.value = editorState.rotateAngle;
    var rotateValEl = document.getElementById('photo-editor-rotate-val');
    if (rotateValEl) {
      var rv = editorState.rotateAngle;
      rotateValEl.textContent = rv === 0 ? '0°' : (rv > 0 ? '+' : '') + rv + '°';
    }
    var rotateActionsEl = document.getElementById('photo-editor-rotate-actions');
    if (rotateActionsEl) rotateActionsEl.classList.toggle('lcars-hidden', editorState.rotateAngle === 0);

    sizeCanvas();
    renderCanvas();
  }

  function undo() {
    if (historyIndex <= 0) return;
    historyIndex--;
    restoreSnapshot(editorHistory[historyIndex]);
    syncControlsToState();
    updateHistoryButtons();
  }

  function redo() {
    if (historyIndex >= editorHistory.length - 1) return;
    historyIndex++;
    restoreSnapshot(editorHistory[historyIndex]);
    syncControlsToState();
    updateHistoryButtons();
  }

  function setFilter(name) {
    editorState.filter = name;
    if (overlay) {
      overlay.querySelectorAll('.photo-editor-filter-btn').forEach(function(btn) {
        btn.classList.toggle('photo-editor-filter-btn--active', btn.dataset.filter === name);
      });
    }
    renderCanvas();
    pushHistory();
  }

  function calcCropRect(startX, startY, endX, endY) {
    var dw = endX - startX;
    var dh = endY - startY;
    var absW = Math.abs(dw);
    var absH = Math.abs(dh);
    var w, h;
    if (editorState.cropRatio) {
      if (absH * editorState.cropRatio > absW) {
        w = absH * editorState.cropRatio;
        h = absH;
      } else {
        w = absW;
        h = absW / editorState.cropRatio;
      }
    } else {
      w = absW;
      h = absH;
    }
    var x = Math.max(0, Math.min(startX, startX + dw));
    var y = Math.max(0, Math.min(startY, startY + dh));
    w = Math.min(w, canvas.width - x);
    h = Math.min(h, canvas.height - y);
    var MIN_CROP = 10;
    if (w < MIN_CROP || h < MIN_CROP) return null;
    return {x: x, y: y, w: w, h: h};
  }

  function defaultCropRect(ratio) {
    var cw = canvas.width, ch = canvas.height;
    if (!ratio) return {x: 0, y: 0, w: cw, h: ch};
    var w = cw, h = cw / ratio;
    if (h > ch) { h = ch; w = ch * ratio; }
    return {
      x: Math.round((cw - w) / 2),
      y: Math.round((ch - h) / 2),
      w: Math.round(w),
      h: Math.round(h)
    };
  }

  function selectCropPreset(ratioStr) {
    var ratio = ratioStr !== '' ? parseFloat(ratioStr) : null;
    var isSame = editorState.cropActive && editorState.cropRatio === ratio;

    if (isSame) {
      editorState.cropActive = false;
      editorState.cropRatio = null;
      editorState.cropRect = null;
    } else {
      editorState.cropActive = true;
      editorState.cropRatio = ratio;
      editorState.cropRect = defaultCropRect(ratio);
    }

    if (overlay) {
      overlay.querySelectorAll('.photo-editor-crop-preset-btn').forEach(function(btn) {
        var btnRatio = btn.dataset.ratio !== '' ? parseFloat(btn.dataset.ratio) : null;
        btn.classList.toggle('photo-editor-crop-preset-btn--active',
          editorState.cropActive && btnRatio === editorState.cropRatio);
      });
    }
    var hint = overlay ? overlay.querySelector('.photo-editor-crop-hint') : null;
    if (hint) hint.classList.toggle('lcars-hidden', !editorState.cropActive);
    var actions = overlay ? overlay.querySelector('.photo-editor-crop-actions') : null;
    if (actions) actions.classList.toggle('lcars-hidden', !editorState.cropActive);
    if (canvas) canvas.style.cursor = editorState.cropActive ? 'crosshair' : 'default';
    renderCanvas();
    pushHistory();
  }

  function resetCrop() {
    editorState.cropRect = defaultCropRect(editorState.cropRatio);
    renderCanvas();
    pushHistory();
  }

  function setEditorBusy(busy, label) {
    var processingEl = document.getElementById('photo-editor-processing');
    var labelEl = document.getElementById('photo-editor-processing-label');
    if (processingEl) processingEl.classList.toggle('lcars-hidden', !busy);
    if (labelEl && label) labelEl.textContent = label;
    var ids = [
      'photo-editor-rotate-ccw', 'photo-editor-rotate-cw',
      'photo-editor-rotate-slider', 'photo-editor-reset-crop',
      'photo-editor-cancel-rotate',
      'photo-editor-cancel', 'photo-editor-upload', 'photo-editor-adjust-btn'
    ];
    ids.forEach(function(id) {
      var el = document.getElementById(id);
      if (el) el.disabled = busy;
    });
    if (overlay) {
      overlay.querySelectorAll('.photo-editor-crop-preset-btn, .photo-editor-filter-btn').forEach(function(btn) {
        btn.disabled = busy;
      });
    }
  }

  // Returns a rotated copy of `image` via callback(rotatedImage) — never
  // mutates editorState. Rotation stays purely interactive (composed live by
  // photo-gl.js's render() every frame); this is only used at export time to
  // produce a full-resolution rotated source for the crop/render math below.
  function rotateImageCopy(image, angleDeg, callback) {
    var totalAngle = ((Math.round(angleDeg * 100) / 100) % 360 + 360) % 360;
    if (!totalAngle) { callback(image); return; }
    var rad = totalAngle * Math.PI / 180;
    var sin = Math.abs(Math.sin(rad));
    var cos = Math.abs(Math.cos(rad));
    var newW = Math.round(image.naturalWidth * cos + image.naturalHeight * sin);
    var newH = Math.round(image.naturalWidth * sin + image.naturalHeight * cos);

    var off = document.createElement('canvas');
    off.width = newW;
    off.height = newH;
    var offCtx = off.getContext('2d');
    offCtx.translate(newW / 2, newH / 2);
    offCtx.rotate(rad);
    offCtx.drawImage(image, -image.naturalWidth / 2, -image.naturalHeight / 2);

    off.toBlob(function(blob) {
      off.width = 0;
      off.height = 0;
      if (!blob) { callback(image); return; }
      var url = URL.createObjectURL(blob);
      var newImg = new Image();
      newImg.onload = function() {
        URL.revokeObjectURL(url);
        callback(newImg);
      };
      newImg.onerror = function() {
        URL.revokeObjectURL(url);
        callback(image);
      };
      newImg.src = url;
    }, 'image/jpeg', 0.95);
  }

  // Interactive editing (filter preview, slider drag, crop/rotate) works
  // against a downscaled working copy rather than the full upload — WebGL
  // texture allocation at full resolution is a real crash risk on older
  // iOS Safari during interactive dragging. Full resolution is only
  // touched once, at export (see loadFullResImage + buildBlob).
  var WORKING_MAX_DIM = 1600;

  function makeWorkingCopy(image, callback) {
    var longEdge = Math.max(image.naturalWidth, image.naturalHeight);
    if (longEdge <= WORKING_MAX_DIM) { callback(image); return; }
    var scale = WORKING_MAX_DIM / longEdge;
    var w = Math.round(image.naturalWidth * scale);
    var h = Math.round(image.naturalHeight * scale);

    var off = document.createElement('canvas');
    off.width = w;
    off.height = h;
    var offCtx = off.getContext('2d');
    offCtx.drawImage(image, 0, 0, w, h);

    off.toBlob(function(blob) {
      off.width = 0;
      off.height = 0;
      if (!blob) { callback(image); return; }
      var url = URL.createObjectURL(blob);
      var workingImg = new Image();
      workingImg.onload = function() {
        URL.revokeObjectURL(url);
        callback(workingImg);
      };
      workingImg.onerror = function() {
        URL.revokeObjectURL(url);
        callback(image);
      };
      workingImg.src = url;
    }, 'image/jpeg', 0.95);
  }

  // Re-decodes the original, full-resolution file — used only at export so
  // the uploaded result isn't capped at the interactive working resolution.
  function loadFullResImage(file, callback) {
    if (!file) { callback(editorState.image); return; }
    var url = URL.createObjectURL(file);
    var img = new Image();
    img.onload = function() {
      URL.revokeObjectURL(url);
      callback(img);
    };
    img.onerror = function() {
      URL.revokeObjectURL(url);
      callback(editorState.image);
    };
    img.src = url;
  }

  function cancelRotation() {
    editorState.rotateAngle = 0;
    var slider = document.getElementById('photo-editor-rotate-slider');
    if (slider) slider.value = 0;
    var valEl = document.getElementById('photo-editor-rotate-val');
    if (valEl) valEl.textContent = '0°';
    var rotateActions = document.getElementById('photo-editor-rotate-actions');
    if (rotateActions) rotateActions.classList.add('lcars-hidden');
    renderCanvas();
    pushHistory();
  }

  function buildBlob(callback) {
    var totalAngle = editorState.cwAngle + editorState.rotateAngle;
    var cropR = editorState.cropRect;

    // editorState.image is the capped working copy used for interactive
    // editing (see makeWorkingCopy) — export re-decodes the original
    // full-resolution file so the upload isn't limited to preview quality.
    // cropRect is stored as canvas-pixel-space, which is fraction-for-fraction
    // consistent between the working copy and the full-res image (same aspect
    // ratio, only scaled), so the existing scale math below needs no changes.
    loadFullResImage(editorState.file, function(fullImage) {
    // Rotation is composed live during preview (photo-gl.js bakes it into an
    // internal offscreen canvas every frame) — export needs one full-resolution
    // rotated copy to crop/render against, built here without touching editorState.
    rotateImageCopy(fullImage, totalAngle, function(src) {
      if (glRenderer) {
        // GL export: temporarily resize main canvas to full resolution, render, then restore
        var uniforms = getUniformsFromState();
        var targetW, targetH, uvOffset, uvScale;

        if (cropR) {
          // UV offset/scale select the crop region in texture space.
          // Y is flipped in the shader (1.0 - uv.y), so offset.y starts at crop bottom.
          var uvOffsetY = 1.0 - (cropR.y + cropR.h) / canvas.height;
          uvOffset = [cropR.x / canvas.width, uvOffsetY];
          uvScale  = [cropR.w / canvas.width, cropR.h / canvas.height];
          var scaleX = src.naturalWidth / canvas.width;
          var scaleY = src.naturalHeight / canvas.height;
          targetW = Math.round(cropR.w * scaleX);
          targetH = Math.round(cropR.h * scaleY);
        } else {
          targetW = src.naturalWidth;
          targetH = src.naturalHeight;
          uvOffset = [0.0, 0.0];
          uvScale  = [1.0, 1.0];
        }

        var dispW = canvas.width, dispH = canvas.height;
        canvas.width = targetW;
        canvas.height = targetH;
        glRenderer.render(src, uniforms, 0, uvOffset, uvScale);

        var mimeType = (editorState.file && editorState.file.type === 'image/png') ? 'image/png' : 'image/jpeg';
        canvas.toBlob(function(blob) {
          // Restore display canvas and re-render the preview (editorState is untouched)
          canvas.width = dispW;
          canvas.height = dispH;
          glRenderer.render(
            editorState.image, getUniformsFromState(),
            editorState.cwAngle + editorState.rotateAngle
          );
          callback(blob);
        }, mimeType, 0.92);
        return;
      }

      // 2D fallback
      var off = document.createElement('canvas');
      var offCtx;

      if (cropR) {
        var scaleX2 = src.naturalWidth / canvas.width;
        var scaleY2 = src.naturalHeight / canvas.height;
        var px = Math.round(cropR.x * scaleX2);
        var py = Math.round(cropR.y * scaleY2);
        var pw = Math.round(cropR.w * scaleX2);
        var ph = Math.round(cropR.h * scaleY2);
        off.width = pw;
        off.height = ph;
        offCtx = off.getContext('2d');
        offCtx.filter = buildFilterString();
        offCtx.drawImage(src, px, py, pw, ph, 0, 0, pw, ph);
      } else {
        off.width = src.naturalWidth;
        off.height = src.naturalHeight;
        offCtx = off.getContext('2d');
        offCtx.filter = buildFilterString();
        offCtx.drawImage(src, 0, 0, src.naturalWidth, src.naturalHeight);
      }
      offCtx.filter = 'none';

      var mimeType2 = (editorState.file && editorState.file.type === 'image/png') ? 'image/png' : 'image/jpeg';
      off.toBlob(function(blob) {
        // Release the off-screen canvas backing store before handing off the blob
        off.width = 0;
        off.height = 0;
        callback(blob);
      }, mimeType2, 0.92);
    }); // end rotateImageCopy
    }); // end loadFullResImage
  }

  function openEditor(file) {
    if (!overlay || !canvas || (!glRenderer && !ctx)) return;
    editorState.file = file;
    editorState.filter = 'none';
    editorState.cropActive = false;
    editorState.cropRatio = null;
    editorState.cropRect = null;
    editorState.dragging = false;
    editorState.dragOrigin = null;
    editorState.rotateAngle = 0;
    editorState.cwAngle = 0;

    overlay.querySelectorAll('.photo-editor-filter-btn').forEach(function(btn) {
      btn.classList.toggle('photo-editor-filter-btn--active', btn.dataset.filter === 'none');
    });
    overlay.querySelectorAll('.photo-editor-crop-preset-btn').forEach(function(btn) {
      btn.classList.remove('photo-editor-crop-preset-btn--active');
    });
    var hint = overlay.querySelector('.photo-editor-crop-hint');
    if (hint) hint.classList.add('lcars-hidden');
    var cropActions = overlay.querySelector('.photo-editor-crop-actions');
    if (cropActions) cropActions.classList.add('lcars-hidden');
    canvas.style.cursor = 'default';
    var rotateSliderEl = document.getElementById('photo-editor-rotate-slider');
    if (rotateSliderEl) rotateSliderEl.value = 0;
    var rotateValEl = document.getElementById('photo-editor-rotate-val');
    if (rotateValEl) rotateValEl.textContent = '0°';
    var rotateActionsEl = document.getElementById('photo-editor-rotate-actions');
    if (rotateActionsEl) rotateActionsEl.classList.add('lcars-hidden');

    editorState.adjustMode = false;
    editorState.adjustments = { brightness: 1, contrast: 1, saturation: 1, warmth: 0, hue: 0,
                                 highlights: 0, shadows: 0, vignette: 0, sharpness: 0 };
    var adjustBtnEl = document.getElementById('photo-editor-adjust-btn');
    if (adjustBtnEl) adjustBtnEl.classList.remove('photo-editor-adjust-btn--active');
    var filterStripEl = overlay.querySelector('.photo-editor-filter-strip');
    if (filterStripEl) filterStripEl.classList.remove('lcars-hidden');
    var adjustPanelEl = document.getElementById('photo-editor-adjustments');
    if (adjustPanelEl) adjustPanelEl.classList.add('lcars-hidden');
    var modeLabelEl = document.getElementById('photo-editor-mode-label');
    if (modeLabelEl) modeLabelEl.textContent = 'Filters';
    var adjDefaults = { brightness: 1, contrast: 1, saturation: 1, warmth: 0, hue: 0,
                        highlights: 0, shadows: 0, vignette: 0, sharpness: 0 };
    ['brightness', 'contrast', 'saturation', 'warmth', 'hue',
     'highlights', 'shadows', 'vignette', 'sharpness'].forEach(function(key) {
      var sliderEl = document.getElementById('adj-' + key);
      if (sliderEl) sliderEl.value = adjDefaults[key];
      var valEl = document.getElementById('adj-' + key + '-val');
      if (valEl) valEl.textContent = formatAdjVal(key, adjDefaults[key]);
    });

    if (editorState._objectUrl) URL.revokeObjectURL(editorState._objectUrl);
    editorState._objectUrl = URL.createObjectURL(file);

    var img = new Image();
    img.onload = function() {
      // Interactive editing works against a capped working copy, not the
      // full-resolution decode — see makeWorkingCopy / buildBlob's export path.
      makeWorkingCopy(img, function(workingImg) {
        editorState.image = workingImg;
        sizeCanvas();
        renderCanvas();
        renderFilterPreviews();
        editorHistory = [snapshotState()];
        historyIndex = 0;
        updateHistoryButtons();
      });
    };
    img.onerror = function() { closeEditor(); };
    img.src = editorState._objectUrl;
    overlay.classList.remove('lcars-hidden');
  }

  function closeEditor() {
    if (!overlay) return;
    setEditorBusy(false);
    overlay.classList.add('lcars-hidden');
    if (cropCtx) cropCtx.clearRect(0, 0, cropCanvas.width, cropCanvas.height);
    comparing = false;
    var compareBtnEl = document.getElementById('photo-editor-compare-btn');
    if (compareBtnEl) compareBtnEl.setAttribute('aria-pressed', 'false');
    if (editorState._objectUrl) {
      URL.revokeObjectURL(editorState._objectUrl);
      editorState._objectUrl = null;
    }
    if (editorState._rafId) {
      cancelAnimationFrame(editorState._rafId);
      editorState._rafId = 0;
    }
    editorHistory = [];
    historyIndex = -1;
    updateHistoryButtons();
    editorState.file = null;
    editorState.image = null;
    editorState.filter = 'none';
    editorState.cropActive = false;
    editorState.cropRatio = null;
    editorState.cropRect = null;
    editorState.dragging = false;
    editorState.dragOrigin = null;
    editorState.rotateAngle = 0;
    editorState.cwAngle = 0;
    editorState.adjustMode = false;
    editorState.adjustments = { brightness: 1, contrast: 1, saturation: 1, warmth: 0, hue: 0,
                                 highlights: 0, shadows: 0, vignette: 0, sharpness: 0 };
    onClose();
  }

  var comparing = false;

  // Attach all editor event listeners once at init
  if (overlay) {
    overlay.addEventListener('click', function(e) {
      if (e.target === overlay) closeEditor();
    });

    var cancelBtn = document.getElementById('photo-editor-cancel');
    if (cancelBtn) cancelBtn.addEventListener('click', closeEditor);

    var undoBtn = document.getElementById('photo-editor-undo');
    if (undoBtn) undoBtn.addEventListener('click', undo);
    var redoBtn = document.getElementById('photo-editor-redo');
    if (redoBtn) redoBtn.addEventListener('click', redo);

    // Before/after compare: press-and-hold shows the unedited original,
    // releasing reverts — a click-to-toggle fallback covers keyboard activation
    // (keyboard-triggered clicks report MouseEvent.detail === 0, real mouse
    // clicks don't, so the mousedown/mouseup pair already handles those).
    var compareBtn = document.getElementById('photo-editor-compare-btn');
    if (compareBtn) {
      function showOriginal() {
        if (comparing || !editorState.image) return;
        comparing = true;
        compareBtn.setAttribute('aria-pressed', 'true');
        renderCanvas(true);
      }
      function showEdited() {
        if (!comparing) return;
        comparing = false;
        compareBtn.setAttribute('aria-pressed', 'false');
        renderCanvas(false);
      }
      compareBtn.addEventListener('mousedown', showOriginal);
      compareBtn.addEventListener('mouseup', showEdited);
      compareBtn.addEventListener('mouseleave', showEdited);
      compareBtn.addEventListener('touchstart', function(e) {
        e.preventDefault();
        showOriginal();
      }, {passive: false});
      compareBtn.addEventListener('touchend', showEdited);
      compareBtn.addEventListener('touchcancel', showEdited);
      compareBtn.addEventListener('click', function(e) {
        if (e.detail !== 0) return; // real mouse clicks are handled above
        if (comparing) showEdited(); else showOriginal();
      });
    }

    var uploadBtn = document.getElementById('photo-editor-upload');
    if (uploadBtn) {
      uploadBtn.addEventListener('click', function() {
        buildBlob(function(blob) {
          var filename = editorState.file ? editorState.file.name : 'photo.jpg';
          closeEditor();
          onUploadStart();

          var formData = new FormData();
          formData.append('file', blob, filename);

          fetch(uploadUrl, {
            method: 'POST',
            headers: {'X-CSRFToken': csrfToken},
            body: formData,
          })
          .then(function(resp) { return resp.json(); })
          .then(function(data) {
            onUploadEnd();
            if (data.url) {
              onUploaded(data.url, blob, filename);
            } else {
              alert('Upload failed: ' + (data.error || 'Unknown error'));
            }
          })
          .catch(function(err) {
            onUploadEnd();
            alert('Upload failed: ' + err);
          });
        });
      });
    }

    overlay.querySelectorAll('.photo-editor-filter-btn').forEach(function(btn) {
      btn.addEventListener('click', function() {
        setFilter(this.dataset.filter);
      });
    });

    overlay.querySelectorAll('.photo-editor-crop-preset-btn').forEach(function(btn) {
      btn.addEventListener('click', function() {
        selectCropPreset(this.dataset.ratio);
      });
    });

    var resetCropBtn = document.getElementById('photo-editor-reset-crop');
    if (resetCropBtn) resetCropBtn.addEventListener('click', resetCrop);

    // 90° steps reshape the canvas (see sizeCanvas's isSwapped logic), which
    // invalidates any active crop rect defined in the old canvas-pixel-space —
    // clear it rather than carry a stale/out-of-bounds rectangle forward.
    function clearCropOnReshape() {
      editorState.cropRect = null;
      editorState.cropActive = false;
      editorState.cropRatio = null;
      overlay.querySelectorAll('.photo-editor-crop-preset-btn').forEach(function(btn) {
        btn.classList.remove('photo-editor-crop-preset-btn--active');
      });
      var hint = overlay.querySelector('.photo-editor-crop-hint');
      if (hint) hint.classList.add('lcars-hidden');
      var cropActions = overlay.querySelector('.photo-editor-crop-actions');
      if (cropActions) cropActions.classList.add('lcars-hidden');
      if (canvas) canvas.style.cursor = 'default';
    }

    var rotateCcwBtn = document.getElementById('photo-editor-rotate-ccw');
    if (rotateCcwBtn) rotateCcwBtn.addEventListener('click', function() {
      editorState.cwAngle = (editorState.cwAngle + 270) % 360;
      clearCropOnReshape();
      sizeCanvas();
      renderCanvas();
      pushHistory();
    });

    var rotateCwBtn = document.getElementById('photo-editor-rotate-cw');
    if (rotateCwBtn) rotateCwBtn.addEventListener('click', function() {
      editorState.cwAngle = (editorState.cwAngle + 90) % 360;
      clearCropOnReshape();
      sizeCanvas();
      renderCanvas();
      pushHistory();
    });

    var rotateSlider = document.getElementById('photo-editor-rotate-slider');
    var rotateActions = document.getElementById('photo-editor-rotate-actions');
    if (rotateSlider) {
      rotateSlider.addEventListener('input', function() {
        var val = parseFloat(this.value);
        editorState.rotateAngle = val;
        var valEl = document.getElementById('photo-editor-rotate-val');
        if (valEl) {
          valEl.textContent = val === 0 ? '0°' : (val > 0 ? '+' : '') + val + '°';
        }
        if (rotateActions) rotateActions.classList.toggle('lcars-hidden', val === 0);
        renderCanvas();
      });
      // 'change' fires once on release/commit — that's the discrete action
      // worth a history entry, not every intermediate drag frame.
      rotateSlider.addEventListener('change', function() {
        pushHistory();
      });
    }

    var cancelRotateBtn = document.getElementById('photo-editor-cancel-rotate');
    if (cancelRotateBtn) cancelRotateBtn.addEventListener('click', cancelRotation);

    var adjustBtn = document.getElementById('photo-editor-adjust-btn');
    var filterStrip = overlay.querySelector('.photo-editor-filter-strip');
    var adjustPanel = document.getElementById('photo-editor-adjustments');
    var modeLabel = document.getElementById('photo-editor-mode-label');
    if (adjustBtn) {
      adjustBtn.addEventListener('click', function() {
        editorState.adjustMode = !editorState.adjustMode;
        adjustBtn.classList.toggle('photo-editor-adjust-btn--active', editorState.adjustMode);
        if (filterStrip) filterStrip.classList.toggle('lcars-hidden', editorState.adjustMode);
        if (adjustPanel) adjustPanel.classList.toggle('lcars-hidden', !editorState.adjustMode);
        if (modeLabel) modeLabel.textContent = editorState.adjustMode ? 'Adjust' : 'Filters';
        renderCanvas();
      });
    }

    var adjDefaults = { brightness: 1, contrast: 1, saturation: 1, warmth: 0, hue: 0,
                        highlights: 0, shadows: 0, vignette: 0, sharpness: 0 };

    if (adjustPanel) {
      adjustPanel.addEventListener('input', function(e) {
        var el = e.target;
        if (!el.classList.contains('photo-editor-adjust-slider')) return;
        var val = parseFloat(el.value);
        var key = el.id.replace('adj-', '');
        editorState.adjustments[key] = val;
        var valEl = document.getElementById(el.id + '-val');
        if (valEl) valEl.textContent = formatAdjVal(key, val);
        renderCanvas();
      });

      // 'change' fires once on release/commit — that's the discrete action
      // worth a history entry, not every intermediate drag frame.
      adjustPanel.addEventListener('change', function(e) {
        if (!e.target.classList.contains('photo-editor-adjust-slider')) return;
        pushHistory();
      });

      adjustPanel.addEventListener('click', function(e) {
        if (!e.target.classList.contains('photo-editor-adjust-label')) return;
        var row = e.target.closest('.photo-editor-adjust-row');
        if (!row) return;
        var slider = row.querySelector('.photo-editor-adjust-slider');
        if (!slider) return;
        var key = slider.id.replace('adj-', '');
        var def = adjDefaults[key];
        slider.value = def;
        editorState.adjustments[key] = def;
        var valEl = document.getElementById(slider.id + '-val');
        if (valEl) valEl.textContent = formatAdjVal(key, def);
        renderCanvas();
        pushHistory();
      });
    }

    if (canvas) {
      function startDrag(pos) {
        var r = editorState.cropRect;
        if (r && pos.x >= r.x && pos.x <= r.x + r.w &&
                 pos.y >= r.y && pos.y <= r.y + r.h) {
          editorState.dragging = 'move';
          editorState.dragOrigin = {x: r.x, y: r.y};
        } else {
          editorState.dragging = 'draw';
          editorState.dragOrigin = null;
        }
        editorState.dragStart = pos;
      }

      function updateDrag(pos) {
        if (editorState.dragging === 'move') {
          var r = editorState.cropRect;
          var nx = Math.max(0, Math.min(editorState.dragOrigin.x + pos.x - editorState.dragStart.x,
                                       canvas.width - r.w));
          var ny = Math.max(0, Math.min(editorState.dragOrigin.y + pos.y - editorState.dragStart.y,
                                       canvas.height - r.h));
          editorState.cropRect = {x: nx, y: ny, w: r.w, h: r.h};
        } else if (editorState.dragging === 'draw') {
          editorState.cropRect = calcCropRect(
            editorState.dragStart.x, editorState.dragStart.y, pos.x, pos.y);
        }
        // Coalesce multiple mousemove events into one draw per animation frame
        if (editorState._rafId) cancelAnimationFrame(editorState._rafId);
        editorState._rafId = requestAnimationFrame(function() {
          editorState._rafId = 0;
          renderCanvas();
        });
      }

      canvas.addEventListener('mousedown', function(e) {
        if (!editorState.cropActive) return;
        startDrag(getCanvasCoords(e));
      });
      canvas.addEventListener('mousemove', function(e) {
        var pos = getCanvasCoords(e);
        if (editorState.dragging) {
          updateDrag(pos);
        } else if (editorState.cropActive) {
          var r = editorState.cropRect;
          canvas.style.cursor = (r && pos.x >= r.x && pos.x <= r.x + r.w &&
                                     pos.y >= r.y && pos.y <= r.y + r.h)
            ? 'move' : 'crosshair';
        }
      });
      canvas.addEventListener('mouseup', function() {
        var wasDragging = editorState.dragging;
        editorState.dragging = false;
        editorState.dragOrigin = null;
        if (wasDragging) pushHistory();
      });

      canvas.addEventListener('touchstart', function(e) {
        if (!editorState.cropActive) return;
        e.preventDefault();
        startDrag(getCanvasCoords(e.touches[0]));
      }, {passive: false});
      canvas.addEventListener('touchmove', function(e) {
        if (!editorState.dragging) return;
        e.preventDefault();
        updateDrag(getCanvasCoords(e.touches[0]));
      }, {passive: false});
      canvas.addEventListener('touchend', function() {
        var wasDragging = editorState.dragging;
        editorState.dragging = false;
        editorState.dragOrigin = null;
        if (wasDragging) pushHistory();
      });
    }
  }

  // Escape closes editor; Cmd/Ctrl+Z undoes, Shift+Cmd/Ctrl+Z redoes
  // (guards with visibility check, coexists with modal.js)
  document.addEventListener('keydown', function(e) {
    if (!overlay || overlay.classList.contains('lcars-hidden')) return;
    if (e.key === 'Escape') {
      closeEditor();
    } else if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z') {
      e.preventDefault();
      if (e.shiftKey) redo(); else undo();
    }
  });

  return { openEditor: openEditor, closeEditor: closeEditor };
}
