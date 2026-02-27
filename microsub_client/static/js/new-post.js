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
      minHeight: '250px',
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

  // Inject the current editor value directly into the HTMX request parameters.
  // htmx:configRequest fires after HTMX has already serialized the form, so
  // syncing the textarea value at this point doesn't affect the collected params.
  // We must write into e.detail.parameters directly.
  document.addEventListener('htmx:configRequest', function(e) {
    if (e.detail && e.detail.elt && e.detail.elt.id === 'save-draft-btn') {
      e.detail.parameters['content'] = easymde ? easymde.value() : ta.value;
    }
  });

  // --- Character counter ---

  var charCounter = document.getElementById('char-counter');

  var SILO_LIMITS = [
    { patterns: ['twitter.com', 'twitter', 't.co'], limit: 280 },
    { patterns: ['bsky.app', 'bluesky', 'bsky'], limit: 300 },
    { patterns: ['mastodon'], limit: 500 },
  ];

  function getSiloLimit(uid, name) {
    var text = (uid + ' ' + name).toLowerCase();
    for (var i = 0; i < SILO_LIMITS.length; i++) {
      var entry = SILO_LIMITS[i];
      for (var j = 0; j < entry.patterns.length; j++) {
        if (text.indexOf(entry.patterns[j]) !== -1) return entry.limit;
      }
    }
    return null;
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
    updateCharCounter();
  }

  document.querySelectorAll('input[name="syndicate_to"]').forEach(function(cb) {
    cb.addEventListener('change', updateCharCounter);
  });

  // --- Media upload ---

  var fileInput = document.getElementById('media-file-input');
  if (fileInput) {
    var uploadUrl = fileInput.dataset.uploadUrl;
    var convertUrl = fileInput.dataset.convertUrl;
    var csrfToken = JSON.parse(document.body.getAttribute('hx-headers') || '{}')['X-CSRFToken'] || '';

    // --- Photo editor state ---

    var editorState = {
      file: null, image: null, filter: 'none',
      cropActive: false, cropRatio: null, cropRect: null,
      dragging: false, dragStart: {x: 0, y: 0}, dragOrigin: null,
      _objectUrl: null, _cropUrl: null, _rotateUrl: null, _rafId: 0,
      adjustMode: false,
      adjustments: { brightness: 1, contrast: 1, saturation: 1, warmth: 0, hue: 0,
                     highlights: 0, shadows: 0, vignette: 0, sharpness: 0 },
      rotateAngle: 0,
      cwAngle: 0
    };

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
        if (val === 0) return '0\u00b0';
        return (val > 0 ? '+' : '') + Math.round(val) + '\u00b0';
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

    function renderCanvas() {
      if (!editorState.image) return;
      if (glRenderer) {
        var totalAngle = editorState.cwAngle + editorState.rotateAngle;
        glRenderer.render(editorState.image, getUniformsFromState(), totalAngle);
        // Draw crop overlay on the separate 2D canvas (can't mix GL + 2D on same element)
        if (cropCtx) {
          cropCtx.clearRect(0, 0, cropCanvas.width, cropCanvas.height);
          if (editorState.cropRect) {
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
        var totalAngle = editorState.cwAngle + editorState.rotateAngle;
        var isSwapped = (editorState.cwAngle % 180 !== 0);
        if (totalAngle) {
          ctx.save();
          ctx.translate(canvas.width / 2, canvas.height / 2);
          ctx.rotate(totalAngle * Math.PI / 180);
          ctx.filter = buildFilterString();
          if (isSwapped) {
            ctx.drawImage(editorState.image, -canvas.height / 2, -canvas.width / 2, canvas.height, canvas.width);
          } else {
            ctx.drawImage(editorState.image, -canvas.width / 2, -canvas.height / 2, canvas.width, canvas.height);
          }
          ctx.filter = 'none';
          ctx.restore();
        } else {
          ctx.filter = buildFilterString();
          ctx.drawImage(editorState.image, 0, 0, canvas.width, canvas.height);
          ctx.filter = 'none';
        }
        if (editorState.cropRect) {
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

    function setFilter(name) {
      editorState.filter = name;
      if (overlay) {
        overlay.querySelectorAll('.photo-editor-filter-btn').forEach(function(btn) {
          btn.classList.toggle('photo-editor-filter-btn--active', btn.dataset.filter === name);
        });
      }
      renderCanvas();
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
    }

    function applyCrop() {
      if (!editorState.cropRect || !editorState.image) return;
      setEditorBusy(true, 'Cropping\u2026');
      bakeRotation(function() {
      var r = editorState.cropRect;
      var scaleX = editorState.image.naturalWidth / canvas.width;
      var scaleY = editorState.image.naturalHeight / canvas.height;
      var px = Math.round(r.x * scaleX);
      var py = Math.round(r.y * scaleY);
      var pw = Math.round(r.w * scaleX);
      var ph = Math.round(r.h * scaleY);

      var off = document.createElement('canvas');
      off.width = pw;
      off.height = ph;
      var offCtx = off.getContext('2d');
      // Draw source without filter so it stays adjustable post-crop
      offCtx.drawImage(editorState.image, px, py, pw, ph, 0, 0, pw, ph);

      // toBlob + createObjectURL avoids a large base64 string on the heap.
      // JPEG 0.95 keeps the intermediate small (same as bakeRotation); filters
      // are not baked in here so the user can still change them after cropping.
      off.toBlob(function(blob) {
        // Release the off-screen canvas backing store immediately
        off.width = 0;
        off.height = 0;
        if (!blob) { setEditorBusy(false); return; }
        if (editorState._cropUrl) URL.revokeObjectURL(editorState._cropUrl);
        var url = URL.createObjectURL(blob);
        editorState._cropUrl = url;
        var newImg = new Image();
        newImg.onload = function() {
          editorState.image = newImg;
          editorState.cropRect = null;
          sizeCanvas();
          renderCanvas();
          renderFilterPreviews();
          setEditorBusy(false);
        };
        newImg.onerror = function() {
          URL.revokeObjectURL(url);
          editorState._cropUrl = null;
          setEditorBusy(false);
        };
        newImg.src = url;
      }, 'image/jpeg', 0.95);
      }); // end bakeRotation

      editorState.cropActive = false;
      editorState.cropRatio = null;
      if (overlay) {
        overlay.querySelectorAll('.photo-editor-crop-preset-btn').forEach(function(btn) {
          btn.classList.remove('photo-editor-crop-preset-btn--active');
        });
      }
      var hint = overlay ? overlay.querySelector('.photo-editor-crop-hint') : null;
      if (hint) hint.classList.add('lcars-hidden');
      var cropActions = overlay ? overlay.querySelector('.photo-editor-crop-actions') : null;
      if (cropActions) cropActions.classList.add('lcars-hidden');
      if (canvas) canvas.style.cursor = 'default';
    }

    function resetCrop() {
      editorState.cropRect = defaultCropRect(editorState.cropRatio);
      renderCanvas();
    }

    function setEditorBusy(busy, label) {
      var processingEl = document.getElementById('photo-editor-processing');
      var labelEl = document.getElementById('photo-editor-processing-label');
      if (processingEl) processingEl.classList.toggle('lcars-hidden', !busy);
      if (labelEl && label) labelEl.textContent = label;
      var ids = [
        'photo-editor-rotate-ccw', 'photo-editor-rotate-cw',
        'photo-editor-rotate-slider',
        'photo-editor-apply-crop', 'photo-editor-reset-crop',
        'photo-editor-apply-rotate', 'photo-editor-cancel-rotate',
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

    // Bakes cwAngle + rotateAngle into editorState.image, then calls callback.
    // Uses JPEG for fast intermediate encoding (final export uses the correct format).
    function bakeRotation(callback) {
      var totalAngle = (editorState.cwAngle + editorState.rotateAngle) % 360;
      if (!totalAngle) { callback(); return; }
      var img = editorState.image;
      var rad = totalAngle * Math.PI / 180;
      var sin = Math.abs(Math.sin(rad));
      var cos = Math.abs(Math.cos(rad));
      var newW = Math.round(img.naturalWidth * cos + img.naturalHeight * sin);
      var newH = Math.round(img.naturalWidth * sin + img.naturalHeight * cos);

      var off = document.createElement('canvas');
      off.width = newW;
      off.height = newH;
      var offCtx = off.getContext('2d');
      offCtx.translate(newW / 2, newH / 2);
      offCtx.rotate(rad);
      offCtx.drawImage(img, -img.naturalWidth / 2, -img.naturalHeight / 2);

      off.toBlob(function(blob) {
        off.width = 0;
        off.height = 0;
        if (!blob) { callback(); return; }
        if (editorState._rotateUrl) URL.revokeObjectURL(editorState._rotateUrl);
        var url = URL.createObjectURL(blob);
        editorState._rotateUrl = url;
        var newImg = new Image();
        newImg.onload = function() {
          editorState.image = newImg;
          editorState.cwAngle = 0;
          editorState.rotateAngle = 0;
          callback();
        };
        newImg.onerror = function() {
          URL.revokeObjectURL(url);
          editorState._rotateUrl = null;
          setEditorBusy(false);
        };
        newImg.src = url;
      }, 'image/jpeg', 0.95);
    }

    function cancelRotation() {
      editorState.rotateAngle = 0;
      var slider = document.getElementById('photo-editor-rotate-slider');
      if (slider) slider.value = 0;
      var valEl = document.getElementById('photo-editor-rotate-val');
      if (valEl) valEl.textContent = '0\u00b0';
      var rotateActions = document.getElementById('photo-editor-rotate-actions');
      if (rotateActions) rotateActions.classList.add('lcars-hidden');
      renderCanvas();
    }

    function buildBlob(callback) {
      if (editorState.cwAngle || editorState.rotateAngle) {
        bakeRotation(function() { buildBlob(callback); });
        return;
      }

      if (glRenderer) {
        // GL export: temporarily resize main canvas to full resolution, render, then restore
        var src = editorState.image;
        var cropR = editorState.cropRect;
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
          // Restore display canvas and re-render the preview
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
      var src = editorState.image;
      var cropR = editorState.cropRect;
      var offCtx;

      if (cropR) {
        var scaleX = src.naturalWidth / canvas.width;
        var scaleY = src.naturalHeight / canvas.height;
        var px = Math.round(cropR.x * scaleX);
        var py = Math.round(cropR.y * scaleY);
        var pw = Math.round(cropR.w * scaleX);
        var ph = Math.round(cropR.h * scaleY);
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

      var mimeType = (editorState.file && editorState.file.type === 'image/png') ? 'image/png' : 'image/jpeg';
      off.toBlob(function(blob) {
        // Release the off-screen canvas backing store before handing off the blob
        off.width = 0;
        off.height = 0;
        callback(blob);
      }, mimeType, 0.92);
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
      if (rotateValEl) rotateValEl.textContent = '0\u00b0';
      var rotateActionsEl = document.getElementById('photo-editor-rotate-actions');
      if (rotateActionsEl) rotateActionsEl.classList.add('lcars-hidden');

      editorState.adjustMode = false;
      editorState.adjustments = { brightness: 1, contrast: 1, saturation: 1, warmth: 0, hue: 0 };
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
        editorState.image = img;
        sizeCanvas();
        renderCanvas();
        renderFilterPreviews();
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
      if (editorState._objectUrl) {
        URL.revokeObjectURL(editorState._objectUrl);
        editorState._objectUrl = null;
      }
      if (editorState._cropUrl) {
        URL.revokeObjectURL(editorState._cropUrl);
        editorState._cropUrl = null;
      }
      if (editorState._rotateUrl) {
        URL.revokeObjectURL(editorState._rotateUrl);
        editorState._rotateUrl = null;
      }
      if (editorState._rafId) {
        cancelAnimationFrame(editorState._rafId);
        editorState._rafId = 0;
      }
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
    }

    // Attach all editor event listeners once at init
    if (overlay) {
      overlay.addEventListener('click', function(e) {
        if (e.target === overlay) closeEditor();
      });

      var cancelBtn = document.getElementById('photo-editor-cancel');
      if (cancelBtn) cancelBtn.addEventListener('click', closeEditor);

      var uploadBtn = document.getElementById('photo-editor-upload');
      if (uploadBtn) {
        uploadBtn.addEventListener('click', function() {
          buildBlob(function(blob) {
            var filename = editorState.file ? editorState.file.name : 'photo.jpg';
            closeEditor();
            var uploading = document.getElementById('media-uploading');
            if (uploading) uploading.classList.remove('lcars-hidden');

            var formData = new FormData();
            formData.append('file', blob, filename);

            fetch(uploadUrl, {
              method: 'POST',
              headers: {'X-CSRFToken': csrfToken},
              body: formData,
            })
            .then(function(resp) { return resp.json(); })
            .then(function(data) {
              if (uploading) uploading.classList.add('lcars-hidden');
              if (data.url) {
                addMediaThumbnail(data.url, blob, filename);
              } else {
                alert('Upload failed: ' + (data.error || 'Unknown error'));
              }
            })
            .catch(function(err) {
              if (uploading) uploading.classList.add('lcars-hidden');
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

      var applyCropBtn = document.getElementById('photo-editor-apply-crop');
      if (applyCropBtn) applyCropBtn.addEventListener('click', applyCrop);

      var resetCropBtn = document.getElementById('photo-editor-reset-crop');
      if (resetCropBtn) resetCropBtn.addEventListener('click', resetCrop);

      var rotateCcwBtn = document.getElementById('photo-editor-rotate-ccw');
      if (rotateCcwBtn) rotateCcwBtn.addEventListener('click', function() {
        editorState.cwAngle = (editorState.cwAngle + 270) % 360;
        sizeCanvas();
        renderCanvas();
      });

      var rotateCwBtn = document.getElementById('photo-editor-rotate-cw');
      if (rotateCwBtn) rotateCwBtn.addEventListener('click', function() {
        editorState.cwAngle = (editorState.cwAngle + 90) % 360;
        sizeCanvas();
        renderCanvas();
      });

      var rotateSlider = document.getElementById('photo-editor-rotate-slider');
      var rotateActions = document.getElementById('photo-editor-rotate-actions');
      if (rotateSlider) {
        rotateSlider.addEventListener('input', function() {
          var val = parseFloat(this.value);
          editorState.rotateAngle = val;
          var valEl = document.getElementById('photo-editor-rotate-val');
          if (valEl) {
            valEl.textContent = val === 0 ? '0\u00b0' : (val > 0 ? '+' : '') + val + '\u00b0';
          }
          if (rotateActions) rotateActions.classList.toggle('lcars-hidden', val === 0);
          renderCanvas();
        });
      }

      var applyRotateBtn = document.getElementById('photo-editor-apply-rotate');
      if (applyRotateBtn) applyRotateBtn.addEventListener('click', function() {
        if (!editorState.image) return;
        setEditorBusy(true, 'Rotating\u2026');
        bakeRotation(function() {
          var slider = document.getElementById('photo-editor-rotate-slider');
          if (slider) slider.value = 0;
          var valEl = document.getElementById('photo-editor-rotate-val');
          if (valEl) valEl.textContent = '0\u00b0';
          var rotateActions = document.getElementById('photo-editor-rotate-actions');
          if (rotateActions) rotateActions.classList.add('lcars-hidden');
          sizeCanvas();
          renderCanvas();
          renderFilterPreviews();
          setEditorBusy(false);
        });
      });

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
          editorState.dragging = false;
          editorState.dragOrigin = null;
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
          editorState.dragging = false;
          editorState.dragOrigin = null;
        });
      }
    }

    // Escape closes editor (guards with visibility check, coexists with modal.js)
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && overlay && !overlay.classList.contains('lcars-hidden')) {
        closeEditor();
      }
    });

    // Web-native files go straight to the editor; everything else is sent to
    // the server for conversion first, then the returned JPEG opens the editor.
    fileInput.addEventListener('change', function() {
      var file = this.files[0];
      if (!file) return;
      this.value = '';
      if (isWebNative(file)) {
        openEditor(file);
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
      openEditor(new File([blob], stem + '.jpg', {type: 'image/jpeg'}));
    })
    .catch(function(err) {
      if (converting) converting.classList.add('lcars-hidden');
      alert('Could not convert image: ' + err);
    });
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
    removeBtn.onclick = function() { item.remove(); };

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

    item.appendChild(img);
    item.appendChild(removeBtn);
    item.appendChild(copyBtn);
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

    item.appendChild(img);
    item.appendChild(removeBtn);
    item.appendChild(copyBtn);
    item.appendChild(hidden);
    container.appendChild(item);
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
      }
    });
  }
})();
