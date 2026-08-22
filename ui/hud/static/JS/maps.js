(() => {
  "use strict";

  let initialized = false;

  const LOCAL_COMMANDS = {
    close: [
      "close map",
      "exit map",
      "hide map",
    ],

    world: [
      "world map",
      "show world",
      "show the world",
      "world",
    ],

    locate: [
      "center on me",
      "center on my location",
      "show my location",
      "locate me",
      "find me",
    ],

    zoomIn: [
      "zoom in",
      "zoom closer",
      "zoom in once",
    ],

    zoomOut: [
      "zoom out",
      "zoom farther",
      "zoom out once",
    ],

    location: [
      "where am i",
      "my location",
      "my coordinates",
      "coordinates",
      "where are we",
    ],
  };

  function normalize(text) {
    return String(text || "")
      .toLowerCase()
      .replace(/[?!.,]/g, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function addChatLine(text, cls) {
    const chatLog =
      document.getElementById("chatLog");

    if (!chatLog) {
      return;
    }

    const element =
      document.createElement("div");

    element.className =
      `chat-line ${cls}`;

    element.textContent = text;

    chatLog.appendChild(element);

    chatLog.scrollTop =
      chatLog.scrollHeight;
  }

  function getMap() {
    return window.JarvisMap || null;
  }

  function isMapOpen() {
    const map = getMap();

    if (!map) {
      return false;
    }

    const context =
      map.getContext?.();

    return !!context?.open;
  }

  function includesCommand(
    normalized,
    commands
  ) {
    return commands.includes(
      normalized
    );
  }

  function runLocalCommand(text) {
    const normalized =
      normalize(text);

    const map = getMap();

    if (!map) {
      return false;
    }

    if (
      includesCommand(
        normalized,
        LOCAL_COMMANDS.close
      )
    ) {
      addChatLine(
        text,
        "user"
      );

      map.close?.();

      addChatLine(
        "Map closed.",
        "jarvis"
      );

      return true;
    }

    if (
      includesCommand(
        normalized,
        LOCAL_COMMANDS.world
      )
    ) {
      addChatLine(
        text,
        "user"
      );

      map.open?.();
      map.expand?.();

      map.showWorld?.();

      addChatLine(
        "World view.",
        "jarvis"
      );

      return true;
    }

    if (
      includesCommand(
        normalized,
        LOCAL_COMMANDS.locate
      )
    ) {
      addChatLine(
        text,
        "user"
      );

      map.open?.();
      map.expand?.();
      map.centerOnUser?.();

      addChatLine(
        "Centering on your location.",
        "jarvis"
      );

      return true;
    }

    if (
      includesCommand(
        normalized,
        LOCAL_COMMANDS.zoomIn
      )
    ) {
      addChatLine(
        text,
        "user"
      );

      map.zoom?.(1);

      return true;
    }

    if (
      includesCommand(
        normalized,
        LOCAL_COMMANDS.zoomOut
      )
    ) {
      addChatLine(
        text,
        "user"
      );

      map.zoom?.(-1);

      return true;
    }

    const zoomMatch =
      normalized.match(
        /^zoom (in|out) (\d+)$/
      );

    if (zoomMatch) {
      addChatLine(
        text,
        "user"
      );

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

      for (
        let i = 0;
        i < amount;
        i++
      ) {
        map.zoom?.(direction);
      }

      return true;
    }

    if (
      includesCommand(
        normalized,
        LOCAL_COMMANDS.location
      )
    ) {
      addChatLine(
        text,
        "user"
      );

      const context =
        map.getContext?.();

      if (
        context?.latitude == null ||
        context?.longitude == null
      ) {
        addChatLine(
          "Your location is not available yet.",
          "jarvis"
        );
      } else {
        const accuracy =
          Number.isFinite(
            Number(
              context.accuracy_m
            )
          )
            ? Math.round(
                context.accuracy_m
              )
            : null;

        addChatLine(
          accuracy == null
            ? `Current position: ${context.latitude.toFixed(6)}, ${context.longitude.toFixed(6)}.`
            : `Current position: ${context.latitude.toFixed(6)}, ${context.longitude.toFixed(6)}. Accuracy: ${accuracy}m.`,
          "jarvis"
        );
      }

      return true;
    }

    return false;
  }

  function interceptOnlyLocalCommands(event) {
  
    if (!isMapOpen()) {
      return;
    }

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

  
    const handled =
      runLocalCommand(text);

    if (!handled) {
      return;
    }

    event.preventDefault();
    event.stopImmediatePropagation();

    input.value = "";
  }

  function exposeCompatibilityAPI() {


    window.JarvisMaps = {
      isOpen: isMapOpen,

      open() {
        getMap()?.open?.();
      },

      close() {
        getMap()?.close?.();
      },

      expand() {
        getMap()?.expand?.();
      },

      collapse() {
        getMap()?.collapse?.();
      },

      centerOnUser() {
        getMap()?.centerOnUser?.();
      },

      showWorld() {
        getMap()?.showWorld?.();
      },

      zoom(direction) {
        getMap()?.zoom?.(
          direction
        );
      },

      getContext() {
        return (
          getMap()?.getContext?.() ||
          null
        );
      },
    };
  }

  function init() {
    if (initialized) {
      return;
    }

    initialized = true;

    exposeCompatibilityAPI();

    const chatForm =
      document.getElementById(
        "chatForm"
      );

    if (chatForm) {
      chatForm.addEventListener(
        "submit",
        interceptOnlyLocalCommands,
        true
      );
    }

    console.log(
      "[Jarvis Maps] Compatibility bridge initialized."
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
