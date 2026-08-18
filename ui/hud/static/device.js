/*
 * Jarvis Step 14 — persistent trusted-device credentials.
 *
 * The server issues the token only after pairing approval.
 * The token is stored locally and sent over the authenticated WebSocket.
 */

(() => {
  "use strict";

  const ID_KEY = "jarvis-device-id";
  const TYPE_KEY = "jarvis-device-type";
  const NAME_KEY = "jarvis-device-name";
  const TOKEN_KEY = "jarvis-device-token";

  function makeId(type) {
    const random = crypto.randomUUID
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;

    return `jarvis-${type}-${random}`;
  }

  function detectType() {
    const forced = localStorage.getItem(TYPE_KEY);

    if (forced === "phone" || forced === "pc") {
      return forced;
    }

    const narrow = window.matchMedia(
      "(max-width: 700px)"
    ).matches;

    const touch = navigator.maxTouchPoints > 0;

    return narrow && touch ? "phone" : "pc";
  }

  function getIdentity() {
    const type = detectType();

    let id = localStorage.getItem(ID_KEY);

    if (!id || !id.startsWith(`jarvis-${type}-`)) {
      id = makeId(type);
      localStorage.setItem(ID_KEY, id);
    }

    const defaultName =
      type === "phone" ? "Phone" : "PC";

    const name =
      localStorage.getItem(NAME_KEY) ||
      defaultName;

    return {
      id,
      type,
      name,
      token: localStorage.getItem(TOKEN_KEY),
    };
  }

  function saveToken(token) {
    if (token) {
      localStorage.setItem(
        TOKEN_KEY,
        token
      );
    }
  }

  function clearToken() {
    localStorage.removeItem(TOKEN_KEY);
  }

  function apply(identity) {
    const wrap = document.getElementById("wrap");

    if (wrap) {
      wrap.dataset.device = identity.type;
      wrap.dataset.authenticated =
        identity.token ? "true" : "false";
    }

    document.documentElement.dataset.jarvisDevice =
      identity.type;

    window.JarvisDevice = Object.freeze({
      id: identity.id,
      type: identity.type,
      name: identity.name,
      token: identity.token,
    });

    window.JarvisDeviceAuth = Object.freeze({
      getToken() {
        return localStorage.getItem(TOKEN_KEY);
      },

      saveToken,

      setToken(token) {
        saveToken(token);
      },

      clearToken,

      refresh() {
        apply(getIdentity());
      },
    });

    window.dispatchEvent(
      new CustomEvent(
        "jarvis-device-ready",
        {
          detail: window.JarvisDevice,
        }
      )
    );
  }

  apply(getIdentity());
})();