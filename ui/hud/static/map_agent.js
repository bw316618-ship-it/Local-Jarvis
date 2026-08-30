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

  const markers = new Map();

  const createElement = (tag, attributes = {}, text = "") => {
    const node = document.createElement(tag);

    Object.entries(attributes).forEach(([key, value]) => {
      if (key === "class") {
        node.className = value;
      } else {
        node.setAttribute(key, value);
      }
    });

    if (text) {
      node.textContent = text;
    }

    return node;
  };

  const escapeHtml = (value) =>
    String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");

  const formatDistance = (distance) => {
    if (!Number.isFinite(Number(distance))) {
      return "";
    }

    const km = Number(distance);

    return km < 1
      ? `${Math.round(km * 1000)} m`
      : `${km.toFixed(2)} km`;
  };

  const normalizeUrl = (value) => {
    const raw = String(value || "").trim();

    if (!raw) {
      return "";
    }

    try {
      const url = new URL(raw, window.location.href);

      if (!["http:", "https:"].includes(url.protocol)) {
        return "";
      }

      return url.href;
    } catch {
      return "";
    }
  };

  function setStatus(text) {
    const node = document.getElementById("jarvisMapStatus");

    if (node) {
      node.textContent = text;
    }
  }

  /*
   * Send a message to the backend over the same authenticated socket
   * hud.js uses for chat -- window.JarvisSocket is the raw WebSocket
   * instance hud.js exposes as soon as a connection opens (see
   * hud.js's connect()). Guarded the same way hud.js guards its own
   * user_message send: socket open AND this device already
   * authenticated, so an unauthenticated or not-yet-connected tab
   * fails quietly rather than throwing.
   */
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
    if (document.getElementById("jarvisMapWidget")) {
      return;
    }

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
      {
        class: "jarvis-map-title",
      },
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

    /*
     * This MUST be a div, not a canvas.
     * Leaflet requires a DOM element as its map container.
     */
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
      placeholder: "Search places, e.g. \"coffee\" or an address...",
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

    widget.append(
      header,
      searchForm,
      mapContainer,
      results,
      details
    );

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

      if (expanded) {
        setExpanded(false);
      } else {
        toggleVisibility();
      }
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

    const widget =
      document.getElementById("jarvisMapWidget");

    widget?.classList.add("map-visible");

    localStorage.setItem(STORAGE_KEY, "1");

    initMap();

    requestAnimationFrame(() => {
      map?.invalidateSize();
    });
  }

  function toggleVisibility() {
    ensureUI();

    const widget =
      document.getElementById("jarvisMapWidget");

    if (!widget) {
      return;
    }

    const visible =
      widget.classList.toggle("map-visible");

    localStorage.setItem(
      STORAGE_KEY,
      visible ? "1" : "0"
    );

    if (visible) {
      initMap();

      requestAnimationFrame(() => {
        map?.invalidateSize();
      });
    }
  }

  function setExpanded(value, options = {}) {
    const nextExpanded = Boolean(value);
    const preserveView =
      options.preserveView === true;

    const centerOnUser =
      options.centerOnUser === true ||
      (
        !preserveView &&
        nextExpanded &&
        !expanded
      );

    expanded = nextExpanded;

    ensureUI();

    const widget =
      document.getElementById("jarvisMapWidget");

    if (!widget) {
      return;
    }

    widget.classList.toggle(
      "map-expanded",
      expanded
    );

    const button =
      document.getElementById("jarvisMapExpand");

    if (button) {
      button.textContent =
        expanded ? "PREVIEW" : "EXPAND";
    }

    initMap();

    requestAnimationFrame(() => {
      if (!map) {
        return;
      }

      map.invalidateSize();

      if (
        expanded &&
        centerOnUser &&
        userLocation
      ) {
        map.setView(
          [
            userLocation.lat,
            userLocation.lon,
          ],
          Math.max(
            map.getZoom(),
            PREVIEW_ZOOM
          )
        );
      }
    });
  }

  function locateUser() {
    if (!navigator.geolocation) {
      setStatus("LOCATION UNAVAILABLE");
      return;
    }

    const success = (position) => {
      const {
        latitude,
        longitude,
        accuracy,
      } = position.coords;

      userLocation = {
        lat: latitude,
        lon: longitude,
        accuracy: Number.isFinite(accuracy)
          ? accuracy
          : null,
      };

      setStatus(
        `${latitude.toFixed(4)}, ${longitude.toFixed(4)}`
      );

      if (!map || !window.L) {
        return;
      }

      if (!userMarker) {
        userMarker =
          L.circleMarker(
            [latitude, longitude],
            {
              radius: 7,
              className:
                "jarvis-user-marker",
              weight: 2,
              fillOpacity: 0.9,
            }
          ).addTo(map);

        userMarker.bindTooltip(
          "YOU",
          {
            permanent: true,
            direction: "top",
            offset: [0, -8],
            className:
              "jarvis-user-label",
          }
        );
      } else {
        userMarker.setLatLng([
          latitude,
          longitude,
        ]);
      }

      if (accuracyCircle) {
        accuracyCircle.setLatLng([
          latitude,
          longitude,
        ]);

        accuracyCircle.setRadius(
          accuracy || 20
        );
      } else {
        accuracyCircle =
          L.circle(
            [latitude, longitude],
            {
              radius: accuracy || 20,
              className:
                "jarvis-accuracy",
            }
          ).addTo(map);
      }

      /*
       * Only center on the user when there are no search results.
       *
       * This prevents the location watcher from stealing the map
       * away from a selected cafe/restaurant/etc.
       */
      if (
        !expanded &&
        markers.size === 0
      ) {
        map.setView(
          [latitude, longitude],
          PREVIEW_ZOOM
        );
      }
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

    navigator.geolocation.watchPosition(
      success,
      () => {},
      {
        enableHighAccuracy: true,
        timeout: 15000,
        maximumAge: 10000,
      }
    );
  }

  function initMap() {
    if (initialized) {
      return;
    }

    if (!window.L) {
      console.error(
        "[Jarvis Map] Leaflet is not loaded."
      );

      setStatus("MAP LIBRARY OFFLINE");
      return;
    }

    ensureUI();

    const mapContainer =
      document.getElementById(
        "jarvisMapCanvas"
      );

    if (!mapContainer) {
      console.error(
        "[Jarvis Map] Map container not found."
      );

      return;
    }

    /*
     * If another implementation somehow left a canvas
     * with this ID behind, replace it.
     */
    if (
      mapContainer.tagName === "CANVAS"
    ) {
      const replacement =
        document.createElement("div");

      replacement.id =
        "jarvisMapCanvas";

      replacement.className =
        "jarvis-map-canvas";

      mapContainer.replaceWith(
        replacement
      );
    }

    const container =
      document.getElementById(
        "jarvisMapCanvas"
      );

    initialized = true;

    map = L.map(container, {
      zoomControl: true,
      worldCopyJump: true,
      minZoom: 2,
    }).setView(
      DEFAULT_CENTER,
      DEFAULT_ZOOM
    );

    L.tileLayer(
      "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
      {
        maxZoom: 19,
        attribution:
          "&copy; OpenStreetMap contributors",
      }
    ).addTo(map);

    markerLayer =
      L.layerGroup().addTo(map);

    /*
     * Click anywhere on the base map (not on a marker -- marker clicks
     * already call event.originalEvent.stopPropagation(), which stops
     * this Leaflet map-level click from also firing for the same
     * physical click) to reverse-geocode that point and show what's
     * there, the way Google Maps' "what's here" works.
     */
    map.on(
      "click",
      (event) => {
        reverseGeocodeClick(
          event.latlng.lat,
          event.latlng.lng
        );
      }
    );

    locateUser();

    setStatus("MAP ONLINE");
  }

  function popupHtml(marker) {
    const distance =
      formatDistance(
        marker.distance_km
      );

    return `
      <div class="jarvis-map-popup">
        <strong>
          ${escapeHtml(
            marker.name ||
            "Unknown place"
          )}
        </strong>

        ${
          distance
            ? `<br>${escapeHtml(
                distance
              )} away`
            : ""
        }

        ${
          marker.address
            ? `<br>${escapeHtml(
                marker.address
              )}`
            : ""
        }

        ${
          marker.opening_hours
            ? `<br>Hours: ${escapeHtml(
                marker.opening_hours
              )}`
            : ""
        }

        ${
          marker.cuisine
            ? `<br>Cuisine: ${escapeHtml(
                marker.cuisine
              )}`
            : ""
        }
      </div>
    `;
  }

  function closeDetails() {
    const details =
      document.getElementById(
        "jarvisMapDetails"
      );

    if (!details) {
      return;
    }

    details.hidden = true;
    details.innerHTML = "";
  }

  function showDetails(marker) {
    const details =
      document.getElementById(
        "jarvisMapDetails"
      );

    if (!details) {
      return;
    }

    const name =
      marker.name ||
      "Unknown place";

    const distance =
      formatDistance(
        marker.distance_km
      );

    const website =
      normalizeUrl(
        marker.website
      );

    const phone =
      String(
        marker.phone || ""
      ).trim();

    const address =
      String(
        marker.address || ""
      ).trim();

    const hours =
      String(
        marker.opening_hours || ""
      ).trim();

    const cuisine =
      String(
        marker.cuisine || ""
      ).trim();

    const type =
      String(
        marker.type ||
        marker.category ||
        ""
      ).trim();

    const lat =
      Number(marker.lat);

    const lon =
      Number(marker.lon);

    const hasCoordinates =
      Number.isFinite(lat) &&
      Number.isFinite(lon);

    const osmUrl =
      hasCoordinates
        ? `https://www.openstreetmap.org/?mlat=${encodeURIComponent(
            lat
          )}&mlon=${encodeURIComponent(
            lon
          )}#map=19/${encodeURIComponent(
            lat
          )}/${encodeURIComponent(
            lon
          )}`
        : "";

    details.innerHTML = `
      <div class="jarvis-map-details-header">

        <div>
          <div class="jarvis-map-details-kicker">
            LOCATION
          </div>

          <div class="jarvis-map-details-title">
            ${escapeHtml(name)}
          </div>
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
            ? `
              <div class="jarvis-map-detail-row">
                <span>TYPE</span>
                <strong>
                  ${escapeHtml(type)}
                </strong>
              </div>
            `
            : ""
        }

        ${
          distance
            ? `
              <div class="jarvis-map-detail-row">
                <span>DISTANCE</span>
                <strong>
                  ${escapeHtml(distance)}
                </strong>
              </div>
            `
            : ""
        }

        ${
          address
            ? `
              <div class="jarvis-map-detail-row stacked">
                <span>ADDRESS</span>
                <strong>
                  ${escapeHtml(address)}
                </strong>
              </div>
            `
            : ""
        }

        ${
          hours
            ? `
              <div class="jarvis-map-detail-row stacked">
                <span>HOURS</span>
                <strong>
                  ${escapeHtml(hours)}
                </strong>
              </div>
            `
            : ""
        }

        ${
          cuisine
            ? `
              <div class="jarvis-map-detail-row stacked">
                <span>CUISINE</span>
                <strong>
                  ${escapeHtml(cuisine)}
                </strong>
              </div>
            `
            : ""
        }

        ${
          phone
            ? `
              <div class="jarvis-map-detail-row stacked">
                <span>PHONE</span>
                <strong>
                  ${escapeHtml(phone)}
                </strong>
              </div>
            `
            : ""
        }

        ${
          hasCoordinates
            ? `
              <div class="jarvis-map-detail-row">
                <span>COORDINATES</span>
                <strong>
                  ${lat.toFixed(6)},
                  ${lon.toFixed(6)}
                </strong>
              </div>
            `
            : ""
        }

        <div class="jarvis-map-detail-actions">

          ${
            website
              ? `
                <a
                  class="jarvis-map-detail-action"
                  href="${escapeHtml(
                    website
                  )}"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  WEBSITE
                </a>
              `
              : ""
          }

          ${
            osmUrl
              ? `
                <a
                  class="jarvis-map-detail-action"
                  href="${escapeHtml(
                    osmUrl
                  )}"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  OPENSTREETMAP
                </a>
              `
              : ""
          }

        </div>

      </div>
    `;

    details.hidden = false;

    document
      .getElementById(
        "jarvisMapDetailsClose"
      )
      ?.addEventListener(
        "click",
        (event) => {
          event.stopPropagation();
          closeDetails();
        }
      );
  }

  function focusMarker(marker) {
    initMap();

    if (!map || !marker) {
      return;
    }

    const lat =
      Number(marker.lat);

    const lon =
      Number(marker.lon);

    if (
      !Number.isFinite(lat) ||
      !Number.isFinite(lon)
    ) {
      console.warn(
        "[Jarvis Map] Invalid marker coordinates:",
        marker
      );

      return;
    }

    /*
     * Critical:
     *
     * preserveView prevents setExpanded() from centering
     * on the user's location.
     */
    setExpanded(
      true,
      {
        preserveView: true,
      }
    );

    requestAnimationFrame(() => {
      if (!map) {
        return;
      }

      map.invalidateSize();

      /*
       * Center on the ACTUAL marker coordinates.
       */
      map.setView(
        [lat, lon],
        MARKER_ZOOM,
        {
          animate: true,
        }
      );

      if (marker.layer) {
        marker.layer.openPopup();
      }

      showDetails(marker);
    });
  }

  function renderResults() {
    const results =
      document.getElementById(
        "jarvisMapResults"
      );

    if (!results) {
      return;
    }

    results.innerHTML = "";

    results.classList.toggle(
      "has-results",
      markers.size > 0
    );

    markers.forEach((marker) => {
      const item =
        createElement(
          "button",
          {
            class:
              "jarvis-map-result",
            type: "button",
          }
        );

      const distance =
        formatDistance(
          marker.distance_km
        );

      item.innerHTML = `
        <span class="jarvis-map-result-name">
          ${escapeHtml(
            marker.name ||
            "Unknown place"
          )}
        </span>

        <span class="jarvis-map-result-distance">
          ${escapeHtml(distance)}
        </span>
      `;

      item.addEventListener(
        "click",
        (event) => {
          event.stopPropagation();
          focusMarker(marker);
        }
      );

      results.appendChild(item);
    });
  }

  function setMarkers(payload) {
    initMap();

    if (
      !map ||
      !markerLayer
    ) {
      console.warn(
        "[Jarvis Map] set_markers received before map initialization",
        payload
      );

      return;
    }

    /*
     * Support both:
     *
     * {
     *   action: "set_markers",
     *   markers: [...]
     * }
     *
     * and:
     *
     * {
     *   action: "set_markers",
     *   payload: {
     *     markers: [...]
     *   }
     * }
     */
    let data = payload || {};

    if (
      payload?.payload &&
      typeof payload.payload ===
        "object"
    ) {
      data = {
        ...payload,
        ...payload.payload,
      };
    }

    const incomingMarkers =
      Array.isArray(data.markers)
        ? data.markers
        : Array.isArray(data.places)
          ? data.places
          : [];

    console.log(
      "[Jarvis Map] Received markers:",
      incomingMarkers
    );

    if (
      data.replace !== false
    ) {
      markerLayer.clearLayers();
      markers.clear();
      closeDetails();
    }

    incomingMarkers.forEach(
      (marker) => {
        const lat =
          Number(marker.lat);

        const lon =
          Number(marker.lon);

        /*
         * Never render a marker without valid coordinates.
         */
        if (
          !Number.isFinite(lat) ||
          !Number.isFinite(lon)
        ) {
          console.warn(
            "[Jarvis Map] Skipping marker with invalid coordinates:",
            marker
          );

          return;
        }

        const id =
          marker.id ||
          `${lat}:${lon}:${
            marker.name ||
            "place"
          }`;

        const normalized = {
          ...marker,
          lat,
          lon,
          id,
        };

        /*
         * Use a CSS/HTML marker.
         *
         * This avoids Leaflet's default marker-image dependency.
         */
        const pinIcon =
          L.divIcon({
            className:
              "jarvis-place-marker-wrapper",

            html: `
              <div
                class="jarvis-place-marker"
                title="${escapeHtml(
                  marker.name ||
                  "Place"
                )}"
              >
                <span></span>
              </div>
            `,

            iconSize: [
              24,
              32,
            ],

            iconAnchor: [
              12,
              30,
            ],

            popupAnchor: [
              0,
              -30,
            ],
          });

        const pin =
          L.marker(
            [lat, lon],
            {
              title:
                marker.name ||
                "Place",

              icon:
                pinIcon,

              keyboard:
                true,

              zIndexOffset:
                1000,
            }
          )
            .bindPopup(
              popupHtml(
                normalized
              )
            )
            .addTo(
              markerLayer
            );

        /*
         * Marker click.
         *
         * Do NOT use the user's location here.
         */
        pin.on(
          "click",
          (event) => {
            event
              ?.originalEvent
              ?.stopPropagation?.();

            focusMarker({
              ...normalized,
              layer: pin,
            });
          }
        );

        markers.set(
          id,
          {
            ...normalized,
            layer: pin,
          }
        );
      }
    );

    renderResults();

    /*
     * Expand without recentering on the user.
     */
    setExpanded(
      true,
      {
        preserveView: true,
      }
    );

    requestAnimationFrame(() => {
      if (!map || !markers.size) {
        return;
      }

      map.invalidateSize();

      /*
       * Fit the returned search results.
       *
       * User location is included only to provide context;
       * it does not overwrite the marker positions.
       */
      const bounds =
        L.latLngBounds(
          Array.from(
            markers.values()
          ).map(
            (marker) => [
              marker.lat,
              marker.lon,
            ]
          )
        );

      if (userLocation) {
        bounds.extend([
          userLocation.lat,
          userLocation.lon,
        ]);
      }

      map.fitBounds(
        bounds.pad(0.15),
        {
          maxZoom: 15,
          animate: true,
        }
      );
    });
  }

  function clearMarkers(category = "") {
    if (!markerLayer) {
      return;
    }

    const wanted =
      String(category)
        .trim()
        .toLowerCase();

    if (!wanted) {
      markerLayer.clearLayers();
      markers.clear();
      closeDetails();
      renderResults();

      return;
    }

    markers.forEach(
      (marker) => {
        if (
          String(
            marker.category ||
            ""
          ).toLowerCase() ===
          wanted
        ) {
          markerLayer.removeLayer(
            marker.layer
          );

          markers.delete(
            marker.id
          );
        }
      }
    );

    closeDetails();
    renderResults();
  }

  function submitSearch(query) {
    const trimmed = String(query || "").trim();

    if (!trimmed) {
      return;
    }

    ensureUI();
    revealMapWidget();
    setExpanded(true);
    setStatus(`Searching "${trimmed}"...`);

    if (!sendToBackend({ type: "map_search", query: trimmed })) {
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
    setStatus(text || (data?.error ? "Search failed." : "MAP ONLINE"));
  }

  function handleReverseGeocodeResult(data) {
    const marker = data?.marker;

    if (!marker || marker.error) {
      setStatus(marker?.error || "Could not identify this location.");
      return;
    }

    ensureUI();
    revealMapWidget();

    /*
     * Add without clearing existing pins (replace: false) -- a "what's
     * here" click augments the current results rather than replacing
     * a prior search. Reuses setMarkers' existing rendering pipeline
     * (popup, click handling, results-list entry) rather than
     * duplicating marker-creation logic here.
     */
    setMarkers({
      markers: [marker],
      replace: false,
    });

    /*
     * setMarkers doesn't return the marker it just created, so look it
     * back up by the same id formula it uses internally, to get the
     * .layer reference focusMarker() needs to open the popup.
     */
    const id =
      marker.id ||
      `${Number(marker.lat)}:${Number(marker.lon)}:${marker.name || "place"}`;

    const stored = markers.get(id);

    if (stored) {
      focusMarker(stored);
    }

    setStatus("MAP ONLINE");
  }

  function handleAction(payload) {
    if (!payload?.action) {
      return;
    }

    if (
      payload.action ===
      "set_markers"
    ) {
      // A set_markers action arriving from the backend (e.g. the user
      // asked Jarvis to find nearby places via voice/chat) means there
      // are results to show, whether or not the panel was ever manually
      // opened. Reveal it now so markers aren't applied to a hidden,
      // zero-size map the user never sees.
      revealMapWidget();
      setMarkers(payload);
    }

    else if (
      payload.action ===
      "clear_markers"
    ) {
      clearMarkers(
        payload.category
      );
    }

    else if (
      payload.action ===
      "focus_marker"
    ) {
      revealMapWidget();
      focusMarker({
        lat:
          payload.latitude,
        lon:
          payload.longitude,
        name:
          payload.name || "",
      });
    }
  }

  function getContext() {
    const widget =
      document.getElementById(
        "jarvisMapWidget"
      );

    const context = {
      open: expanded,

      visible:
        !!widget?.classList.contains(
          "map-visible"
        ),

      latitude:
        userLocation?.lat ??
        null,

      longitude:
        userLocation?.lon ??
        null,

      accuracy_m:
        userLocation?.accuracy ??
        null,

      zoom:
        map?.getZoom?.() ??
        null,

      marker_count:
        markers.size,

      markers:
        Array.from(
          markers.values()
        )
          .slice(0, 20)
          .map(
            (marker) => ({
              id:
                marker.id,

              name:
                marker.name,

              latitude:
                marker.lat,

              longitude:
                marker.lon,

              category:
                marker.category,

              distance_km:
                marker.distance_km,

              address:
                marker.address,

              opening_hours:
                marker.opening_hours,

              phone:
                marker.phone,

              website:
                marker.website,

              cuisine:
                marker.cuisine,

              type:
                marker.type,
            })
          ),
    };

    if (map) {
      const bounds =
        map.getBounds();

      context.bounds = {
        north:
          bounds.getNorth(),

        south:
          bounds.getSouth(),

        east:
          bounds.getEast(),

        west:
          bounds.getWest(),
      };
    }

    return context;
  }

  function centerOnUser() {
    if (!map || !userLocation) {
      return;
    }

    map.setView(
      [
        userLocation.lat,
        userLocation.lon,
      ],
      Math.max(
        map.getZoom(),
        PREVIEW_ZOOM
      ),
      {
        animate: true,
      }
    );
  }

  function showWorld() {
    if (!map) {
      initMap();
    }

    if (!map) {
      return;
    }

    map.setView(
      DEFAULT_CENTER,
      DEFAULT_ZOOM,
      {
        animate: true,
      }
    );
  }

  function zoomMap(direction) {
    if (!map) {
      initMap();
    }

    if (!map) {
      return;
    }

    const current =
      map.getZoom();

    const next =
      Math.max(
        2,
        Math.min(
          19,
          current +
            Number(direction || 0)
        )
      );

    map.setZoom(
      next,
      {
        animate: true,
      }
    );
  }

  window.JarvisMap = {
    toggle:
      toggleVisibility,

    open() {
      revealMapWidget();
    },

    close() {
      const widget =
        document.getElementById(
          "jarvisMapWidget"
        );

      widget?.classList.remove(
        "map-visible"
      );

      localStorage.setItem(
        STORAGE_KEY,
        "0"
      );
    },

    expand() {
      setExpanded(true);
    },

    collapse() {
      setExpanded(false);
    },

    centerOnUser,

    showWorld,

    zoom:
      zoomMap,

    getContext,

    handleAction,

    handleSearchResult,

    handleReverseGeocodeResult,

    clear:
      clearMarkers,

    focus:
      focusMarker,
  };

  document.addEventListener(
    "DOMContentLoaded",
    () => {
      ensureUI();

      if (
        localStorage.getItem(
          STORAGE_KEY
        ) === "1"
      ) {
        document
          .getElementById(
            "jarvisMapWidget"
          )
          ?.classList.add(
            "map-visible"
          );

        initMap();
      }
    }
  );
})();
