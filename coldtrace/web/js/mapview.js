// Leaflet wrapper: bright basemap (config-driven tile provider, see /api/ref/config) plus a route
// polyline, hub markers, and a truck marker.
const MapView = (() => {
  let map, routeLine, truckMarker, hubLayer, destMarker, tileConfig = null;

  async function ensure(containerId) {
    if (map) return map;
    if (!tileConfig) {
      try { tileConfig = await API.get('/api/ref/config'); }
      catch { tileConfig = { map_tile_url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', map_attribution: '', map_max_zoom: 19 }; }
    }
    map = L.map(containerId, { zoomControl: true, attributionControl: true, preferCanvas: true }).setView([19.5, 76], 6);
    L.tileLayer(tileConfig.map_tile_url, {
      subdomains: 'abc', maxZoom: tileConfig.map_max_zoom || 19, crossOrigin: true, attribution: tileConfig.map_attribution,
    }).addTo(map);
    hubLayer = L.layerGroup().addTo(map);
    return map;
  }

  function truckIcon(color) {
    return L.divIcon({ className: '', html: `<div style="width:14px;height:14px;border-radius:50%;background:${color};border:2px solid #ffffff;box-shadow:0 0 0 1px ${color},0 2px 4px rgba(15,23,42,.3)"></div>`, iconSize: [14, 14] });
  }

  function drawRoute(points, dest) {
    if (routeLine) routeLine.remove();
    const latlngs = points.map(p => [p[0], p[1]]);
    routeLine = L.polyline(latlngs, { color: '#0d9488', weight: 4, opacity: 0.85 }).addTo(map);
    if (destMarker) destMarker.remove();
    if (dest) destMarker = L.circleMarker([dest.lat, dest.lon], { radius: 6, color: '#ffffff', weight: 2, fillColor: '#475569', fillOpacity: 1 }).bindTooltip(dest.name).addTo(map);
    map.fitBounds(routeLine.getBounds(), { padding: [30, 30] });
  }

  function setTruck(lat, lon, color) {
    if (!truckMarker) truckMarker = L.marker([lat, lon], { icon: truckIcon(color) }).addTo(map);
    else { truckMarker.setLatLng([lat, lon]); truckMarker.setIcon(truckIcon(color)); }
  }

  function setHubs(hubs) {
    hubLayer.clearLayers();
    for (const h of hubs) {
      L.circleMarker([h.lat, h.lon], { radius: 5, color: '#ffffff', weight: 2, fillColor: '#d97706', fillOpacity: 0.95 })
        .bindTooltip(`${h.name} · ${h.drive_km} km`).addTo(hubLayer);
    }
  }

  function destroy() { if (map) { map.remove(); map = null; routeLine = truckMarker = hubLayer = destMarker = null; } }
  return { ensure, drawRoute, setTruck, setHubs, destroy };
})();
