/*
 * Jarvis graphical HUD client.
 *
 * With the arc reactor now built entirely in CSS (hud.css), this file
 * has one job left: build the 60-tick dial once, connect to Jarvis's
 * WebSocket, and flip #wrap's `data-state` attribute (plus the status
 * label) when a state message arrives. No animation loop, no canvas --
 * the browser's own CSS engine handles all of that now.
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

const wrap = document.getElementById("wrap");
const dial = document.getElementById("dial");
const statusDot = document.getElementById("dot");
const statusText = document.getElementById("statustext");
const modeToggle = document.getElementById("modeToggle");

const MODE_STORAGE_KEY = "jarvis-hud-mode";

function applyMode(mode) {
  wrap.dataset.mode = mode;
  modeToggle.textContent = mode === "storm" ? "REACTOR MODE" : "STORM MODE";
}

applyMode(localStorage.getItem(MODE_STORAGE_KEY) || "reactor");

modeToggle.addEventListener("click", () => {
  const next = wrap.dataset.mode === "storm" ? "reactor" : "storm";
  applyMode(next);
  localStorage.setItem(MODE_STORAGE_KEY, next);
});

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

function setState(stateName, meta) {
  const label = STATE_LABELS[stateName] || STATE_LABELS.idle;
  wrap.dataset.state = STATE_LABELS[stateName] ? stateName : "idle";
  statusText.textContent = meta && meta.name ? `${label} \u2014 ${meta.name}` : label;
}

function connect() {
  const ws = new WebSocket(`ws://${location.hostname}:${WS_PORT}`);

  ws.onopen = () => {
    statusDot.classList.add("connected");
    if (!wrap.dataset.state || wrap.dataset.state === "idle") {
      statusText.textContent = "CONNECTED";
    }
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data && data.state) {
        setState(data.state, data.meta);
      }
    } catch (e) {
      // Malformed message -- ignore rather than crash the HUD.
    }
  };

  ws.onclose = () => {
    statusDot.classList.remove("connected");
    statusText.textContent = "disconnected \u2014 retrying...";
    setTimeout(connect, RECONNECT_DELAY_MS);
  };

  ws.onerror = () => {
    ws.close();
  };
}

connect();
