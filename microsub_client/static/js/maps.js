var _LCARS_MAP_TILE = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png';

var _LCARS_MAP_OPTIONS = {
  zoomControl: false,
  attributionControl: false,
  dragging: false,
  scrollWheelZoom: false,
  doubleClickZoom: false,
  boxZoom: false,
  keyboard: false,
  touchZoom: false,
};

function _createLcarsMapPin() {
  return L.divIcon({
    className: 'lcars-map-pin',
    html: '<div class="lcars-map-pin-dot"></div><div class="lcars-map-pin-ring"></div>',
    iconSize: [24, 24],
    iconAnchor: [12, 12],
  });
}

/**
 * Creates a static Leaflet map centered on the given coordinates.
 *
 * @param {HTMLElement|string} element - DOM element or element ID for the map container.
 * @param {number} lat - Latitude.
 * @param {number} lng - Longitude.
 * @returns {L.Map}
 */
function createLcarsMap(element, lat, lng) {
  var map = L.map(element, _LCARS_MAP_OPTIONS).setView([lat, lng], 15);
  L.tileLayer(_LCARS_MAP_TILE, { maxZoom: 19 }).addTo(map);
  L.marker([lat, lng], { icon: _createLcarsMapPin() }).addTo(map);
  return map;
}

/**
 * Initializes static maps for all un-initialized `.lcars-entry-map` elements
 * within the given root. Safe to call multiple times — skips already-initialized maps.
 *
 * @param {Document|HTMLElement} root
 */
function initEntryMaps(root) {
  root.querySelectorAll('.lcars-entry-map:not([data-map-init])').forEach(function(el) {
    el.dataset.mapInit = '1';
    var lat = parseFloat(el.dataset.lat);
    var lng = parseFloat(el.dataset.lng);
    if (!isNaN(lat) && !isNaN(lng)) {
      createLcarsMap(el, lat, lng);
    }
  });
}
