// photo-gl.js — WebGL photo renderer for Safari-compatible filter application.
// Creates a WebGL rendering context on a canvas and applies image adjustments
// via GLSL uniforms, bypassing ctx.filter which is unreliable on Safari.
//
// Usage:
//   createPhotoGL(canvasElement)  → renderer | null  (attach to existing canvas)
//   createPhotoGL(width, height)  → renderer | null  (creates offscreen canvas)
//
// Returns null if WebGL is unavailable (caller should fall back to 2D ctx.filter).
// Returns: { canvas, render(image, params, totalAngleDeg, uvOffset, uvScale), destroy() }

function createPhotoGL(canvasOrWidth, height) {
  var canvas;
  if (typeof canvasOrWidth === 'number') {
    canvas = document.createElement('canvas');
    canvas.width = canvasOrWidth;
    canvas.height = height || canvasOrWidth;
  } else {
    canvas = canvasOrWidth;
  }

  var gl = null;
  var program = null;
  var posBuffer = null;
  var texture = null;
  var cachedImage = null;
  var contextLost = false;

  // Offscreen 2D canvas for rotation baking at preview scale.
  // Export always receives angle=0 (bakeRotation was called first), so this
  // is only used during interactive preview — size is bounded to display canvas.
  var rotCanvas = document.createElement('canvas');
  var rotCtx = rotCanvas.getContext('2d');

  // --- Shaders ---

  var VS = [
    'attribute vec2 a_pos;',
    'varying vec2 v_uv;',
    'void main() {',
    '  v_uv = a_pos * 0.5 + 0.5;',
    '  gl_Position = vec4(a_pos, 0.0, 1.0);',
    '}'
  ].join('\n');

  // v_uv: (0,0) = screen bottom-left, (1,1) = screen top-right.
  // Image data: row 0 = top. Flip Y via "1.0 - uv.y" so image displays right-side up.
  // UV crop: uv = u_uv_offset + v_uv * u_uv_scale (full image: offset=(0,0), scale=(1,1)).
  // Application order: brightness → contrast → saturation → sepia → hue →
  //                    highlights/shadows → opacity → sharpness → vignette.
  var FS = [
    'precision mediump float;',
    'varying vec2 v_uv;',
    'uniform sampler2D u_tex;',
    'uniform float u_brightness;',
    'uniform float u_contrast;',
    'uniform float u_saturation;',
    'uniform float u_sepia;',
    'uniform float u_hue;',
    'uniform float u_opacity;',
    'uniform float u_highlights;',
    'uniform float u_shadows;',
    'uniform float u_vignette;',
    'uniform float u_sharpness;',
    'uniform vec2 u_uv_offset;',
    'uniform vec2 u_uv_scale;',
    'uniform vec2 u_texel_size;',
    '',
    // W3C hue-rotate matrix via dot products (avoids GLSL mat3 column-major confusion)
    'vec3 applyHue(vec3 col, float angle) {',
    '  float c = cos(angle), s = sin(angle);',
    '  return clamp(vec3(',
    '    dot(col, vec3(0.213+c*0.787-s*0.213, 0.715-c*0.715-s*0.715, 0.072-c*0.072+s*0.928)),',
    '    dot(col, vec3(0.213-c*0.213+s*0.143, 0.715+c*0.285+s*0.140, 0.072-c*0.072-s*0.283)),',
    '    dot(col, vec3(0.213-c*0.213-s*0.787, 0.715-c*0.715+s*0.715, 0.072+c*0.928+s*0.072))',
    '  ), 0.0, 1.0);',
    '}',
    '',
    'void main() {',
    '  vec2 uv = u_uv_offset + v_uv * u_uv_scale;',
    '  vec2 texUV = vec2(uv.x, 1.0 - uv.y);',
    '  vec4 src = texture2D(u_tex, texUV);',
    '  vec3 col = src.rgb;',
    // brightness: multiply all channels
    '  col = col * u_brightness;',
    // contrast: (c - 0.5) * contrast + 0.5  [matte: (c-0.5)*0.8+0.5 = 0.8c+0.1]
    '  col = (col - 0.5) * u_contrast + 0.5;',
    // saturation: lerp(luminance, color, saturation)
    '  float lum = dot(col, vec3(0.2126, 0.7152, 0.0722));',
    '  col = mix(vec3(lum), col, u_saturation);',
    // sepia: blend toward W3C sepia matrix
    '  vec3 sepia = clamp(vec3(',
    '    dot(col, vec3(0.393, 0.769, 0.189)),',
    '    dot(col, vec3(0.349, 0.686, 0.168)),',
    '    dot(col, vec3(0.272, 0.534, 0.131))',
    '  ), 0.0, 1.0);',
    '  col = mix(col, sepia, u_sepia);',
    // hue rotation
    '  col = applyHue(col, u_hue);',
    // highlights: additive push on bright pixels only (negative = recover, positive = boost)
    '  float lum2 = dot(col, vec3(0.2126, 0.7152, 0.0722));',
    '  col = col + u_highlights * smoothstep(0.5, 1.0, lum2) * 0.5;',
    // shadows: additive push on dark pixels only (positive = lift, negative = crush)
    '  col = col + u_shadows * (1.0 - smoothstep(0.0, 0.5, lum2)) * 0.5;',
    // opacity: mix(white, col, opacity) — creates fade-toward-white effect
    '  col = mix(vec3(1.0), col, u_opacity);',
    // sharpness: unsharp mask — high-freq detail from original + adjusted color
    '  vec3 blur = (',
    '    texture2D(u_tex, texUV + vec2(-u_texel_size.x, 0.0)).rgb +',
    '    texture2D(u_tex, texUV + vec2( u_texel_size.x, 0.0)).rgb +',
    '    texture2D(u_tex, texUV + vec2(0.0, -u_texel_size.y)).rgb +',
    '    texture2D(u_tex, texUV + vec2(0.0,  u_texel_size.y)).rgb',
    '  ) * 0.25;',
    '  col += (src.rgb - blur) * u_sharpness;',
    // vignette: darken edges toward black (elliptical, follows canvas shape)
    '  float vig = smoothstep(0.25, 0.75, length(v_uv - vec2(0.5)));',
    '  col = mix(col, vec3(0.0), vig * u_vignette);',
    '  gl_FragColor = vec4(clamp(col, 0.0, 1.0), src.a);',
    '}'
  ].join('\n');

  // --- WebGL setup ---

  function compileShader(type, src) {
    var s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      console.error('photo-gl shader compile error:', gl.getShaderInfoLog(s));
      gl.deleteShader(s);
      return null;
    }
    return s;
  }

  function init() {
    // preserveDrawingBuffer required so canvas.toBlob() can read the framebuffer
    var opts = { preserveDrawingBuffer: true };
    gl = canvas.getContext('webgl', opts) ||
         canvas.getContext('experimental-webgl', opts);
    if (!gl) return false;

    var vs = compileShader(gl.VERTEX_SHADER, VS);
    var fs = compileShader(gl.FRAGMENT_SHADER, FS);
    if (!vs || !fs) { gl = null; return false; }

    program = gl.createProgram();
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    gl.deleteShader(vs);
    gl.deleteShader(fs);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      console.error('photo-gl program link error:', gl.getProgramInfoLog(program));
      gl = null;
      return false;
    }

    // Full-screen quad: two triangles covering [-1,1]×[-1,1] clip space
    posBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, posBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
      -1, -1,  1, -1, -1,  1,
      -1,  1,  1, -1,  1,  1
    ]), gl.STATIC_DRAW);

    texture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);

    cachedImage = null;
    return true;
  }

  if (!init()) return null;

  canvas.addEventListener('webglcontextlost', function(e) {
    e.preventDefault();
    contextLost = true;
  });
  canvas.addEventListener('webglcontextrestored', function() {
    contextLost = false;
    cachedImage = null;
    init();
  });

  // --- Render ---

  function render(image, params, totalAngleDeg, uvOffset, uvScale) {
    if (contextLost || !gl || !image) return;

    var texSource = image;
    var angle = totalAngleDeg || 0;

    if (angle !== 0) {
      // Bake rotation into an offscreen 2D canvas, scaled to display canvas size
      // for performance (only used during interactive preview; export uses angle=0).
      var rad = angle * Math.PI / 180;
      var sin = Math.abs(Math.sin(rad));
      var cos = Math.abs(Math.cos(rad));
      var rw = image.naturalWidth * cos + image.naturalHeight * sin;
      var rh = image.naturalWidth * sin + image.naturalHeight * cos;
      var s = Math.min(canvas.width / rw, canvas.height / rh, 1);
      var dw = Math.max(1, Math.round(rw * s));
      var dh = Math.max(1, Math.round(rh * s));
      rotCanvas.width = dw;
      rotCanvas.height = dh;
      rotCtx.save();
      rotCtx.translate(dw / 2, dh / 2);
      rotCtx.rotate(rad);
      rotCtx.drawImage(
        image,
        -image.naturalWidth * s / 2, -image.naturalHeight * s / 2,
        image.naturalWidth * s, image.naturalHeight * s
      );
      rotCtx.restore();
      texSource = rotCanvas;
      cachedImage = null; // rotCanvas mutates each call; always re-upload
    }

    if (texSource !== cachedImage) {
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, texSource);
      cachedImage = texSource;
    }

    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.useProgram(program);

    var posLoc = gl.getAttribLocation(program, 'a_pos');
    gl.bindBuffer(gl.ARRAY_BUFFER, posBuffer);
    gl.enableVertexAttribArray(posLoc);
    gl.vertexAttribPointer(posLoc, 2, gl.FLOAT, false, 0, 0);

    var p = params || {};
    gl.uniform1i(gl.getUniformLocation(program, 'u_tex'), 0);
    gl.uniform1f(gl.getUniformLocation(program, 'u_brightness'),
      p.brightness !== undefined ? p.brightness : 1.0);
    gl.uniform1f(gl.getUniformLocation(program, 'u_contrast'),
      p.contrast  !== undefined ? p.contrast  : 1.0);
    gl.uniform1f(gl.getUniformLocation(program, 'u_saturation'),
      p.saturation !== undefined ? p.saturation : 1.0);
    gl.uniform1f(gl.getUniformLocation(program, 'u_sepia'),
      p.sepia !== undefined ? p.sepia : 0.0);
    gl.uniform1f(gl.getUniformLocation(program, 'u_hue'),
      p.hue !== undefined ? p.hue : 0.0);
    gl.uniform1f(gl.getUniformLocation(program, 'u_opacity'),
      p.opacity !== undefined ? p.opacity : 1.0);
    gl.uniform1f(gl.getUniformLocation(program, 'u_highlights'),
      p.highlights !== undefined ? p.highlights : 0.0);
    gl.uniform1f(gl.getUniformLocation(program, 'u_shadows'),
      p.shadows !== undefined ? p.shadows : 0.0);
    gl.uniform1f(gl.getUniformLocation(program, 'u_vignette'),
      p.vignette !== undefined ? p.vignette : 0.0);
    gl.uniform1f(gl.getUniformLocation(program, 'u_sharpness'),
      p.sharpness !== undefined ? p.sharpness : 0.0);
    var us = uvScale || [1.0, 1.0];
    gl.uniform2fv(gl.getUniformLocation(program, 'u_uv_offset'),
      uvOffset || [0.0, 0.0]);
    gl.uniform2fv(gl.getUniformLocation(program, 'u_uv_scale'), us);
    // texel size = 1 output pixel in texture UV space (for unsharp mask)
    gl.uniform2fv(gl.getUniformLocation(program, 'u_texel_size'),
      [us[0] / canvas.width, us[1] / canvas.height]);

    gl.drawArrays(gl.TRIANGLES, 0, 6);
  }

  function destroy() {
    if (gl) {
      if (texture)   { gl.deleteTexture(texture);   texture   = null; }
      if (posBuffer) { gl.deleteBuffer(posBuffer);   posBuffer = null; }
      if (program)   { gl.deleteProgram(program);    program   = null; }
    }
    gl = null;
    cachedImage = null;
  }

  return { canvas: canvas, render: render, destroy: destroy };
}
