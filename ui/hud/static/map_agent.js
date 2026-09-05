(() => {
  "use strict";

  const STORAGE_KEY = "jarvis-map-visible";
  const DEFAULT_CENTER = [20, 0];
  const DEFAULT_ZOOM = 2;
  const PREVIEW_ZOOM = 13;
  const MARKER_ZOOM = 17;

  let map = null;
  let markerLayer = null;
  let userMarker = null;
  let accuracyCircle = null;
  let userLocation = null;
  let expanded = false;
  let initialized = false;
  let watchId = null;

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

  const escapeHtml = (value) =>
    String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");

  const haversineKm = (aLat, aLon, bLat, bLon) => {
    const lat1 = Number(aLat);
    const lon1 = Number(aLon);
    const lat2 = Number(bLat);
    const lon2 = Number(bLon);

    if (![lat1, lon1, lat2, lon2].every(Number.isFinite)) return null;

    const rad = Math.PI / 180;
    const dLat = (lat2 - lat1) * rad;
    const dLon = (lon2 - lon1) * rad;
    const x =
      Math.sin(dLat / 2) ** 2 +
      Math.cos(lat1 * rad) *
        Math.cos(lat2 * rad) *
        Math.sin(dLon / 2) ** 2;

    return 6371 * 2 * Math.asin(Math.sqrt(Math.min(1, x)));
  };

  const distanceFor = (marker) =>
    haversineKm(
      userLocation?.lat,
      userLocation?.lon,
      marker?.lat,
      marker?.lon
    );

  const normalizeMarker = (marker) => {
    const lat = Number(marker?.lat);
    const lon = Number(marker?.lon);

    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;

    const normalized = {
      ...marker,
      lat,
      lon,
    };

    const calculated = distanceFor(normalized);

    if (calculated !== null) {
      normalized.distance_km = calculated;
    } else if (!Number.isFinite(Number(normalized.distance_km))) {
      normalized.distance_km = null;
    }

    normalized.id =
      marker.id ||
      `${lat}:${lon}:${String(marker.name || "place").trim()}`;

    return normalized;
  };

  const formatDistance = (distance) => {
    /*
     * Number(null) is 0, not NaN, so Number.isFinite(Number(null)) is
     * true -- a plain finite-check alone doesn't actually filter out a
     * missing distance. This regressed when normalizeMarker's
     * client-side haversine calculation was added: distanceFor()
     * legitimately returns null whenever userLocation isn't available
     * yet (geolocation permission not granted, not resolved yet, or an
     * insecure/non-localhost context where navigator.geolocation is
     * unavailable at all), and normalizeMarker passes that null
     * straight through when the marker's own backend-provided
     * distance_km also isn't a valid number -- which is always the
     * case for a reverse-geocoded map click, since Nominatim reverse
     * geocoding has no "distance from the user" concept at all. Without
     * this guard, every such marker silently displayed "0 m" instead of
     * omitting the distance.
     */
    if (distance === null || distance === undefined) return "Distance unavailable";
    if (!Number.isFinite(Number(distance))) return "Distance unavailable";
    const km = Number(distance);
    return km < 1
      ? `${Math.round(km * 1000)} m`
      : `${km.toFixed(2)} km`;
  };

  const normalizeUrl = (value) => {
    const raw = String(value || "").trim();
    if (!raw) return "";

    try {
      const url = new URL(raw, window.location.href);
      return ["http:", "https:"].includes(url.protocol) ? url.href : "";
    } catch {
      return "";
    }
  };

  function setStatus(text) {
    const node = document.getElementById("jarvisMapStatus");
    if (node) node.textContent = text;
  }

  function sendToBackend(payload) {
    const socket = window.JarvisSocket;
    const wrap = document.getElementById("wrap");

    if (
      socket &&
      socket.readyState === WebSocket.OPEN &&
      wrap?.dataset.authenticated === "true"
    ) {
      socket.send(JSON.stringify(payload));
      return true;
    }

    return false;
  }

  function ensureUI() {
    if (document.getElementById("jarvisMapWidget")) return;

    const toggle = createElement(
      "button",
      {
        id: "jarvisMapToggle",
        type: "button",
        title: "Toggle Jarvis Maps",
      },
      "MAP"
    );

    const widget = createElement("section", {
      id: "jarvisMapWidget",
      "aria-label": "Jarvis map",
    });

    const header = createElement("div", {
      class: "jarvis-map-header",
    });

    const title = createElement(
      "div",
      { class: "jarvis-map-title" },
      "JARVIS / MAP"
    );

    const status = createElement(
      "div",
      {
        id: "jarvisMapStatus",
        class: "jarvis-map-status",
      },
      "LOCATING..."
    );

    const controls = createElement("div", {
      class: "jarvis-map-controls",
    });

    const expand = createElement(
      "button",
      {
        id: "jarvisMapExpand",
        class: "jarvis-map-button",
        type: "button",
      },
      "EXPAND"
    );

    const close = createElement(
      "button",
      {
        id: "jarvisMapClose",
        class: "jarvis-map-button",
        type: "button",
      },
      "×"
    );

    const mapContainer = createElement("div", {
      id: "jarvisMapCanvas",
      class: "jarvis-map-canvas",
    });

    const searchForm = createElement("form", {
      id: "jarvisMapSearchForm",
      class: "jarvis-map-search",
    });

    const searchInput = createElement("input", {
      id: "jarvisMapSearchInput",
      type: "text",
      placeholder: 'Search places, e.g. "coffee" or an address...',
      "aria-label": "Search the map",
      autocomplete: "off",
    });

    const searchButton = createElement(
      "button",
      {
        id: "jarvisMapSearchButton",
        type: "submit",
      },
      "SEARCH"
    );

    searchForm.append(searchInput, searchButton);

    const results = createElement("div", {
      id: "jarvisMapResults",
      class: "jarvis-map-results",
    });

    const details = createElement("aside", {
      id: "jarvisMapDetails",
      class: "jarvis-map-details",
      "aria-label": "Selected location details",
      hidden: "true",
    });

    controls.append(expand, close);
    header.append(title, status, controls);
    widget.append(header, searchForm, mapContainer, results, details);
    document.body.append(toggle, widget);

    toggle.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleVisibility();
    });

    expand.addEventListener("click", (event) => {
      event.stopPropagation();
      setExpanded(!expanded);
    });

    close.addEventListener("click", (event) => {
      event.stopPropagation();
      if (expanded) setExpanded(false);
      else toggleVisibility();
    });

    searchForm.addEventListener("submit", (event) => {
      event.preventDefault();
      event.stopPropagation();
      submitSearch(searchInput.value);
    });

    widget.addEventListener("click", (event) => {
      if (
        !expanded &&
        !event.target.closest("button") &&
        !event.target.closest("form") &&
        !event.target.closest(".jarvis-map-result") &&
        !event.target.closest(".jarvis-map-details")
      ) {
        setExpanded(true);
      }
    });
  }

  function revealMapWidget() {
    ensureUI();

    const widget = document.getElementById("jarvisMapWidget");
    widget?.classList.add("map-visible");
    localStorage.setItem(STORAGE_KEY, "1");

    initMap();

    requestAnimationFrame(() => map?.invalidateSize());
  }

  function toggleVisibility() {
    ensureUI();

    const widget = document.getElementById("jarvisMapWidget");
    if (!widget) return;

    const visible = widget.classList.toggle("map-visible");

    localStorage.setItem(STORAGE_KEY, visible ? "1" : "0");

    if (visible) {
      initMap();
      requestAnimationFrame(() => map?.invalidateSize());
    }
  }

  function setExpanded(value, options = {}) {
    const nextExpanded = Boolean(value);
    const preserveView = options.preserveView === true;
    const centerOnUser =
      options.centerOnUser === true ||
      (!preserveView && nextExpanded && !expanded);

    expanded = nextExpanded;
    ensureUI();

    const widget = document.getElementById("jarvisMapWidget");
    if (!widget) return;

    widget.classList.toggle("map-expanded", expanded);

    const button = document.getElementById("jarvisMapExpand");
    if (button) button.textContent = expanded ? "PREVIEW" : "EXPAND";

    initMap();

    requestAnimationFrame(() => {
      if (!map) return;

      map.invalidateSize();

      if (expanded && centerOnUser && userLocation) {
        map.setView(
          [userLocation.lat, userLocation.lon],
          Math.max(map.getZoom(), PREVIEW_ZOOM)
        );
      }
    });
  }

  function refreshMarkerDistances() {
    markers.forEach((marker) => {
      const distance = distanceFor(marker);
      marker.distance_km = distance;
      if (marker.layer) {
        marker.layer.setPopupContent(popupHtml(marker));
      }
    });

    renderResults();

    const details = document.getElementById("jarvisMapDetails");
    const selectedId = details?.dataset.markerId;

    if (selectedId && markers.has(selectedId)) {
      showDetails(markers.get(selectedId));
    }
  }

  function updateUserVisuals() {
    if (!map || !window.L || !userLocation) return;

    const latLng = [userLocation.lat, userLocation.lon];

    if (!userMarker) {
      userMarker = L.circleMarker(latLng, {
        radius: 7,
        className: "jarvis-user-marker",
        weight: 2,
        fillOpacity: 0.9,
      }).addTo(map);

      userMarker.bindTooltip("YOU", {
        permanent: true,
        direction: "top",
        offset: [0, -8],
        className: "jarvis-user-label",
      });
    } else {
      userMarker.setLatLng(latLng);
    }

    if (!accuracyCircle) {
      accuracyCircle = L.circle(latLng, {
        radius: userLocation.accuracy || 20,
        className: "jarvis-accuracy",
      }).addTo(map);
    } else {
      accuracyCircle.setLatLng(latLng);
      accuracyCircle.setRadius(userLocation.accuracy || 20);
    }

    refreshMarkerDistances();

    if (!expanded && markers.size === 0) {
      map.setView(latLng, PREVIEW_ZOOM);
    }
  }

  function locateUser() {
    if (!navigator.geolocation) {
      setStatus("LOCATION UNAVAILABLE");
      return;
    }

    const success = (position) => {
      userLocation = {
        lat: position.coords.latitude,
        lon: position.coords.longitude,
        accuracy: Number.isFinite(position.coords.accuracy)
          ? position.coords.accuracy
          : null,
      };

      setStatus(
        `${userLocation.lat.toFixed(4)}, ${userLocation.lon.toFixed(4)}`
      );

      updateUserVisuals();
    };

    navigator.geolocation.getCurrentPosition(
      success,
      () => setStatus("LOCATION DENIED"),
      {
        enableHighAccuracy: true,
        timeout: 10000,
        maximumAge: 30000,
      }
    );

    if (watchId === null) {
      watchId = navigator.geolocation.watchPosition(
        success,
        () => {},
        {
          enableHighAccuracy: true,
          timeout: 15000,
          maximumAge: 10000,
        }
      );
    }
  }

  function initMap() {
    if (initialized) return;

    if (!window.L) {
      setStatus("MAP LIBRARY OFFLINE");
      return;
    }

    ensureUI();

    const mapContainer = document.getElementById("jarvisMapCanvas");
    if (!mapContainer) return;

    if (mapContainer.tagName === "CANVAS") {
      const replacement = document.createElement("div");
      replacement.id = "jarvisMapCanvas";
      replacement.className = "jarvis-map-canvas";
      mapContainer.replaceWith(replacement);
    }

    const container = document.getElementById("jarvisMapCanvas");

    map = L.map(container, {
      zoomControl: true,
      worldCopyJump: true,
      minZoom: 2,
    }).setView(DEFAULT_CENTER, DEFAULT_ZOOM);

    L.tileLayer(
      "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
      {
        maxZoom: 19,
        attribution: "&copy; OpenStreetMap contributors",
      }
    ).addTo(map);

    markerLayer = L.layerGroup().addTo(map);

    map.on("click", (event) => {
      reverseGeocodeClick(event.latlng.lat, event.latlng.lng);
    });

    initialized = true;
    locateUser();
    setStatus("MAP ONLINE");
  }

  function popupHtml(marker) {
    const distance = Number.isFinite(Number(marker.distance_km))
      ? formatDistance(marker.distance_km)
      : "";

    return `
      <div class="jarvis-map-popup">
        <strong>${escapeHtml(marker.name || "Unknown place")}</strong>
        ${distance ? `<br>${escapeHtml(distance)} away` : ""}
        ${
          marker.address
            ? `<br>${escapeHtml(marker.address)}`
            : ""
        }
        ${
          marker.opening_hours
            ? `<br>Hours: ${escapeHtml(marker.opening_hours)}`
            : ""
        }
        ${
          marker.cuisine
            ? `<br>Cuisine: ${escapeHtml(marker.cuisine)}`
            : ""
        }
      </div>
    `;
  }

  function closeDetails() {
    const details = document.getElementById("jarvisMapDetails");
    if (!details) return;

    details.hidden = true;
    details.dataset.markerId = "";
    details.innerHTML = "";
  }

  function showDetails(marker) {
    const details = document.getElementById("jarvisMapDetails");
    if (!details) return;

    const name = marker.name || "Unknown place";
    const distance = Number.isFinite(Number(marker.distance_km))
      ? formatDistance(marker.distance_km)
      : "Distance unavailable";

    const website = normalizeUrl(marker.website);
    const phone = String(marker.phone || "").trim();
    const address = String(marker.address || "").trim();
    const hours = String(marker.opening_hours || "").trim();
    const cuisine = String(marker.cuisine || "").trim();
    const type = String(marker.type || marker.category || "").trim();

    const lat = Number(marker.lat);
    const lon = Number(marker.lon);
    const hasCoordinates =
      Number.isFinite(lat) && Number.isFinite(lon);

    const destination = hasCoordinates ? `${lat},${lon}` : "";
    const directionsUrl = hasCoordinates
      ? `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(destination)}`
      : "";
    const navigateUrl = hasCoordinates
      ? `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(destination)}&dir_action=navigate`
      : "";

    const osmUrl = hasCoordinates
      ? `https://www.openstreetmap.org/?mlat=${encodeURIComponent(
          lat
        )}&mlon=${encodeURIComponent(
          lon
        )}#map=19/${encodeURIComponent(lat)}/${encodeURIComponent(lon)}`
      : "";

    details.dataset.markerId = marker.id || "";
    details.innerHTML = `
      <div class="jarvis-map-details-header">
        <div>
          <div class="jarvis-map-details-kicker">LOCATION</div>
          <div class="jarvis-map-details-title">${escapeHtml(name)}</div>
        </div>
        <button
          type="button"
          class="jarvis-map-details-close"
          id="jarvisMapDetailsClose"
          aria-label="Close location details"
        >×</button>
      </div>

      <div class="jarvis-map-details-body">
        ${
          type
            ? `<div class="jarvis-map-detail-row"><span>TYPE</span><strong>${escapeHtml(
                type
              )}</strong></div>`
            : ""
        }

        <div class="jarvis-map-detail-row">
          <span>DISTANCE</span>
          <strong>${escapeHtml(distance)}</strong>
        </div>

        ${
          address
            ? `<div class="jarvis-map-detail-row stacked"><span>ADDRESS</span><strong>${escapeHtml(
                address
              )}</strong></div>`
            : ""
        }

        ${
          hours
            ? `<div class="jarvis-map-detail-row stacked"><span>HOURS</span><strong>${escapeHtml(
                hours
              )}</strong></div>`
            : ""
        }

        ${
          cuisine
            ? `<div class="jarvis-map-detail-row stacked"><span>CUISINE</span><strong>${escapeHtml(
                cuisine
              )}</strong></div>`
            : ""
        }

        ${
          phone
            ? `<div class="jarvis-map-detail-row stacked"><span>PHONE</span><strong>${escapeHtml(
                phone
              )}</strong></div>`
            : ""
        }

        ${
          hasCoordinates
            ? `<div class="jarvis-map-detail-row"><span>COORDINATES</span><strong>${lat.toFixed(
                6
              )}, ${lon.toFixed(6)}</strong></div>`
            : ""
        }

        <div class="jarvis-map-detail-actions">
          ${
            directionsUrl
              ? `<a class="jarvis-map-detail-action" href="${escapeHtml(
                  directionsUrl
                )}" target="_blank" rel="noopener noreferrer">DIRECTIONS</a>`
              : ""
          }

          ${
            navigateUrl
              ? `<a class="jarvis-map-detail-action" href="${escapeHtml(
                  navigateUrl
                )}" target="_blank" rel="noopener noreferrer">NAVIGATE</a>`
              : ""
          }

          ${
            website
              ? `<a class="jarvis-map-detail-action" href="${escapeHtml(
                  website
                )}" target="_blank" rel="noopener noreferrer">WEBSITE</a>`
              : ""
          }

          ${
            osmUrl
              ? `<a class="jarvis-map-detail-action" href="${escapeHtml(
                  osmUrl
                )}" target="_blank" rel="noopener noreferrer">OPENSTREETMAP</a>`
              : ""
          }
        </div>
      </div>
    `;

    details.hidden = false;

    document
      .getElementById("jarvisMapDetailsClose")
      ?.addEventListener("click", (event) => {
        event.stopPropagation();
        closeDetails();
      });
  }

  function focusMarker(marker) {
    initMap();
    if (!map || !marker) return;

    const normalized = normalizeMarker(marker);
    if (!normalized) return;

    setExpanded(true, { preserveView: true });

    requestAnimationFrame(() => {
      if (!map) return;

      map.invalidateSize();
      map.setView([normalized.lat, normalized.lon], MARKER_ZOOM, {
        animate: true,
      });

      if (normalized.layer) {
        normalized.layer.openPopup();
      }

      showDetails(normalized);
    });
  }

  function renderResults() {
    const results = document.getElementById("jarvisMapResults");
    if (!results) return;

    results.innerHTML = "";
    results.classList.toggle("has-results", markers.size > 0);

    markers.forEach((marker) => {
      const item = createElement("button", {
        class: "jarvis-map-result",
        type: "button",
      });

      const distance = Number.isFinite(Number(marker.distance_km))
        ? formatDistance(marker.distance_km)
        : "Distance unavailable";

      item.innerHTML = `
        <span class="jarvis-map-result-name">${escapeHtml(
          marker.name || "Unknown place"
        )}</span>
        <span class="jarvis-map-result-distance">${escapeHtml(
          distance
        )}</span>
      `;

      item.addEventListener("click", (event) => {
        event.stopPropagation();
        focusMarker(marker);
      });

      results.appendChild(item);
    });
  }

  function clearMarkers(category = "") {
    if (!markerLayer) {
      markers.clear();
      renderResults();
      closeDetails();
      return;
    }

    const wanted = String(category).trim().toLowerCase();

    if (!wanted) {
      markerLayer.clearLayers();
      markers.clear();
      closeDetails();
      renderResults();
      return;
    }

    markers.forEach((marker) => {
      if (
        String(marker.category || "").trim().toLowerCase() === wanted
      ) {
        markerLayer.removeLayer(marker.layer);
        markers.delete(marker.id);
      }
    });

    closeDetails();
    renderResults();
  }

  function setMarkers(payload) {
    initMap();

    if (!map || !markerLayer) return;

    let data = payload || {};

    if (
      payload?.payload &&
      typeof payload.payload === "object"
    ) {
      data = { ...payload, ...payload.payload };
    }

    const incoming = Array.isArray(data.markers)
      ? data.markers
      : Array.isArray(data.places)
        ? data.places
        : [];

    if (data.replace !== false) {
      markerLayer.clearLayers();
      markers.clear();
      closeDetails();
    }

    incoming.forEach((rawMarker) => {
      const marker = normalizeMarker(rawMarker);
      if (!marker) return;

      const existing = markers.get(marker.id);

      if (existing?.layer) {
        markerLayer.removeLayer(existing.layer);
      }

      const pinIcon = L.divIcon({
        className: "jarvis-place-marker-wrapper",
        html: `
          <div
            class="jarvis-place-marker"
            title="${escapeHtml(marker.name || "Place")}"
          >
            <span></span>
          </div>
        `,
        iconSize: [24, 32],
        iconAnchor: [12, 30],
        popupAnchor: [0, -30],
      });

      const pin = L.marker([marker.lat, marker.lon], {
        title: marker.name || "Place",
        icon: pinIcon,
        keyboard: true,
        zIndexOffset: 1000,
      })
        .bindPopup(popupHtml(marker))
        .addTo(markerLayer);

      marker.layer = pin;

      pin.on("click", (event) => {
        event?.originalEvent?.stopPropagation?.();
        focusMarker(marker);
      });

      markers.set(marker.id, marker);
    });

    renderResults();

    setExpanded(true, { preserveView: true });

    requestAnimationFrame(() => {
      if (!map || !markers.size) return;

      map.invalidateSize();

      const bounds = L.latLngBounds(
        Array.from(markers.values()).map((marker) => [
          marker.lat,
          marker.lon,
        ])
      );

      if (userLocation) {
        bounds.extend([userLocation.lat, userLocation.lon]);
      }

      map.fitBounds(bounds.pad(0.15), {
        maxZoom: 15,
        animate: true,
      });
    });
  }

  function submitSearch(query) {
    const trimmed = String(query || "").trim();
    if (!trimmed) return;

    ensureUI();
    revealMapWidget();

    // A new query starts a new result set immediately.
    // This prevents Search A from remaining visible while Search B loads.
    clearMarkers();

    setExpanded(true, { preserveView: true });
    setStatus(`Searching "${trimmed}"...`);

    // Search around wherever the map is actually showing, not always the
    // device's real-world location. Without this, panning the map away
    // from where you physically are and searching for something you can
    // see on screen would query Overpass around your device's location
    // instead, and silently come back empty.
    const center = map
      ? { lat: map.getCenter().lat, lon: map.getCenter().lng }
      : null;

    if (
      !sendToBackend({
        type: "map_search",
        query: trimmed,
        center,
      })
    ) {
      setStatus("Not connected -- can't search right now.");
    }
  }

  function reverseGeocodeClick(lat, lon) {
    setStatus("Identifying location...");

    if (
      !sendToBackend({
        type: "map_reverse_geocode",
        lat,
        lon,
      })
    ) {
      setStatus("Not connected -- can't identify this location.");
    }
  }

  function handleSearchResult(data) {
    const text = String(data?.text || "").trim();

    if (data?.error) {
      clearMarkers();
      setStatus(String(data.error));
      return;
    }

    if (
      text.toLowerCase().includes("no results") ||
      text.toLowerCase().includes("no places found") ||
      text.toLowerCase().includes("search failed")
    ) {
      clearMarkers();
    }

    setStatus(text || "MAP ONLINE");
  }

  function handleReverseGeocodeResult(data) {
    const raw = data?.marker;

    if (!raw || raw.error) {
      setStatus(raw?.error || "Could not identify this location.");
      return;
    }

    const marker = normalizeMarker(raw);
    if (!marker) {
      setStatus("Invalid location returned.");
      return;
    }

    revealMapWidget();

    // A map click is a selection, not another search result.
    // Replace the previous selection so the list cannot accumulate clicks.
    clearMarkers();

    setMarkers({
      markers: [marker],
      replace: true,
    });

    const stored = markers.get(marker.id);
    if (stored) focusMarker(stored);

    setStatus("MAP ONLINE");
  }

  function handleAction(payload) {
    if (!payload?.action) return;

    if (payload.action === "set_markers") {
      revealMapWidget();
      setMarkers(payload);
      return;
    }

    if (payload.action === "clear_markers") {
      clearMarkers(payload.category);
      return;
    }

    if (payload.action === "focus_marker") {
      revealMapWidget();

      const marker = normalizeMarker({
        lat: payload.latitude,
        lon: payload.longitude,
        name: payload.name || "",
      });

      if (marker) focusMarker(marker);
    }
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
      markers: Array.from(markers.values())
        .slice(0, 20)
        .map((marker) => ({
          id: marker.id,
          name: marker.name,
          latitude: marker.lat,
          longitude: marker.lon,
          category: marker.category,
          distance_km: marker.distance_km,
          address: marker.address,
          opening_hours: marker.opening_hours,
          phone: marker.phone,
          website: marker.website,
          cuisine: marker.cuisine,
          type: marker.type,
        })),
    };

    if (map) {
      const bounds = map.getBounds();

      context.bounds = {
        north: bounds.getNorth(),
        south: bounds.getSouth(),
        east: bounds.getEast(),
        west: bounds.getWest(),
      };
    }

    return context;
  }

  function centerOnUser() {
    if (!map || !userLocation) return;

    map.setView(
      [userLocation.lat, userLocation.lon],
      Math.max(map.getZoom(), PREVIEW_ZOOM),
      { animate: true }
    );
  }

  function showWorld() {
    if (!map) initMap();
    if (!map) return;

    map.setView(DEFAULT_CENTER, DEFAULT_ZOOM, {
      animate: true,
    });
  }

  function zoomMap(direction) {
    if (!map) initMap();
    if (!map) return;

    const next = Math.max(
      2,
      Math.min(19, map.getZoom() + Number(direction || 0))
    );

    map.setZoom(next, { animate: true });
  }

  window.JarvisMap = {
    toggle: toggleVisibility,
    open: revealMapWidget,

    close() {
      const widget = document.getElementById("jarvisMapWidget");
      widget?.classList.remove("map-visible");
      localStorage.setItem(STORAGE_KEY, "0");
    },

    expand: () => setExpanded(true),
    collapse: () => setExpanded(false),
    centerOnUser,
    showWorld,
    zoom: zoomMap,
    getContext,
    handleAction,
    handleSearchResult,
    handleReverseGeocodeResult,
    clear: clearMarkers,
    focus: focusMarker,
  };

  document.addEventListener("DOMContentLoaded", () => {
    ensureUI();

    if (localStorage.getItem(STORAGE_KEY) === "1") {
      document
        .getElementById("jarvisMapWidget")
        ?.classList.add("map-visible");

      initMap();
    }
  });
})();
