(() => {
  "use strict";

  const STORAGE_KEY = "jarvis-map-visible";
  const DEFAULT_CENTER = [20, 0];
  const DEFAULT_ZOOM = 2;
  const PREVIEW_ZOOM = 13;

  let map = null;
  let markerLayer = null;
  let userMarker = null;
  let accuracyCircle = null;
  let userLocation = null;
  let expanded = false;
  let initialized = false;
  const markers = new Map();

  const createElement = (tag, attributes = {}, text = "") => {
    const node = document.createElement(tag);
    Object.entries(attributes).forEach(([key, value]) => {
      if (key === "class") node.className = value;
      else node.setAttribute(key, value);
    });
    if (text) node.textContent = text;
    return node;
  };

  const escapeHtml = (value) => String(value)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  function setStatus(text) {
    const node = document.getElementById("jarvisMapStatus");
    if (node) node.textContent = text;
  }

  function ensureUI() {
    if (document.getElementById("jarvisMapWidget")) return;

    const toggle = createElement("button", { id: "jarvisMapToggle", type: "button", title: "Toggle Jarvis Maps" }, "MAP");
    const widget = createElement("section", { id: "jarvisMapWidget", "aria-label": "Jarvis map" });
    const header = createElement("div", { class: "jarvis-map-header" });
    const title = createElement("div", { class: "jarvis-map-title" }, "JARVIS / MAP");
    const status = createElement("div", { id: "jarvisMapStatus", class: "jarvis-map-status" }, "LOCATING...");
    const controls = createElement("div", { class: "jarvis-map-controls" });
    const expand = createElement("button", { id: "jarvisMapExpand", class: "jarvis-map-button", type: "button" }, "EXPAND");
    const close = createElement("button", { id: "jarvisMapClose", class: "jarvis-map-button", type: "button" }, "×");
    const canvas = createElement("div", { id: "jarvisMapCanvas", class: "jarvis-map-canvas" });
    const results = createElement("div", { id: "jarvisMapResults", class: "jarvis-map-results" });

    controls.append(expand, close);
    header.append(title, status, controls);
    widget.append(header, canvas, results);
    document.body.append(toggle, widget);

    toggle.addEventListener("click", (event) => { event.stopPropagation(); toggleVisibility(); });
    expand.addEventListener("click", (event) => { event.stopPropagation(); setExpanded(!expanded); });
    close.addEventListener("click", (event) => { event.stopPropagation(); setExpanded(false); });
    widget.addEventListener("click", (event) => {
      if (!expanded && !event.target.closest("button")) setExpanded(true);
    });
  }

  function toggleVisibility() {
    const widget = document.getElementById("jarvisMapWidget");
    if (!widget) return;
    const visible = widget.classList.toggle("map-visible");
    localStorage.setItem(STORAGE_KEY, visible ? "1" : "0");
    if (visible) {
      initMap();
      requestAnimationFrame(() => map?.invalidateSize());
    }
  }

  function setExpanded(value) {
    expanded = Boolean(value);
    const widget = document.getElementById("jarvisMapWidget");
    if (!widget) return;
    widget.classList.toggle("map-expanded", expanded);
    const button = document.getElementById("jarvisMapExpand");
    if (button) button.textContent = expanded ? "PREVIEW" : "EXPAND";
    initMap();
    requestAnimationFrame(() => {
      map?.invalidateSize();
      if (expanded && userLocation) map?.setView([userLocation.lat, userLocation.lon], Math.max(map.getZoom(), PREVIEW_ZOOM));
    });
  }

  function locateUser() {
    if (!navigator.geolocation) { setStatus("LOCATION UNAVAILABLE"); return; }
    const success = (position) => {
      const { latitude, longitude, accuracy } = position.coords;
      userLocation = { lat: latitude, lon: longitude, accuracy: Number.isFinite(accuracy) ? accuracy : null };
      setStatus(`${latitude.toFixed(4)}, ${longitude.toFixed(4)}`);
      if (!map || !window.L) return;
      if (!userMarker) {
        userMarker = L.circleMarker([latitude, longitude], { radius: 7, className: "jarvis-user-marker", weight: 2, fillOpacity: 0.9 }).addTo(map);
        userMarker.bindTooltip("YOU", { permanent: true, direction: "top", offset: [0, -8], className: "jarvis-user-label" });
      } else userMarker.setLatLng([latitude, longitude]);
      if (accuracyCircle) { accuracyCircle.setLatLng([latitude, longitude]); accuracyCircle.setRadius(accuracy || 20); }
      else accuracyCircle = L.circle([latitude, longitude], { radius: accuracy || 20, className: "jarvis-accuracy" }).addTo(map);
      if (!expanded && markers.size === 0) map.setView([latitude, longitude], PREVIEW_ZOOM);
    };
    navigator.geolocation.getCurrentPosition(success, () => setStatus("LOCATION DENIED"), { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 });
    navigator.geolocation.watchPosition(success, () => {}, { enableHighAccuracy: true, timeout: 15000, maximumAge: 10000 });
  }

  function initMap() {
    if (initialized || !window.L) return;
    const canvas = document.getElementById("jarvisMapCanvas");
    if (!canvas) return;
    initialized = true;
    map = L.map(canvas, { zoomControl: true, worldCopyJump: true, minZoom: 2 }).setView(DEFAULT_CENTER, DEFAULT_ZOOM);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "&copy; OpenStreetMap contributors" }).addTo(map);
    markerLayer = L.layerGroup().addTo(map);
    locateUser();
    setStatus("MAP ONLINE");
  }

  function popupHtml(marker) {
    const distance = marker.distance_km == null ? "" : marker.distance_km < 1 ? `${Math.round(marker.distance_km * 1000)} m away` : `${marker.distance_km.toFixed(2)} km away`;
    return `<div class="jarvis-map-popup"><strong>${escapeHtml(marker.name || "Unknown place")}</strong>${distance ? `<br>${distance}` : ""}${marker.address ? `<br>${escapeHtml(marker.address)}` : ""}${marker.opening_hours ? `<br>Hours: ${escapeHtml(marker.opening_hours)}` : ""}${marker.cuisine ? `<br>Cuisine: ${escapeHtml(marker.cuisine)}` : ""}</div>`;
  }

  function focusMarker(marker) {
    initMap();
    if (!map) return;
    setExpanded(true);
    map.setView([marker.lat, marker.lon], 17);
    marker.layer?.openPopup?.();
  }

  function renderResults() {
    const results = document.getElementById("jarvisMapResults");
    if (!results) return;
    results.innerHTML = "";
    results.classList.toggle("has-results", markers.size > 0);
    markers.forEach((marker) => {
      const item = createElement("button", { class: "jarvis-map-result", type: "button" });
      const distance = marker.distance_km < 1 ? `${Math.round(marker.distance_km * 1000)} m` : `${marker.distance_km.toFixed(2)} km`;
      item.innerHTML = `<span class="jarvis-map-result-name">${escapeHtml(marker.name)}</span><span class="jarvis-map-result-distance">${distance}</span>`;
      item.addEventListener("click", () => focusMarker(marker));
      results.appendChild(item);
    });
  }

  function setMarkers(payload) {
    initMap();
    if (!map || !markerLayer) return;
    if (payload.replace !== false) { markerLayer.clearLayers(); markers.clear(); }
    (payload.markers || []).forEach((marker) => {
      const id = marker.id || `${marker.lat}:${marker.lon}:${marker.name}`;
      const pin = L.marker([marker.lat, marker.lon], { title: marker.name || "Place" }).bindPopup(popupHtml(marker)).addTo(markerLayer);
      pin.on("click", () => { setExpanded(true); map.setView([marker.lat, marker.lon], Math.max(map.getZoom(), 16)); });
      markers.set(id, { ...marker, id, layer: pin });
    });
    renderResults();
    if (markers.size) {
      const bounds = L.latLngBounds(Array.from(markers.values()).map((marker) => [marker.lat, marker.lon]));
      if (userLocation) bounds.extend([userLocation.lat, userLocation.lon]);
      map.fitBounds(bounds.pad(0.15), { maxZoom: 15 });
    }
    setExpanded(true);
  }

  function clearMarkers(category = "") {
    if (!markerLayer) return;
    const wanted = String(category).trim().toLowerCase();
    if (!wanted) { markerLayer.clearLayers(); markers.clear(); renderResults(); return; }
    markers.forEach((marker) => {
      if (String(marker.category || "").toLowerCase() === wanted) { markerLayer.removeLayer(marker.layer); markers.delete(marker.id); }
    });
    renderResults();
  }

  function handleAction(payload) {
    if (!payload?.action) return;
    if (payload.action === "set_markers") setMarkers(payload);
    else if (payload.action === "clear_markers") clearMarkers(payload.category);
    else if (payload.action === "focus_marker") focusMarker({ lat: payload.latitude, lon: payload.longitude, name: payload.name || "" });
  }

  function getContext() {
    const widget = document.getElementById("jarvisMapWidget");
    const context = {
      open: expanded,
      visible: !!widget?.classList.contains("map-visible"),
      latitude: userLocation?.lat ?? null,
      longitude: userLocation?.lon ?? null,
      accuracy_m: userLocation?.accuracy ?? null,
      zoom: map?.getZoom?.() ?? null,
      marker_count: markers.size,
      markers: Array.from(markers.values()).slice(0, 20).map((marker) => ({ id: marker.id, name: marker.name, latitude: marker.lat, longitude: marker.lon, category: marker.category, distance_km: marker.distance_km })),
    };
    if (map) {
      const bounds = map.getBounds();
      context.bounds = { north: bounds.getNorth(), south: bounds.getSouth(), east: bounds.getEast(), west: bounds.getWest() };
    }
    return context;
  }

  window.JarvisMap = { toggle: toggleVisibility, open() { ensureUI(); document.getElementById("jarvisMapWidget")?.classList.add("map-visible"); localStorage.setItem(STORAGE_KEY, "1"); initMap(); }, close() { document.getElementById("jarvisMapWidget")?.classList.remove("map-visible"); localStorage.setItem(STORAGE_KEY, "0"); }, expand: () => setExpanded(true), collapse: () => setExpanded(false), getContext, handleAction, clear: clearMarkers, focus: focusMarker };

  document.addEventListener("DOMContentLoaded", () => {
    ensureUI();
    if (localStorage.getItem(STORAGE_KEY) === "1") { document.getElementById("jarvisMapWidget")?.classList.add("map-visible"); initMap(); }
  });
})();
