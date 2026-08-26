/*
 * Jarvis graphical HUD client.
 *
 * Step 10:
 *   - registers the browser's Step 9 device identity with hud_server.py
 *   - receives the authoritative device registry
 *   - exposes connected devices through window.JarvisDevices
 */

const RECONNECT_DELAY_MS = 2000;
const TICK_COUNT = 60;

const STATE_LABELS = {
  idle: "IDLE",
  listening: "LISTENING",
  thinking: "THINKING",
  speaking: "SPEAKING",
  tool: "WORKING",
  error: "ERROR",
};

const MODE_STORAGE_KEY = "jarvis-hud-mode";

const wrap = document.getElementById("wrap");
const dial = document.getElementById("dial");
const statusDot = document.getElementById("dot");
const statusText = document.getElementById("statustext");
const modeToggle = document.getElementById("modeToggle");

const chatLog = document.getElementById("chatLog");
const chatForm = document.getElementById("chatForm");
const chatInput = document.getElementById("chatInput");

const confirmOverlay = document.getElementById("confirmOverlay");
const confirmBody = document.getElementById("confirmBody");
const confirmApprove = document.getElementById("confirmApprove");
const confirmDeny = document.getElementById("confirmDeny");

let socket = null;
window.JarvisSocket = null;
let pendingConfirmId = null;
let replyLineEl = null;

// ------------------------------------------------------------
// Reactor dial
// ------------------------------------------------------------

function buildDial() {
  const fragment = document.createDocumentFragment();

  for (let i = 0; i < TICK_COUNT; i++) {
    const tick = document.createElement("span");
    tick.style.setProperty("--i", i);
    fragment.appendChild(tick);
  }

  dial.appendChild(fragment);
}

buildDial();

// ------------------------------------------------------------
// Device registry
// ------------------------------------------------------------

function getLocalDevice() {
  if (window.JarvisDevice) {
    return window.JarvisDevice;
  }

  return {
    id: "unknown",
    type: "unknown",
    name: "Unknown",
  };
}

function authenticateDevice() {
  const device = getLocalDevice();
  const token =
    window.JarvisDeviceAuth?.getToken?.() || "";

  if (
    !socket ||
    socket.readyState !== WebSocket.OPEN
  ) {
    return;
  }

  socket.send(
    JSON.stringify({
      type: "authenticate",
      device_id: device.id,
      device_type: device.type,
      name: device.name,
      token,
    })
  );
}

function handleAuthGranted(data) {
  if (data.token) {
    window.JarvisDeviceAuth?.setToken(data.token);
  }

  wrap.dataset.authenticated = "true";
  statusDot.classList.add("connected");

  statusText.textContent =
    `DEVICE: ${getLocalDevice().type.toUpperCase()} | TRUSTED`;

  console.log(
    "[Jarvis Auth] Device authenticated:",
    data.device
  );
}

function handleAuthPending(data) {
  wrap.dataset.authenticated = "false";
  statusDot.classList.remove("connected");

  statusText.textContent =
    "ACCESS PENDING — APPROVAL REQUIRED";

  appendChatLine(
    data.text ||
      "Waiting for approval from a trusted Jarvis device.",
    "system"
  );
}

function handleAuthDenied(data) {
  wrap.dataset.authenticated = "false";
  statusDot.classList.remove("connected");

  statusText.textContent = "ACCESS DENIED";

  appendChatLine(
    data.text || "Device access was denied.",
    "system"
  );
}

function handleAuthRequired(data) {
  wrap.dataset.authenticated = "false";
  statusDot.classList.remove("connected");

  statusText.textContent =
    "AUTHENTICATION REQUIRED";

  appendChatLine(
    data.text ||
      "This device needs a valid Jarvis token.",
    "system"
  );
}

function showDeviceAccessRequest(data) {
  const device = data.device || {};
  const requestId = data.request_id;

  const message =
    `Allow this device to access Jarvis?\n\n` +
    `Name: ${device.name || "Unknown"}\n` +
    `Type: ${(device.device_type || "unknown").toUpperCase()}\n` +
    `ID: ${device.device_id || "Unknown"}`;

  const approved = window.confirm(message);

  if (
    socket &&
    socket.readyState === WebSocket.OPEN
  ) {
    socket.send(
      JSON.stringify({
        type: "device_approval",
        request_id: requestId,
        approved,
      })
    );
  }
}

function requestDeviceRevocation(deviceId) {
  if (
    !socket ||
    socket.readyState !== WebSocket.OPEN
  ) {
    return;
  }

  socket.send(
    JSON.stringify({
      type: "revoke_device",
      device_id: deviceId,
    })
  );
}

function setDeviceRegistry(devices) {
  const normalized = Array.isArray(devices)
    ? devices
    : [];

  window.JarvisDevices = normalized;

  console.log(
    "[Jarvis Step 10] Device registry updated:",
    normalized
  );

  window.dispatchEvent(
    new CustomEvent(
      "jarvis-devices-updated",
      {
        detail: normalized,
      }
    )
  );

  updateDeviceStatus(normalized);
}

function updateDeviceStatus(devices) {
  const local = getLocalDevice();

  const localConnected = devices.some(
    (device) =>
      device.device_id === local.id
  );

  const phoneConnected = devices.some(
    (device) =>
      device.device_type === "phone"
  );

  const pcConnected = devices.some(
    (device) =>
      device.device_type === "pc"
  );

  wrap.dataset.phoneConnected =
    phoneConnected
      ? "true"
      : "false";

  wrap.dataset.pcConnected =
    pcConnected
      ? "true"
      : "false";

  if (
    localConnected &&
    socket?.readyState ===
      WebSocket.OPEN
  ) {
    statusText.textContent =
      `DEVICE: ${local.type.toUpperCase()} | ` +
      `PHONE: ${phoneConnected ? "ON" : "OFF"} | ` +
      `PC: ${pcConnected ? "ON" : "OFF"}`;
  }
}

// ------------------------------------------------------------
// Mode toggle
// ------------------------------------------------------------

let stormInitialized = false;
let stormUsingWebGL = false;

function readThemeVars() {
  const style =
    getComputedStyle(wrap);

  return {
    color:
      style
        .getPropertyValue("--glow")
        .trim(),

    speed:
      parseFloat(
        style.getPropertyValue(
          "--speed"
        )
      ) || 1,

    pulse:
      parseFloat(
        style.getPropertyValue(
          "--pulse"
        )
      ) || 1,
  };
}

function syncStormTheme() {
  if (
    !stormUsingWebGL ||
    !window.StormScene
  ) {
    return;
  }

  const {
    color,
    speed,
    pulse,
  } = readThemeVars();

  window.StormScene.setTheme({
    color,
    speedMultiplier: speed,
    pulse,
  });
}

function activateStormVisual() {
  const stormCanvas =
    document.getElementById(
      "stormCanvas"
    );

  const stormFallback =
    document.getElementById(
      "stormFallback"
    );

  if (!stormInitialized) {
    const { color } =
      readThemeVars();

    const ok =
      window.StormScene &&
      window.StormScene.init(
        stormCanvas,
        color
      );

    stormUsingWebGL = !!ok;

    if (stormUsingWebGL) {
      // Only latch "already initialized" on success. A failed attempt
      // (WebGL unavailable, module still loading, a transient GPU
      // hiccup) used to set this flag too, which permanently locked
      // the page into the CSS fallback for the rest of that page's
      // lifetime -- switching back to storm mode later would just
      // reapply the fallback without ever calling StormScene.init()
      // again, even after whatever caused the failure was fixed or
      // resolved itself. Leaving it false lets the next storm-mode
      // activation retry cleanly.
      stormInitialized = true;

      // Undo whatever a *previous* failed attempt left behind -- if
      // this succeeded on a retry, the fallback may already be marked
      // "active" and the canvas hidden from that earlier failure, and
      // both need to be reversed or the working WebGL canvas would
      // stay hidden behind (or alongside) the CSS fallback.
      stormFallback.classList.remove(
        "active"
      );

      stormCanvas.style.display =
        "";
    } else {
      stormFallback.classList.add(
        "active"
      );

      stormCanvas.style.display =
        "none";
    }
  }

  if (stormUsingWebGL) {
    syncStormTheme();

    window.StormScene.setState(
      wrap.dataset.state ||
        "idle"
    );

    window.StormScene.resize();
    window.StormScene.start();
  }
}

function deactivateStormVisual() {
  if (
    stormUsingWebGL &&
    window.StormScene
  ) {
    window.StormScene.stop();
  }
}

// ------------------------------------------------------------
// Storm glyphs
// ------------------------------------------------------------

const GLYPH_CHARS =
  "0123456789ABCDEF";

let glyphIntervalId = null;

function randomGlyphString(len) {
  let s = "";

  for (let i = 0; i < len; i++) {
    s +=
      GLYPH_CHARS[
        Math.floor(
          Math.random() *
            GLYPH_CHARS.length
        )
      ];
  }

  return s;
}

function startGlyphCycling() {
  if (
    glyphIntervalId !== null
  ) {
    return;
  }

  const glyphEls =
    document.querySelectorAll(
      ".glyph"
    );

  glyphIntervalId =
    setInterval(() => {
      glyphEls.forEach((el) => {
        el.textContent =
          randomGlyphString(
            6 +
              Math.floor(
                Math.random() * 4
              )
          );
      });
    }, 450);
}

function stopGlyphCycling() {
  if (
    glyphIntervalId !== null
  ) {
    clearInterval(
      glyphIntervalId
    );

    glyphIntervalId = null;
  }
}

function applyMode(mode) {
  wrap.dataset.mode = mode;

  modeToggle.textContent =
    mode === "storm"
      ? "REACTOR MODE"
      : "STORM MODE";

  if (mode === "storm") {
    activateStormVisual();
    startGlyphCycling();
  } else {
    deactivateStormVisual();
    stopGlyphCycling();
  }
}

applyMode(
  localStorage.getItem(
    MODE_STORAGE_KEY
  ) || "reactor"
);

modeToggle.addEventListener(
  "click",
  () => {
    const next =
      wrap.dataset.mode ===
      "storm"
        ? "reactor"
        : "storm";

    applyMode(next);

    localStorage.setItem(
      MODE_STORAGE_KEY,
      next
    );
  }
);

// ------------------------------------------------------------
// State
// ------------------------------------------------------------

function setState(
  stateName,
  meta
) {
  const label =
    STATE_LABELS[stateName] ||
    STATE_LABELS.idle;

  wrap.dataset.state =
    STATE_LABELS[stateName]
      ? stateName
      : "idle";

  statusText.textContent =
    meta && meta.name
      ? `${label} — ${meta.name}`
      : label;

  syncStormTheme();

  if (
    stormUsingWebGL &&
    window.StormScene
  ) {
    window.StormScene.setState(
      wrap.dataset.state
    );
  }
}

// ------------------------------------------------------------
// Chat
// ------------------------------------------------------------

function appendChatLine(
  text,
  cls
) {
  const el =
    document.createElement(
      "div"
    );

  el.className =
    `chat-line ${cls}`;

  el.textContent = text;

  chatLog.appendChild(el);

  chatLog.scrollTop =
    chatLog.scrollHeight;

  return el;
}

chatForm.addEventListener(
  "submit",
  (event) => {
    event.preventDefault();

    const text =
      chatInput.value.trim();

    if (!text) {
      return;
    }

    appendChatLine(
      text,
      "user"
    );

    replyLineEl = null;

    if (
      socket &&
      socket.readyState ===
        WebSocket.OPEN &&
      wrap.dataset.authenticated ===
        "true"
    ) {
      socket.send(
        JSON.stringify({
          type: "user_message",
          text,
          map_context:
            window.JarvisMap?.getContext?.() || null,
        })
      );
    } else {
      appendChatLine(
        "Jarvis is not authenticated on this device.",
        "system"
      );
    }

    chatInput.value = "";
  }
);

function handleReplyChunk(text) {
  if (!replyLineEl) {
    replyLineEl =
      appendChatLine(
        text,
        "jarvis"
      );
  } else {
    replyLineEl.textContent +=
      ` ${text}`;
  }

  chatLog.scrollTop =
    chatLog.scrollHeight;
}

function handleToolStep(text) {
  appendChatLine(
    text,
    "tool"
  );
}

function handlePlan(text) {
  appendChatLine(
    `Plan:\n${text}`,
    "tool"
  );
}

function handleReplyDone() {
  replyLineEl = null;
  setState("idle");
}

function handleChatUnavailable(
  text
) {
  appendChatLine(
    text,
    "system"
  );
}

function handleError(text) {
  appendChatLine(
    text,
    "system"
  );

  setState("error");
}

// ------------------------------------------------------------
// Confirmation
// ------------------------------------------------------------

function showConfirm(
  id,
  tool,
  args
) {
  pendingConfirmId = id;

  confirmBody.textContent =
    `${tool}(${JSON.stringify(
      args
    )})`;

  confirmOverlay.classList.remove(
    "hidden"
  );
}

function resolveConfirm(
  approved
) {
  if (!pendingConfirmId) {
    return;
  }

  if (
    socket &&
    socket.readyState ===
      WebSocket.OPEN
  ) {
    socket.send(
      JSON.stringify({
        type: "confirm_response",
        id: pendingConfirmId,
        approved,
      })
    );
  }

  pendingConfirmId = null;

  confirmOverlay.classList.add(
    "hidden"
  );
}

confirmApprove.addEventListener(
  "click",
  () => resolveConfirm(true)
);

confirmDeny.addEventListener(
  "click",
  () => resolveConfirm(false)
);

// ------------------------------------------------------------
// WebSocket
// ------------------------------------------------------------

function connect() {
  if (!window.JarvisBackend) {
    console.error(
      "[Jarvis Step 15] backend_client.js was not loaded."
    );
    statusText.textContent =
      "BACKEND CLIENT UNAVAILABLE";
    return;
  }

  socket = window.JarvisBackend.createSocket();
  window.JarvisSocket = socket;

  socket.onopen = () => {
    console.log(
      "[Jarvis Step 15] Connected to Jarvis backend:",
      window.JarvisBackend?.getUrl?.()
    );

    statusDot.classList.add(
      "connected"
    );

    wrap.dataset.authenticated =
      "false";

    statusText.textContent =
      "AUTHENTICATING...";

    authenticateDevice();
  };

  socket.onmessage = (
    event
  ) => {
    let data;

    try {
      data = JSON.parse(
        event.data
      );
    } catch (e) {
      console.error(
        "[Jarvis Step 10] Invalid WebSocket message:",
        event.data
      );
      return;
    }

    switch (data.type) {
      case "auth_granted":
        handleAuthGranted(data);
        break;

      case "pairing_approved":
        // Backward-compatible handling for a backend that separates
        // pairing approval from the final authentication event.
        if (data.token) {
          window.JarvisDeviceAuth?.setToken?.(
            data.token
          );
        }
        handleAuthGranted(data);
        break;

      case "auth_pending":
        handleAuthPending(data);
        break;

      case "auth_denied":
        handleAuthDenied(data);
        break;

      case "auth_required":
        handleAuthRequired(data);
        break;

      case "device_access_request":
        showDeviceAccessRequest(data);
        break;

      case "device_revoked":
        window.JarvisDeviceAuth?.clearToken?.();

        wrap.dataset.authenticated =
          "false";

        statusDot.classList.remove(
          "connected"
        );

        statusText.textContent =
          "DEVICE REVOKED";
        break;

      case "device_registered":
        console.log(
          "[Jarvis Step 10] Server confirmed registration:",
          data.device
        );
        break;

      case "device_registry":
        setDeviceRegistry(
          data.devices
        );
        break;

      case "state":
        setState(
          data.state,
          data.meta
        );
        break;

      case "reply_chunk":
        handleReplyChunk(
          data.text
        );
        break;

      case "tool_step":
        handleToolStep(
          data.text
        );
        break;

      case "plan":
        handlePlan(
          data.text
        );
        break;

      case "reply_done":
        handleReplyDone();
        break;

      case "chat_unavailable":
        handleChatUnavailable(
          data.text
        );
        break;

      case "confirm_request":
        showConfirm(
          data.id,
          data.tool,
          data.args
        );
        break;

      case "system_status":
        // Live CPU/memory/disk/uptime pushed periodically by
        // ui/hud_server.py's _system_status_loop. Stored on window
        // rather than handled here directly, matching the existing
        // window.JarvisDevices pattern -- inspector.js is a deliberately
        // non-invasive observer that reads shared state rather than
        // hooking into this socket handler itself.
        window.JarvisSystemStatus = data;
        break;

      case "error":
        handleError(
          data.text
        );
        break;

      case "map_action":
        window.JarvisMap?.handleAction?.(data);
        break;

      default:
        break;
    }
  };

  socket.onclose = () => {
    console.log(
      "[Jarvis Step 15] Jarvis backend disconnected."
    );

    statusDot.classList.remove(
      "connected"
    );

    wrap.dataset.authenticated =
      "false";

    statusText.textContent =
      "disconnected — retrying...";

    setTimeout(
      connect,
      RECONNECT_DELAY_MS
    );
  };

  socket.onerror = (
    error
  ) => {
    console.error(
      "[Jarvis Step 15] Backend WebSocket error:",
      error
    );

    socket.close();
  };
}

connect();