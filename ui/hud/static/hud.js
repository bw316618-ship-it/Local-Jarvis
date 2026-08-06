/*
 * Jarvis graphical HUD client.
 *
 * The arc reactor / data storm visuals are entirely CSS-driven (hud.css)
 * -- this file's job is the WebSocket protocol: building the reactor's
 * tick dial once, toggling #wrap's data-state/data-mode attributes, and
 * now also running the chat panel and the risky-tool confirmation modal.
 *
 * Message types received from the server (ui/hud_server.py):
 *   state            -- { state, meta }              always sent
 *   reply_chunk      -- { text }                      chat only (daemon)
 *   tool_step        -- { text }                       "
 *   plan             -- { text }                        "
 *   reply_done       -- {}                               "
 *   chat_unavailable -- { text }   (no JarvisLLM attached -- main.py case)
 *   confirm_request  -- { id, tool, args }              chat only (daemon)
 *   error            -- { text }
 *
 * Message types sent to the server:
 *   user_message     -- { type, text }
 *   confirm_response -- { type, id, approved }
 */

const WS_PORT = 8766;
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
let pendingConfirmId = null;
let replyLineEl = null; // the in-progress Jarvis chat bubble being streamed into

// -- Reactor dial ------------------------------------------------------

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

// -- Mode toggle ---------------------------------------------------------

let stormInitialized = false;
let stormUsingWebGL = false;

function readThemeVars() {
  const style = getComputedStyle(wrap);
  return {
    color: style.getPropertyValue("--glow").trim(),
    speed: parseFloat(style.getPropertyValue("--speed")) || 1,
    pulse: parseFloat(style.getPropertyValue("--pulse")) || 1,
  };
}

function syncStormTheme() {
  if (!stormUsingWebGL || !window.StormScene) return;
  const { color, speed, pulse } = readThemeVars();
  window.StormScene.setTheme({ color, speedMultiplier: speed, pulse });
}

function activateStormVisual() {
  const stormCanvas = document.getElementById("stormCanvas");
  const stormFallback = document.getElementById("stormFallback");

  if (!stormInitialized) {
    stormInitialized = true;
    const { color } = readThemeVars();
    const ok = window.StormScene && window.StormScene.init(stormCanvas, color);
    stormUsingWebGL = !!ok;
    if (!stormUsingWebGL) {
      // Three.js didn't load (no internet on first load) or WebGL isn't
      // available -- fall back to the CSS-turbulence layers so storm
      // mode still works, just with the simpler look.
      stormFallback.classList.add("active");
      stormCanvas.style.display = "none";
    }
  }

  if (stormUsingWebGL) {
    syncStormTheme();
    window.StormScene.setState(wrap.dataset.state || "idle");
    window.StormScene.resize();
    window.StormScene.start();
  }
}

function deactivateStormVisual() {
  if (stormUsingWebGL && window.StormScene) {
    window.StormScene.stop(); // pause the render loop -- no need to burn
    // GPU cycles animating a mode that isn't visible
  }
}

// -- Technical glyph readouts (pure DOM -- works in both WebGL and
//    fallback storm modes, unlike the particle-specific logic above) ---

const GLYPH_CHARS = "0123456789ABCDEF";
let glyphIntervalId = null;

function randomGlyphString(len) {
  let s = "";
  for (let i = 0; i < len; i++) {
    s += GLYPH_CHARS[Math.floor(Math.random() * GLYPH_CHARS.length)];
  }
  return s;
}

function startGlyphCycling() {
  if (glyphIntervalId !== null) return;
  const glyphEls = document.querySelectorAll(".glyph");
  glyphIntervalId = setInterval(() => {
    glyphEls.forEach((el) => {
      el.textContent = randomGlyphString(6 + Math.floor(Math.random() * 4));
    });
  }, 450);
}

function stopGlyphCycling() {
  if (glyphIntervalId !== null) {
    clearInterval(glyphIntervalId);
    glyphIntervalId = null;
  }
}

function applyMode(mode) {
  wrap.dataset.mode = mode;
  modeToggle.textContent = mode === "storm" ? "REACTOR MODE" : "STORM MODE";
  if (mode === "storm") {
    activateStormVisual();
    startGlyphCycling();
  } else {
    deactivateStormVisual();
    stopGlyphCycling();
  }
}

applyMode(localStorage.getItem(MODE_STORAGE_KEY) || "reactor");

modeToggle.addEventListener("click", () => {
  const next = wrap.dataset.mode === "storm" ? "reactor" : "storm";
  applyMode(next);
  localStorage.setItem(MODE_STORAGE_KEY, next);
});

// -- State -------------------------------------------------------------

function setState(stateName, meta) {
  const label = STATE_LABELS[stateName] || STATE_LABELS.idle;
  wrap.dataset.state = STATE_LABELS[stateName] ? stateName : "idle";
  statusText.textContent = meta && meta.name ? `${label} \u2014 ${meta.name}` : label;
  syncStormTheme();
  if (stormUsingWebGL && window.StormScene) {
    window.StormScene.setState(wrap.dataset.state);
  }
}

// -- Chat panel ----------------------------------------------------------

function appendChatLine(text, cls) {
  const el = document.createElement("div");
  el.className = `chat-line ${cls}`;
  el.textContent = text;
  chatLog.appendChild(el);
  chatLog.scrollTop = chatLog.scrollHeight;
  return el;
}

chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = chatInput.value.trim();
  if (!text) return;

  appendChatLine(text, "user");
  replyLineEl = null; // next reply_chunk starts a fresh Jarvis bubble

  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "user_message", text }));
  } else {
    appendChatLine("Not connected -- waiting to reconnect...", "system");
  }

  chatInput.value = "";
});

function handleReplyChunk(text) {
  if (!replyLineEl) {
    replyLineEl = appendChatLine(text, "jarvis");
  } else {
    replyLineEl.textContent += ` ${text}`;
  }
  chatLog.scrollTop = chatLog.scrollHeight;
}

function handleToolStep(text) {
  appendChatLine(text, "tool");
}

function handlePlan(text) {
  appendChatLine(`Plan:\n${text}`, "tool");
}

function handleReplyDone() {
  replyLineEl = null;
  setState("idle");
}

function handleChatUnavailable(text) {
  appendChatLine(text, "system");
}

function handleError(text) {
  appendChatLine(text, "system");
  setState("error");
}

// -- Confirmation modal ----------------------------------------------------

function showConfirm(id, tool, args) {
  pendingConfirmId = id;
  confirmBody.textContent = `${tool}(${JSON.stringify(args)})`;
  confirmOverlay.classList.remove("hidden");
}

function resolveConfirm(approved) {
  if (!pendingConfirmId) return;
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "confirm_response", id: pendingConfirmId, approved }));
  }
  pendingConfirmId = null;
  confirmOverlay.classList.add("hidden");
}

confirmApprove.addEventListener("click", () => resolveConfirm(true));
confirmDeny.addEventListener("click", () => resolveConfirm(false));

// -- WebSocket -------------------------------------------------------------

function connect() {
  socket = new WebSocket(`ws://${location.hostname}:${WS_PORT}`);

  socket.onopen = () => {
    statusDot.classList.add("connected");
    if (!wrap.dataset.state || wrap.dataset.state === "idle") {
      statusText.textContent = "CONNECTED";
    }
  };

  socket.onmessage = (event) => {
    let data;
    try {
      data = JSON.parse(event.data);
    } catch (e) {
      return; // malformed message -- ignore rather than crash the HUD
    }

    switch (data.type) {
      case "state":
        setState(data.state, data.meta);
        break;
      case "reply_chunk":
        handleReplyChunk(data.text);
        break;
      case "tool_step":
        handleToolStep(data.text);
        break;
      case "plan":
        handlePlan(data.text);
        break;
      case "reply_done":
        handleReplyDone();
        break;
      case "chat_unavailable":
        handleChatUnavailable(data.text);
        break;
      case "confirm_request":
        showConfirm(data.id, data.tool, data.args);
        break;
      case "error":
        handleError(data.text);
        break;
      default:
        break; // unknown message type -- ignore, forward-compatible
    }
  };

  socket.onclose = () => {
    statusDot.classList.remove("connected");
    statusText.textContent = "disconnected \u2014 retrying...";
    setTimeout(connect, RECONNECT_DELAY_MS);
  };

  socket.onerror = () => {
    socket.close();
  };
}

connect();
