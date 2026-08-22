/*
 * JARVIS HUD INSPECTOR
 *
 * Non-invasive observability layer.
 *
 * It intentionally does not replace hud.js.
 * It observes the existing HUD DOM and the existing
 * JarvisDevices event exposed by device.js.
 */

(() => {
  "use strict";

  const MAX_ACTIVITY = 80;
  const MAX_TIMELINE = 40;

  const inspector = document.getElementById("hudInspector");

  if (!inspector) {
    console.error("[Jarvis Inspector] Root element missing.");
    return;
  }

  const body = inspector.querySelector(".inspector-body");
  const collapseButton =
    document.getElementById("inspectorCollapse");

  const stateOrb =
    document.getElementById("inspectorStateOrb");

  const stateName =
    document.getElementById("inspectorStateName");

  const stateDetail =
    document.getElementById("inspectorStateDetail");

  const timeline =
    document.getElementById("inspectorTimeline");

  const activity =
    document.getElementById("inspectorActivity");

  const devices =
    document.getElementById("inspectorDevices");

  const diag =
    document.getElementById("inspectorDiagnostics");

  const deviceCount =
    document.getElementById("inspectorDeviceCount");

  const eventCount =
    document.getElementById("inspectorEventCount");

  const sessionTime =
    document.getElementById("inspectorSessionTime");

  const chatLog =
    document.getElementById("chatLog");

  const statusText =
    document.getElementById("statustext");

  const wrap =
    document.getElementById("wrap");

  const startTime = performance.now();

  let eventCounter = 0;
  let currentState = "idle";
  let lastActivityText = "";
  let timelineState = null;

  const timelineStages = [
    {
      id: "input",
      label: "INPUT",
    },
    {
      id: "intent",
      label: "INTENT",
    },
    {
      id: "memory",
      label: "MEMORY",
    },
    {
      id: "rag",
      label: "RAG",
    },
    {
      id: "model",
      label: "MODEL",
    },
    {
      id: "tool",
      label: "TOOL",
    },
    {
      id: "response",
      label: "RESPONSE",
    },
  ];

  function nowString() {
    return new Date().toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function setVisible() {
    inspector.classList.add("visible");
  }

  function addActivity(text, type = "system") {
    const normalized = String(text || "").trim();

    if (!normalized) {
      return;
    }

    if (normalized === lastActivityText) {
      return;
    }

    lastActivityText = normalized;
    eventCounter += 1;

    const item = document.createElement("div");

    item.className =
      `activity-item ${type}`;

    item.innerHTML = `
      <span class="activity-time">
        ${escapeHtml(nowString())}
      </span>

      <span class="activity-marker">●</span>

      <span class="activity-text">
        ${escapeHtml(normalized)}
      </span>
    `;

    activity.prepend(item);

    while (activity.children.length > MAX_ACTIVITY) {
      activity.lastElementChild.remove();
    }

    if (eventCount) {
      eventCount.textContent = String(eventCounter);
    }

    setVisible();
  }

  function updateState(state, detail = "") {
    currentState = state || "idle";

    const labelMap = {
      idle: "IDLE",
      listening: "LISTENING",
      thinking: "THINKING",
      speaking: "SPEAKING",
      tool: "WORKING",
      error: "ERROR",
    };

    const label =
      labelMap[currentState] ||
      currentState.toUpperCase();

    if (stateName) {
      stateName.textContent = label;
    }

    if (stateDetail) {
      stateDetail.textContent =
        detail ||
        "Jarvis runtime state";
    }

    if (stateOrb) {
      stateOrb.classList.toggle(
        "active",
        currentState !== "idle" &&
        currentState !== "error"
      );
    }

    if (currentState === "error") {
      stateOrb?.classList.add("active");
    }

    updateTimelineFromState(currentState);

    addActivity(
      detail
        ? `${label} — ${detail}`
        : label,
      currentState === "error"
        ? "error"
        : "system"
    );
  }

  function resetTimeline() {
    timelineState = {
      input: "complete",
      intent: "active",
      memory: "pending",
      rag: "pending",
      model: "pending",
      tool: "pending",
      response: "pending",
    };

    renderTimeline();
  }

  function completeThrough(stageId) {
    if (!timelineState) {
      resetTimeline();
    }

    let reached = false;

    for (const stage of timelineStages) {
      if (stage.id === stageId) {
        timelineState[stage.id] = "active";
        reached = true;
        continue;
      }

      if (!reached) {
        timelineState[stage.id] = "complete";
      }
    }

    renderTimeline();
  }

  function updateTimelineFromState(state) {
    if (state === "thinking") {
      completeThrough("model");
    }

    if (state === "tool") {
      completeThrough("tool");
    }

    if (state === "speaking") {
      completeThrough("response");
    }

    if (state === "idle" && timelineState) {
      for (const stage of timelineStages) {
        if (
          timelineState[stage.id] === "active"
        ) {
          timelineState[stage.id] = "complete";
        }
      }

      renderTimeline();
    }

    if (state === "error") {
      renderTimeline();
    }
  }

  function renderTimeline() {
    if (!timeline) {
      return;
    }

    timeline.innerHTML = "";

    for (const stage of timelineStages) {
      const state =
        timelineState?.[stage.id] ||
        "pending";

      const row =
        document.createElement("div");

      row.className =
        `timeline-row ${state}`;

      row.innerHTML = `
        <span class="timeline-node"></span>
        <span>${escapeHtml(stage.label)}</span>
        <span class="timeline-time">
          ${state === "complete"
            ? "DONE"
            : state === "active"
              ? "ACTIVE"
              : "—"}
        </span>
      `;

      timeline.appendChild(row);
    }

    while (timeline.children.length > MAX_TIMELINE) {
      timeline.lastElementChild.remove();
    }
  }

  function renderDevices(list) {
    if (!devices) {
      return;
    }

    devices.innerHTML = "";

    const normalized =
      Array.isArray(list)
        ? list
        : [];

    if (deviceCount) {
      deviceCount.textContent =
        String(normalized.length);
    }

    if (!normalized.length) {
      devices.innerHTML = `
        <div class="device-card">
          <div class="device-card-name">
            NO DEVICES
          </div>

          <div class="device-card-status">
            <span class="device-dot"></span>
            <span>OFFLINE</span>
          </div>
        </div>
      `;

      return;
    }

    for (const device of normalized) {
      const card =
        document.createElement("div");

      const online =
        true;

      const name =
        device.name ||
        device.device_type ||
        "UNKNOWN";

      const type =
        String(
          device.device_type ||
          "unknown"
        ).toUpperCase();

      card.className =
        "device-card";

      card.innerHTML = `
        <div class="device-card-name">
          ${escapeHtml(name)}
        </div>

        <div class="device-card-status">
          <span class="device-dot ${
            online ? "online" : ""
          }"></span>

          <span>
            ${escapeHtml(type)} · ${
              online
                ? "ONLINE"
                : "OFFLINE"
            }
          </span>
        </div>
      `;

      devices.appendChild(card);
    }
  }

  function updateDiagnostics() {
    if (!diag) {
      return;
    }

    const elapsed =
      Math.max(
        0,
        performance.now() - startTime
      );

    const seconds =
      Math.floor(elapsed / 1000);

    if (sessionTime) {
      sessionTime.textContent =
        formatDuration(seconds);
    }

    const memory =
      performance.memory;

    const values = {
      STATE:
        currentState.toUpperCase(),

      WS:
        document
          .getElementById("dot")
          ?.classList.contains("connected")
          ? "CONNECTED"
          : "DISCONNECTED",

      AUTH:
        wrap?.dataset.authenticated === "true"
          ? "TRUSTED"
          : "PENDING",

      MODE:
        wrap?.dataset.mode?.toUpperCase() ||
        "UNKNOWN",

      EVENTS:
        String(eventCounter),

      DEVICES:
        String(
          Array.isArray(
            window.JarvisDevices
          )
            ? window.JarvisDevices.length
            : 0
        ),
    };

    // Real machine stats pushed by ui/hud_server.py's periodic
    // system_status broadcast (see hud.js's WebSocket message switch).
    // Absent until the first broadcast arrives after connecting, so
    // these rows simply don't appear until then rather than showing
    // fake placeholder values.
    const sys = window.JarvisSystemStatus;

    if (sys) {
      values.CPU =
        `${Math.round(sys.cpu_percent)}% (${sys.cpu_count} cores)`;

      values.MEM =
        `${Math.round(sys.memory_percent)}%`;

      values.DISK =
        `${Math.round(sys.disk_percent)}%`;

      values.UPTIME =
        formatDuration(sys.uptime_seconds);
    }

    if (memory) {
      values.HEAP =
        `${formatMB(
          memory.usedJSHeapSize
        )} / ${formatMB(
          memory.jsHeapSizeLimit
        )}`;
    }

    diag.innerHTML = "";

    for (const [label, value] of
      Object.entries(values)) {

      const labelEl =
        document.createElement("span");

      labelEl.className =
        "diag-label";

      labelEl.textContent = label;

      const valueEl =
        document.createElement("span");

      valueEl.className =
        "diag-value";

      valueEl.textContent = value;

      diag.appendChild(labelEl);
      diag.appendChild(valueEl);
    }
  }

  function formatMB(bytes) {
    if (!Number.isFinite(bytes)) {
      return "N/A";
    }

    return `${(
      bytes /
      1024 /
      1024
    ).toFixed(1)} MB`;
  }

  function formatDuration(seconds) {
    const h =
      Math.floor(seconds / 3600);

    const m =
      Math.floor(
        (seconds % 3600) / 60
      );

    const s =
      seconds % 60;

    if (h > 0) {
      return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    }

    return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }

  function classifyChatLine(element) {
    if (!element) {
      return;
    }

    const text =
      element.textContent.trim();

    if (!text) {
      return;
    }

    if (
      element.classList.contains("tool")
    ) {
      addActivity(text, "tool");

      const lower =
        text.toLowerCase();

      if (
        lower.includes("rag") ||
        lower.includes("retriev") ||
        lower.includes("search")
      ) {
        completeThrough("rag");
      } else {
        completeThrough("tool");
      }

      return;
    }

    if (
      element.classList.contains("user")
    ) {
      resetTimeline();
      addActivity(
        `INPUT — ${text}`,
        "system"
      );

      return;
    }

    if (
      element.classList.contains("jarvis")
    ) {
      addActivity(
        "RESPONSE STREAM",
        "system"
      );

      completeThrough("response");
    }

    if (
      element.classList.contains("system")
    ) {
      addActivity(
        text,
        "system"
      );
    }
  }

  function observeChat() {
    if (!chatLog) {
      return;
    }

    const observer =
      new MutationObserver(
        mutations => {
          for (const mutation of mutations) {
            for (const node of mutation.addedNodes) {
              if (
                node.nodeType !== Node.ELEMENT_NODE
              ) {
                continue;
              }

              classifyChatLine(node);
            }
          }
        }
      );

    observer.observe(chatLog, {
      childList: true,
    });
  }

  function observeState() {
    if (!statusText) {
      return;
    }

    const observer =
      new MutationObserver(
        () => {
          const text =
            statusText.textContent.trim();

          if (!text) {
            return;
          }

          const normalized =
            text.toLowerCase();

          let state = "idle";

          if (
            normalized.includes("listen")
          ) {
            state = "listening";
          } else if (
            normalized.includes("think")
          ) {
            state = "thinking";
          } else if (
            normalized.includes("speak")
          ) {
            state = "speaking";
          } else if (
            normalized.includes("work") ||
            normalized.includes("tool")
          ) {
            state = "tool";
          } else if (
            normalized.includes("error") ||
            normalized.includes("denied")
          ) {
            state = "error";
          }

          const detail =
            text
              .replace(
                /^(IDLE|LISTENING|THINKING|SPEAKING|WORKING|ERROR)/i,
                ""
              )
              .replace(/^[-—:]\s*/, "")
              .trim();

          updateState(
            state,
            detail
          );
        }
      );

    observer.observe(statusText, {
      childList: true,
      characterData: true,
      subtree: true,
    });
  }

  function observeDevices() {
    window.addEventListener(
      "jarvis-devices-updated",
      event => {
        renderDevices(
          event.detail
        );

        addActivity(
          `DEVICE REGISTRY — ${
            Array.isArray(event.detail)
              ? event.detail.length
              : 0
          } CONNECTED`,
          "system"
        );
      }
    );

    renderDevices(
      window.JarvisDevices || []
    );
  }

  function installCollapse() {
    if (!collapseButton) {
      return;
    }

    collapseButton.addEventListener(
      "click",
      () => {
        inspector.classList.toggle(
          "collapsed"
        );

        collapseButton.textContent =
          inspector.classList.contains(
            "collapsed"
          )
            ? "+"
            : "−";
      }
    );
  }

  function installKeyboardShortcut() {
    document.addEventListener(
      "keydown",
      event => {
        if (
          event.ctrlKey &&
          event.shiftKey &&
          event.key.toLowerCase() === "i"
        ) {
          inspector.classList.toggle(
            "visible"
          );
        }
      }
    );
  }

  function boot() {
    resetTimeline();

    observeChat();
    observeState();
    observeDevices();

    installCollapse();
    installKeyboardShortcut();

    addActivity(
      "INSPECTOR ONLINE",
      "system"
    );

    updateDiagnostics();

    setInterval(
      updateDiagnostics,
      1000
    );

    /*
     * Do not keep the inspector permanently
     * visible during the initial HUD animation.
     */
    setTimeout(
      () => {
        inspector.classList.add(
          "visible"
        );
      },
      600
    );
  }

  boot();
})();