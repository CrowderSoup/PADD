/**
 * New Post page: EasyMDE editor, media upload, and location picker.
 *
 * Depends on editor.js and maps.js (loaded via base.html).
 * Reads the media upload URL from data-upload-url on the file input element.
 */
(function() {
  var ta = document.getElementById('post-content');
  if (!ta) return;

  var easymde = createLcarsEditor(ta, {
    placeholder: 'Write your post in Markdown...',
    minHeight: '250px',
  });

  // Sync editor value into the textarea before the form submits
  var form = document.getElementById('new-post-form');
  if (form) {
    form.addEventListener('submit', function() {
      ta.value = easymde.value();
    });
  }

  // --- Media upload ---

  var fileInput = document.getElementById('media-file-input');
  if (fileInput) {
    var uploadUrl = fileInput.dataset.uploadUrl;
    var csrfToken = JSON.parse(document.body.getAttribute('hx-headers') || '{}')['X-CSRFToken'] || '';

    fileInput.addEventListener('change', function() {
      var file = this.files[0];
      if (!file) return;

      var uploading = document.getElementById('media-uploading');
      uploading.classList.remove('lcars-hidden');

      var formData = new FormData();
      formData.append('file', file);

      fetch(uploadUrl, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken },
        body: formData,
      })
      .then(function(resp) { return resp.json(); })
      .then(function(data) {
        uploading.classList.add('lcars-hidden');
        if (data.url) {
          addMediaThumbnail(data.url, file);
        } else {
          alert('Upload failed: ' + (data.error || 'Unknown error'));
        }
      })
      .catch(function(err) {
        uploading.classList.add('lcars-hidden');
        alert('Upload failed: ' + err);
      });

      this.value = '';
    });
  }

  function addMediaThumbnail(url, file) {
    var container = document.getElementById('media-thumbnails');
    var item = document.createElement('div');
    item.className = 'lcars-media-thumb';

    var img = document.createElement('img');
    img.src = URL.createObjectURL(file);
    img.alt = file.name;

    var removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'lcars-media-thumb-remove';
    removeBtn.innerHTML = '&times;';
    removeBtn.onclick = function() { item.remove(); };

    var hidden = document.createElement('input');
    hidden.type = 'hidden';
    hidden.name = 'photo';
    hidden.value = url;

    item.appendChild(img);
    item.appendChild(removeBtn);
    item.appendChild(hidden);
    container.appendChild(item);
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
