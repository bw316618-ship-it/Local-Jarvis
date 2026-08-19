(() => {
  "use strict";

  const PORT = 8770;
  const HOST_KEY = "jarvis-backend-host";

  function getHost() {
    return (
      localStorage.getItem(HOST_KEY) ||
      window.location.hostname ||
      "localhost"
    );
  }

  function getUrl() {
    const host = getHost();
    const protocol =
      window.location.protocol === "https:" ? "wss:" : "ws:";

    return `${protocol}//${host}:${PORT}`;
  }

  function createSocket() {
    return new WebSocket(getUrl());
  }

  window.JarvisBackend = Object.freeze({
    port: PORT,
    getHost,
    getUrl,
    createSocket,
    setHost(host) {
      if (!host || typeof host !== "string") {
        throw new TypeError("Backend host must be a non-empty string.");
      }

      localStorage.setItem(
        HOST_KEY,
        host.trim()
      );
    },
    clearHost() {
      localStorage.removeItem(HOST_KEY);
    },
  });

  console.log(
    "[Jarvis Step 15] Backend endpoint:",
    window.JarvisBackend.getUrl()
  );
})();
