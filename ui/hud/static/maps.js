/* ============================================================
   JARVIS HUD MAP EXTENSION
   ------------------------------------------------------------
   Local geolocation + OpenStreetMap rendering.

   Map mode:
     - Keeps the global Jarvis chat bar visible.
     - Intercepts chat while the map is open.
     - Handles map commands locally.
     - Sends natural-language map questions to Jarvis
       with current map/location context.
   ============================================================ */

(() => {
  "use strict";

  const TILE_URL =
    "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

  const TILE_SIZE = 256;

  const MIN_ZOOM = 1;
  const MAX_ZOOM = 19;

  const WORLD_ZOOM = 2;
  const LOCAL_ZOOM = 14;

  const MAP_STORAGE_KEY =
    "jarvis-map-last-state";

  let latitude = null;
  let longitude = null;
  let accuracy = null;

  let smallCanvas = null;
  let expandedCanvas = null;

  let smallCtx = null;
  let expandedCtx = null;

  let expanded = false;

  let dragging = false;
  let dragStart = null;

  let map = {
    x: 0,
    y: 0,
    zoom: WORLD_ZOOM,
  };

  let smallMap = {
    x: 0,
    y: 0,
    zoom: LOCAL_ZOOM,
  };

  const tileCache = new Map();


  /* ============================================================
     DOM
     ============================================================ */

  function createDOM() {
    if (
      document.getElementById(
        "jarvisMapWidget"
      )
    ) {
      return;
    }

    /*
     * ----------------------------------------------------------
     * MINI MAP
     * ----------------------------------------------------------
     */

    const widget =
      document.createElement("div");

    widget.id =
      "jarvisMapWidget";

    widget.title =
      "Open Jarvis Maps";

    widget.innerHTML = `
      <canvas
        id="jarvisMapCanvas"
      ></canvas>

      <div class="jarvis-map-header">
        <span class="jarvis-map-title">
          LOCATION
        </span>

        <span
          id="jarvisMapStatus"
          class="jarvis-map-status"
        >
          LOCATING
        </span>
      </div>

      <div
        id="jarvisMapLocation"
        class="jarvis-map-location"
      >
        ACQUIRING POSITION
      </div>
    `;

    document.body.appendChild(
      widget
    );


    /*
     * ----------------------------------------------------------
     * EXPANDED MAP
     * ----------------------------------------------------------
     */

    const overlay =
      document.createElement("div");

    overlay.id =
      "jarvisMapOverlay";

    overlay.innerHTML = `
      <div class="jarvis-map-window">

        <div class="jarvis-map-window-header">

          <div class="jarvis-map-window-title">
            JARVIS / MAP
          </div>

          <button
            id="jarvisMapClose"
            class="jarvis-map-close"
            type="button"
            title="Close map"
          >
            ×
          </button>

        </div>

        <canvas
          id="jarvisMapExpandedCanvas"
        ></canvas>

        <div
          id="jarvisMapMessage"
          class="jarvis-map-message"
          hidden
        ></div>

        <div class="jarvis-map-info">

          <div>
            LAT
            <span id="jarvisMapLat">
              --
            </span>
          </div>

          <div>
            LON
            <span id="jarvisMapLon">
              --
            </span>
          </div>

          <div>
            ACC
            <span id="jarvisMapAccuracy">
              --
            </span>
          </div>

          <div>
            ZOOM
            <span id="jarvisMapZoom">
              --
            </span>
          </div>

        </div>

        <div class="jarvis-map-controls">

          <button
            id="jarvisMapZoomIn"
            class="jarvis-map-control"
            type="button"
            title="Zoom in"
          >
            +
          </button>

          <button
            id="jarvisMapZoomOut"
            class="jarvis-map-control"
            type="button"
            title="Zoom out"
          >
            −
          </button>

          <button
            id="jarvisMapLocate"
            class="jarvis-map-control"
            type="button"
            title="Center on me"
          >
            ◎
          </button>

        </div>

      </div>
    `;

    document.body.appendChild(
      overlay
    );


    smallCanvas =
      document.getElementById(
        "jarvisMapCanvas"
      );

    expandedCanvas =
      document.getElementById(
        "jarvisMapExpandedCanvas"
      );

    smallCtx =
      smallCanvas.getContext(
        "2d"
      );

    expandedCtx =
      expandedCanvas.getContext(
        "2d"
      );


    /*
     * ----------------------------------------------------------
     * EVENTS
     * ----------------------------------------------------------
     */

    widget.addEventListener(
      "click",
      openMap
    );

    document
      .getElementById(
        "jarvisMapClose"
      )
      .addEventListener(
        "click",
        closeMap
      );

    document
      .getElementById(
        "jarvisMapZoomIn"
      )
      .addEventListener(
        "click",
        () => {
          zoomMap(1);
        }
      );

    document
      .getElementById(
        "jarvisMapZoomOut"
      )
      .addEventListener(
        "click",
        () => {
          zoomMap(-1);
        }
      );

    document
      .getElementById(
        "jarvisMapLocate"
      )
      .addEventListener(
        "click",
        centerOnUser
      );


    /*
     * ----------------------------------------------------------
     * DRAGGING
     * ----------------------------------------------------------
     */

    expandedCanvas.addEventListener(
      "mousedown",
      startDrag
    );

    window.addEventListener(
      "mousemove",
      dragMap
    );

    window.addEventListener(
      "mouseup",
      stopDrag
    );


    expandedCanvas.addEventListener(
      "wheel",
      event => {
        event.preventDefault();

        zoomMap(
          event.deltaY < 0
            ? 1
            : -1
        );
      },
      {
        passive: false,
      }
    );


    /*
     * ----------------------------------------------------------
     * RESIZE
     * ----------------------------------------------------------
     */

    window.addEventListener(
      "resize",
      () => {
        resizeCanvas(
          smallCanvas,
          smallCtx
        );

        resizeCanvas(
          expandedCanvas,
          expandedCtx
        );

        drawSmallMap();

        if (expanded) {
          drawExpandedMap();
        }
      }
    );


    /*
     * ----------------------------------------------------------
     * KEYBOARD
     * ----------------------------------------------------------
     */

    window.addEventListener(
      "keydown",
      event => {
        if (
          event.key ===
          "Escape"
        ) {
          if (expanded) {
            closeMap();
          }
        }
      }
    );


    /*
     * ----------------------------------------------------------
     * MAP CHAT INTERCEPTION
     *
     * Capture phase is intentional.
     *
     * hud.js already owns chatForm. This listener runs before
     * hud.js's normal submit handler when map mode is active.
     * ----------------------------------------------------------
     */

    const chatForm =
      document.getElementById(
        "chatForm"
      );

    if (chatForm) {
      chatForm.addEventListener(
        "submit",
        handleMapChatSubmit,
        true
      );
    }
  }


  /* ============================================================
     GEOLOCATION
     ============================================================ */

  function startLocationTracking() {
    const status =
      document.getElementById(
        "jarvisMapStatus"
      );

    if (
      !navigator.geolocation
    ) {
      status.textContent =
        "UNAVAILABLE";

      setMapMessage(
        "GEOLOCATION UNAVAILABLE"
      );

      return;
    }

    status.textContent =
      "LOCATING";

    navigator.geolocation.watchPosition(
      position => {

        latitude =
          position.coords.latitude;

        longitude =
          position.coords.longitude;

        accuracy =
          position.coords.accuracy;

        status.textContent =
          "LOCKED";

        updateLocationUI();

        /*
         * First valid location establishes
         * the small map around the user.
         */

        if (
          !smallMap._positioned
        ) {
          centerSmallMap();

          smallMap._positioned =
            true;
        }

        drawSmallMap();

        if (expanded) {
          drawExpandedMap();
        }
      },

      error => {

        console.warn(
          "[Jarvis Maps] Geolocation:",
          error.message
        );

        status.textContent =
          "NO SIGNAL";

        setMapMessage(
          "LOCATION PERMISSION UNAVAILABLE"
        );
      },

      {
        enableHighAccuracy: true,
        maximumAge: 10000,
        timeout: 15000,
      }
    );
  }


  /* ============================================================
     LOCATION UI
     ============================================================ */

  function updateLocationUI() {
    const location =
      document.getElementById(
        "jarvisMapLocation"
      );

    const lat =
      document.getElementById(
        "jarvisMapLat"
      );

    const lon =
      document.getElementById(
        "jarvisMapLon"
      );

    const acc =
      document.getElementById(
        "jarvisMapAccuracy"
      );

    if (
      latitude === null ||
      longitude === null
    ) {
      return;
    }

    location.textContent =
      `${latitude.toFixed(4)}, ${longitude.toFixed(4)}`;

    lat.textContent =
      latitude.toFixed(6);

    lon.textContent =
      longitude.toFixed(6);

    acc.textContent =
      accuracy !== null
        ? `${Math.round(accuracy)}m`
        : "--";
  }


  function updateZoomUI() {
    const zoom =
      document.getElementById(
        "jarvisMapZoom"
      );

    if (zoom) {
      zoom.textContent =
        String(map.zoom);
    }
  }


  function setMapMessage(
    text
  ) {
    const element =
      document.getElementById(
        "jarvisMapMessage"
      );

    if (!element) {
      return;
    }

    element.textContent =
      text;

    element.hidden =
      !text;
  }


  /* ============================================================
     PROJECTION
     ============================================================ */

  function longitudeToWorldX(
    lon,
    zoom
  ) {
    const scale =
      TILE_SIZE *
      Math.pow(
        2,
        zoom
      );

    return (
      (lon + 180) /
      360 *
      scale
    );
  }


  function latitudeToWorldY(
    lat,
    zoom
  ) {
    const scale =
      TILE_SIZE *
      Math.pow(
        2,
        zoom
      );

    const sinLat =
      Math.sin(
        lat *
        Math.PI /
        180
      );

    const y =
      0.5 -
      Math.log(
        (1 + sinLat) /
        (1 - sinLat)
      ) /
      (4 * Math.PI);

    return y * scale;
  }


  function worldXToLongitude(
    x,
    zoom
  ) {
    const scale =
      TILE_SIZE *
      Math.pow(
        2,
        zoom
      );

    return (
      x / scale *
      360 -
      180
    );
  }


  function worldYToLatitude(
    y,
    zoom
  ) {
    const scale =
      TILE_SIZE *
      Math.pow(
        2,
        zoom
      );

    const n =
      Math.PI -
      2 *
      Math.PI *
      y /
      scale;

    return (
      180 /
      Math.PI *
      Math.atan(
        0.5 *
        (
          Math.exp(n) -
          Math.exp(-n)
        )
      )
    );
  }


  /* ============================================================
     CANVAS
     ============================================================ */

  function resizeCanvas(
    canvas,
    ctx
  ) {
    if (
      !canvas ||
      !ctx
    ) {
      return;
    }

    const rect =
      canvas.getBoundingClientRect();

    const dpr =
      window.devicePixelRatio ||
      1;

    canvas.width =
      Math.max(
        1,
        Math.round(
          rect.width *
          dpr
        )
      );

    canvas.height =
      Math.max(
        1,
        Math.round(
          rect.height *
          dpr
        )
      );

    ctx.setTransform(
      dpr,
      0,
      0,
      dpr,
      0,
      0
    );
  }


  /* ============================================================
     TILE CACHE
     ============================================================ */

  function getTile(
    x,
    y,
    z
  ) {
    const count =
      Math.pow(
        2,
        z
      );

    x =
      ((x % count) +
        count) %
      count;

    if (
      y < 0 ||
      y >= count
    ) {
      return null;
    }

    const key =
      `${z}/${x}/${y}`;

    if (
      tileCache.has(key)
    ) {
      return tileCache.get(
        key
      );
    }

    const image =
      new Image();

    image.crossOrigin =
      "anonymous";

    image.src =
      TILE_URL
        .replace(
          "{z}",
          z
        )
        .replace(
          "{x}",
          x
        )
        .replace(
          "{y}",
          y
        );

    tileCache.set(
      key,
      image
    );

    image.onload = () => {
      drawSmallMap();

      if (expanded) {
        drawExpandedMap();
      }
    };

    return image;
  }


  /* ============================================================
     RENDERER
     ============================================================ */

  function drawMap(
    canvas,
    ctx,
    state
  ) {
    if (
      !canvas ||
      !ctx
    ) {
      return;
    }

    const width =
      canvas.clientWidth;

    const height =
      canvas.clientHeight;

    ctx.clearRect(
      0,
      0,
      width,
      height
    );

    ctx.fillStyle =
      "#071017";

    ctx.fillRect(
      0,
      0,
      width,
      height
    );


    const firstTileX =
      Math.floor(
        (
          state.x -
          width / 2
        ) /
        TILE_SIZE
      );

    const lastTileX =
      Math.floor(
        (
          state.x +
          width / 2
        ) /
        TILE_SIZE
      );

    const firstTileY =
      Math.floor(
        (
          state.y -
          height / 2
        ) /
        TILE_SIZE
      );

    const lastTileY =
      Math.floor(
        (
          state.y +
          height / 2
        ) /
        TILE_SIZE
      );


    for (
      let tileX =
        firstTileX;
      tileX <= lastTileX;
      tileX++
    ) {

      for (
        let tileY =
          firstTileY;
        tileY <= lastTileY;
        tileY++
      ) {

        const image =
          getTile(
            tileX,
            tileY,
            state.zoom
          );

        if (!image) {
          continue;
        }

        const drawX =
          tileX *
            TILE_SIZE -
          state.x +
          width / 2;

        const drawY =
          tileY *
            TILE_SIZE -
          state.y +
          height / 2;

        if (
          image.complete &&
          image.naturalWidth
        ) {

          ctx.drawImage(
            image,
            drawX,
            drawY,
            TILE_SIZE,
            TILE_SIZE
          );

        } else {

          ctx.fillStyle =
            "rgba(15, 35, 46, 0.8)";

          ctx.fillRect(
            drawX,
            drawY,
            TILE_SIZE,
            TILE_SIZE
          );
        }
      }
    }


    drawGrid(
      ctx,
      width,
      height
    );


    if (
      latitude !== null &&
      longitude !== null
    ) {
      drawLocationMarker(
        ctx,
        state,
        width,
        height
      );
    }
  }


  function drawGrid(
    ctx,
    width,
    height
  ) {
    ctx.save();

    ctx.strokeStyle =
      "rgba(116, 215, 255, 0.035)";

    ctx.lineWidth = 1;

    const spacing = 64;

    for (
      let x = 0;
      x < width;
      x += spacing
    ) {

      ctx.beginPath();

      ctx.moveTo(
        x,
        0
      );

      ctx.lineTo(
        x,
        height
      );

      ctx.stroke();
    }

    for (
      let y = 0;
      y < height;
      y += spacing
    ) {

      ctx.beginPath();

      ctx.moveTo(
        0,
        y
      );

      ctx.lineTo(
        width,
        y
      );

      ctx.stroke();
    }

    ctx.restore();
  }


  function drawLocationMarker(
    ctx,
    state,
    width,
    height
  ) {
    const locationX =
      longitudeToWorldX(
        longitude,
        state.zoom
      );

    const locationY =
      latitudeToWorldY(
        latitude,
        state.zoom
      );

    const screenX =
      locationX -
      state.x +
      width / 2;

    const screenY =
      locationY -
      state.y +
      height / 2;


    if (
      screenX < -30 ||
      screenX > width + 30 ||
      screenY < -30 ||
      screenY > height + 30
    ) {
      return;
    }


    ctx.save();


    ctx.beginPath();

    ctx.arc(
      screenX,
      screenY,
      14,
      0,
      Math.PI * 2
    );

    ctx.strokeStyle =
      "rgba(116, 215, 255, 0.4)";

    ctx.lineWidth = 1;

    ctx.stroke();


    ctx.beginPath();

    ctx.arc(
      screenX,
      screenY,
      5,
      0,
      Math.PI * 2
    );

    ctx.fillStyle =
      "#74d7ff";

    ctx.shadowColor =
      "#74d7ff";

    ctx.shadowBlur = 12;

    ctx.fill();


    ctx.beginPath();

    ctx.arc(
      screenX,
      screenY,
      2,
      0,
      Math.PI * 2
    );

    ctx.fillStyle =
      "#ffffff";

    ctx.shadowBlur = 0;

    ctx.fill();

    ctx.restore();
  }


  /* ============================================================
     SMALL MAP
     ============================================================ */

  function centerSmallMap() {
    if (
      latitude === null ||
      longitude === null
    ) {
      return;
    }

    smallMap.zoom =
      LOCAL_ZOOM;

    smallMap.x =
      longitudeToWorldX(
        longitude,
        smallMap.zoom
      );

    smallMap.y =
      latitudeToWorldY(
        latitude,
        smallMap.zoom
      );
  }


  function drawSmallMap() {
    drawMap(
      smallCanvas,
      smallCtx,
      smallMap
    );
  }


  /* ============================================================
     EXPANDED MAP
     ============================================================ */

  function openMap() {
    const overlay =
      document.getElementById(
        "jarvisMapOverlay"
      );

    overlay.classList.add(
      "visible"
    );

    expanded = true;

    activateMapChat();

    requestAnimationFrame(
      () => {

        resizeCanvas(
          expandedCanvas,
          expandedCtx
        );

        /*
         * Always begin with the world view.
         */

        map.zoom =
          WORLD_ZOOM;

        if (
          latitude !== null &&
          longitude !== null
        ) {

          map.x =
            longitudeToWorldX(
              longitude,
              map.zoom
            );

          map.y =
            latitudeToWorldY(
              latitude,
              map.zoom
            );

        } else {

          map.x =
            longitudeToWorldX(
              0,
              map.zoom
            );

          map.y =
            latitudeToWorldY(
              0,
              map.zoom
            );
        }

        updateZoomUI();

        setMapMessage("");

        drawExpandedMap();
      }
    );
  }


  function closeMap() {
    const overlay =
      document.getElementById(
        "jarvisMapOverlay"
      );

    overlay.classList.remove(
      "visible"
    );

    expanded = false;

    deactivateMapChat();
  }


  function drawExpandedMap() {
    drawMap(
      expandedCanvas,
      expandedCtx,
      map
    );
  }


  /* ============================================================
     MAP NAVIGATION
     ============================================================ */

  function centerOnUser() {
    if (
      latitude === null ||
      longitude === null
    ) {
      setMapMessage(
        "LOCATION NOT AVAILABLE"
      );

      return;
    }

    map.x =
      longitudeToWorldX(
        longitude,
        map.zoom
      );

    map.y =
      latitudeToWorldY(
        latitude,
        map.zoom
      );

    setMapMessage("");

    drawExpandedMap();
  }


  function showWorld() {
    map.zoom =
      WORLD_ZOOM;

    map.x =
      longitudeToWorldX(
        0,
        map.zoom
      );

    map.y =
      latitudeToWorldY(
        0,
        map.zoom
      );

    updateZoomUI();

    drawExpandedMap();
  }


  function zoomMap(
    direction
  ) {
    const oldZoom =
      map.zoom;

    const newZoom =
      Math.max(
        MIN_ZOOM,
        Math.min(
          MAX_ZOOM,
          oldZoom +
            direction
        )
      );

    if (
      newZoom === oldZoom
    ) {
      return;
    }


    const centerLon =
      worldXToLongitude(
        map.x,
        oldZoom
      );

    const centerLat =
      worldYToLatitude(
        map.y,
        oldZoom
      );


    map.zoom =
      newZoom;

    map.x =
      longitudeToWorldX(
        centerLon,
        newZoom
      );

    map.y =
      latitudeToWorldY(
        centerLat,
        newZoom
      );

    updateZoomUI();

    drawExpandedMap();
  }


  /* ============================================================
     DRAGGING
     ============================================================ */

  function startDrag(
    event
  ) {
    dragging = false;

    dragStart = {
      x: event.clientX,
      y: event.clientY,
      mapX: map.x,
      mapY: map.y,
    };

    expandedCanvas.classList.add(
      "dragging"
    );
  }


  function dragMap(
    event
  ) {
    if (!dragStart) {
      return;
    }

    const dx =
      event.clientX -
      dragStart.x;

    const dy =
      event.clientY -
      dragStart.y;


    if (
      Math.abs(dx) > 3 ||
      Math.abs(dy) > 3
    ) {
      dragging = true;
    }


    map.x =
      dragStart.mapX -
      dx;

    map.y =
      dragStart.mapY -
      dy;

    drawExpandedMap();
  }


  function stopDrag() {
    dragStart = null;

    expandedCanvas.classList.remove(
      "dragging"
    );

    setTimeout(
      () => {
        dragging = false;
      },
      0
    );
  }


  /* ============================================================
     MAP CHAT
     ============================================================ */

  function activateMapChat() {
    const input =
      document.getElementById(
        "chatInput"
      );

    if (!input) {
      return;
    }

    input.dataset.previousPlaceholder =
      input.placeholder;

    input.placeholder =
      "Map / location query...";

    input.setAttribute(
      "aria-label",
      "Ask Jarvis about the map"
    );
  }


  function deactivateMapChat() {
    const input =
      document.getElementById(
        "chatInput"
      );

    if (!input) {
      return;
    }

    input.placeholder =
      input.dataset.previousPlaceholder ||
      "Talk to Jarvis...";

    input.removeAttribute(
      "aria-label"
    );
  }


  function handleMapChatSubmit(
    event
  ) {
    if (!expanded) {
      return;
    }

    /*
     * Stop hud.js from processing this same submission.
     */

    event.preventDefault();
    event.stopImmediatePropagation();

    const input =
      document.getElementById(
        "chatInput"
      );

    if (!input) {
      return;
    }

    const text =
      input.value.trim();

    if (!text) {
      return;
    }

    input.value = "";

    /*
     * Local map commands are handled immediately.
     */

    if (
      handleLocalMapCommand(
        text
      )
    ) {
      return;
    }

    /*
     * Everything else becomes a normal Jarvis
     * message with map context attached.
     */

    sendMapQuestion(
      text
    );
  }


  function handleLocalMapCommand(
    rawText
  ) {
    const text =
      rawText
        .toLowerCase()
        .replace(
          /[?!.,]/g,
          ""
        )
        .trim();


    /*
     * CLOSE
     */

    if (
      text === "close map" ||
      text === "exit map" ||
      text === "hide map"
    ) {
      closeMap();

      return true;
    }


    /*
     * WORLD
     */

    if (
      text === "world map" ||
      text === "show world" ||
      text === "show the world" ||
      text === "world"
    ) {
      appendMapChatLine(
        rawText,
        "user"
      );

      appendMapChatLine(
        "Switching to world view.",
        "jarvis"
      );

      showWorld();

      return true;
    }


    /*
     * CENTER
     */

    if (
      text === "center on me" ||
      text === "center on my location" ||
      text === "show my location" ||
      text === "locate me" ||
      text === "find me"
    ) {
      appendMapChatLine(
        rawText,
        "user"
      );

      appendMapChatLine(
        "Centering the map on your location.",
        "jarvis"
      );

      centerOnUser();

      return true;
    }


    /*
     * ZOOM IN
     */

    if (
      text === "zoom in" ||
      text === "zoom closer" ||
      text === "zoom in once"
    ) {
      appendMapChatLine(
        rawText,
        "user"
      );

      zoomMap(1);

      appendMapChatLine(
        `Zoom level ${map.zoom}.`,
        "jarvis"
      );

      return true;
    }


    /*
     * ZOOM OUT
     */

    if (
      text === "zoom out" ||
      text === "zoom farther" ||
      text === "zoom out once"
    ) {
      appendMapChatLine(
        rawText,
        "user"
      );

      zoomMap(-1);

      appendMapChatLine(
        `Zoom level ${map.zoom}.`,
        "jarvis"
      );

      return true;
    }


    /*
     * MULTIPLE ZOOM STEPS
     */

    const zoomMatch =
      text.match(
        /^zoom (in|out) (\d+)$/
      );

    if (zoomMatch) {

      const direction =
        zoomMatch[1] === "in"
          ? 1
          : -1;

      const amount =
        Math.min(
          10,
          parseInt(
            zoomMatch[2],
            10
          )
        );

      appendMapChatLine(
        rawText,
        "user"
      );

      for (
        let i = 0;
        i < amount;
        i++
      ) {
        zoomMap(
          direction
        );
      }

      appendMapChatLine(
        `Zoom level ${map.zoom}.`,
        "jarvis"
      );

      return true;
    }


    /*
     * WHERE AM I
     */

    if (
      text === "where am i" ||
      text === "my location" ||
      text === "my coordinates" ||
      text === "coordinates" ||
      text === "where are we"
    ) {
      appendMapChatLine(
        rawText,
        "user"
      );

      if (
        latitude === null ||
        longitude === null
      ) {

        appendMapChatLine(
          "Your location is not available yet.",
          "jarvis"
        );

      } else {

        appendMapChatLine(
          `Current position: ${latitude.toFixed(6)}, ${longitude.toFixed(6)}. Accuracy: ${Math.round(accuracy || 0)}m.`,
          "jarvis"
        );
      }

      return true;
    }


    return false;
  }


  function appendMapChatLine(
    text,
    cls
  ) {
    const chatLog =
      document.getElementById(
        "chatLog"
      );

    if (!chatLog) {
      return;
    }

    const element =
      document.createElement(
        "div"
      );

    element.className =
      `chat-line ${cls}`;

    element.textContent =
      text;

    chatLog.appendChild(
      element
    );

    chatLog.scrollTop =
      chatLog.scrollHeight;
  }


  /* ============================================================
     SEND NATURAL LANGUAGE MAP QUESTION
     ============================================================ */

  function sendMapQuestion(
    question
  ) {
    appendMapChatLine(
      question,
      "user"
    );


    const socket =
      window.JarvisSocket;

    /*
     * hud.js currently keeps its socket private.
     *
     * If a future version exposes it as JarvisSocket,
     * use that directly.
     *
     * Otherwise fall back to the existing WebSocket
     * discovery mechanism below.
     */

    const activeSocket =
      socket ||
      findJarvisSocket();


    if (
      !activeSocket ||
      activeSocket.readyState !==
        WebSocket.OPEN
    ) {

      appendMapChatLine(
        "Jarvis is not connected to the backend.",
        "system"
      );

      return;
    }


    const context =
      buildMapContext();


    activeSocket.send(
      JSON.stringify({
        type: "user_message",

        text:
          `[MAP CONTEXT]\n` +
          `${context}\n\n` +
          `[USER MAP QUESTION]\n` +
          question,
      })
    );
  }


  function buildMapContext() {
    const location =
      latitude !== null &&
      longitude !== null
        ? `${latitude.toFixed(6)}, ${longitude.toFixed(6)}`
        : "unavailable";

    const accuracyText =
      accuracy !== null
        ? `${Math.round(accuracy)} meters`
        : "unavailable";

    const centerLat =
      worldYToLatitude(
        map.y,
        map.zoom
      );

    const centerLon =
      worldXToLongitude(
        map.x,
        map.zoom
      );

    return [
      `User location: ${location}`,
      `Location accuracy: ${accuracyText}`,
      `Map center: ${centerLat.toFixed(6)}, ${centerLon.toFixed(6)}`,
      `Map zoom: ${map.zoom}`,
      `Map mode: expanded world/local map`,
    ].join("\n");
  }


  /*
   * hud.js does not currently expose its socket.
   *
   * We therefore inspect the page's known WebSocket instances
   * only as a compatibility fallback.
   */

  function findJarvisSocket() {
    if (
      window.JarvisSocket &&
      window.JarvisSocket.readyState ===
        WebSocket.OPEN
    ) {
      return window.JarvisSocket;
    }

    return null;
  }


  /* ============================================================
     INITIALIZATION
     ============================================================ */

  function init() {
    createDOM();

    resizeCanvas(
      smallCanvas,
      smallCtx
    );

    resizeCanvas(
      expandedCanvas,
      expandedCtx
    );

    drawSmallMap();

    startLocationTracking();

    console.log(
      "[Jarvis Maps] Map extension initialized."
    );
  }


  if (
    document.readyState ===
    "loading"
  ) {
    document.addEventListener(
      "DOMContentLoaded",
      init
    );
  } else {
    init();
  }

})();