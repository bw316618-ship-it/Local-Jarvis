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

    const canvas = createElement("div", {
      id: "jarvisMapCanvas",
      class: "jarvis-map-canvas",
    });

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
      canvas,
      results,
      details
    );

    document.body.append(
      toggle,
      widget
    );

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

    widget.addEventListener("click", (event) => {
      if (
        !expanded &&
        !event.target.closest("button")
      ) {
        setExpanded(true);
      }
    });
  }

  function toggleVisibility() {
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

  /*
   * Expanding the map normally centers on the user.
   *
   * Marker selection/search results pass preserveView:true,
   * which prevents the expansion process from overwriting the
   * marker's coordinates with the user's coordinates.
   */
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
        expanded
          ? "PREVIEW"
          : "EXPAND";
    }

    initMap();

    requestAnimationFrame(() => {
      map?.invalidateSize();

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
        userMarker = L.circleMarker(
          [
            latitude,
            longitude,
          ],
          {
            radius: 7,
            className: "jarvis-user-marker",
            weight: 2,
            fillOpacity: 0.9,
          }
        ).addTo(map);

        userMarker.bindTooltip("YOU", {
          permanent: true,
          direction: "top",
          offset: [0, -8],
          className: "jarvis-user-label",
        });
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
        accuracyCircle = L.circle(
          [
            latitude,
            longitude,
          ],
          {
            radius: accuracy || 20,
            className: "jarvis-accuracy",
          }
        ).addTo(map);
      }

      /*
       * Only automatically center on the user when the map has
       * no search results.
       *
       * Once places exist, location updates must NEVER move
       * the map away from the places the user is inspecting.
       */
      if (
        !expanded &&
        markers.size === 0
      ) {
        map.setView(
          [
            latitude,
            longitude,
          ],
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
    if (
      initialized ||
      !window.L
    ) {
      return;
    }

    const canvas =
      document.getElementById(
        "jarvisMapCanvas"
      );

    if (!canvas) {
      return;
    }

    initialized = true;

    map = L.map(canvas, {
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

    const osmUrl =
      Number.isFinite(
        Number(marker.lat)
      ) &&
      Number.isFinite(
        Number(marker.lon)
      )
        ? `https://www.openstreetmap.org/?mlat=${encodeURIComponent(
            marker.lat
          )}&mlon=${encodeURIComponent(
            marker.lon
          )}#map=19/${encodeURIComponent(
            marker.lat
          )}/${encodeURIComponent(
            marker.lon
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

        <div class="jarvis-map-detail-row">
          <span>COORDINATES</span>

          <strong>
            ${Number(marker.lat).toFixed(6)},
            ${Number(marker.lon).toFixed(6)}
          </strong>
        </div>

        <div class="jarvis-map-detail-actions">

          ${
            website
              ? `
                <a
                  class="jarvis-map-detail-action"
                  href="${escapeHtml(website)}"
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
                  href="${escapeHtml(osmUrl)}"
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

  /*
   * Central place-selection function.
   *
   * Every marker click and every result-list click goes through here.
   * This prevents the user-location recentering bug.
   */
  function focusMarker(marker) {
    initMap();

    if (!map || !marker) {
      return;
    }

    const lat = Number(marker.lat);
    const lon = Number(marker.lon);

    if (
      !Number.isFinite(lat) ||
      !Number.isFinite(lon)
    ) {
      return;
    }

    /*
     * Expand without changing the current map view.
     */
    setExpanded(
      true,
      {
        preserveView: true,
      }
    );

    requestAnimationFrame(() => {
      map.invalidateSize();

      /*
       * This is the important part:
       *
       * ALWAYS use the selected marker's coordinates.
       * Never use userLocation here.
       */
      map.setView(
        [lat, lon],
        Math.max(
          map.getZoom(),
          MARKER_ZOOM
        ),
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
      const item = createElement(
        "button",
        {
          class: "jarvis-map-result",
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
            marker.name
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
      return;
    }

    if (
      payload.replace !== false
    ) {
      markerLayer.clearLayers();
      markers.clear();
      closeDetails();
    }

    (payload.markers || []).forEach(
      (marker) => {
        const lat = Number(
          marker.lat
        );

        const lon = Number(
          marker.lon
        );

        if (
          !Number.isFinite(lat) ||
          !Number.isFinite(lon)
        ) {
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

        const pin =
          L.marker(
            [lat, lon],
            {
              title:
                marker.name ||
                "Place",
            }
          )
            .bindPopup(
              popupHtml(normalized)
            )
            .addTo(markerLayer);

        pin.on(
          "click",
          (event) => {
            /*
             * Marker clicks use the exact same
             * selection path as search results.
             */
            L.DomEvent.stopPropagation(
              event
            );

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
     * Expand while preserving the current map.
     */
    setExpanded(
      true,
      {
        preserveView: true,
      }
    );

    requestAnimationFrame(() => {
      map.invalidateSize();

      if (!markers.size) {
        return;
      }

      const bounds =
        L.latLngBounds(
          Array.from(
            markers.values()
          ).map((marker) => [
            marker.lat,
            marker.lon,
          ])
        );

      /*
       * Include the user only when fitting the overall
       * search results. This does NOT affect marker selection.
       */
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

  function clearMarkers(
    category = ""
  ) {
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
            marker.category || ""
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

  function handleAction(payload) {
    if (!payload?.action) {
      return;
    }

    if (
      payload.action ===
      "set_markers"
    ) {
      setMarkers(payload);

    } else if (
      payload.action ===
      "clear_markers"
    ) {
      clearMarkers(
        payload.category
      );

    } else if (
      payload.action ===
      "focus_marker"
    ) {
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

  window.JarvisMap = {
    toggle:
      toggleVisibility,

    open() {
      ensureUI();

      document
        .getElementById(
          "jarvisMapWidget"
        )
        ?.classList.add(
          "map-visible"
        );

      localStorage.setItem(
        STORAGE_KEY,
        "1"
      );

      initMap();
    },

    close() {
      document
        .getElementById(
          "jarvisMapWidget"
        )
        ?.classList.remove(
          "map-visible"
        );

      localStorage.setItem(
        STORAGE_KEY,
        "0"
      );
    },

    expand: () =>
      setExpanded(true),

    collapse: () =>
      setExpanded(false),

    getContext,

    handleAction,

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