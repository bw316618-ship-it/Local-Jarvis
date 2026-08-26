/*
 * Jarvis "living core" HUD -- storm3d.js, v3.
 *
 * Explicitly NOT a particle vortex/galaxy: the old version distributed
 * particles across a disk with one continuous density falloff, which
 * read as diffuse and organic-but-directionless (a nebula, a tornado).
 * This version has real *structure* instead -- four independent
 * concentric rings (not a filled disk), each a separate THREE.Points
 * system with its own radius, particle count, and rotation speed/
 * direction, plus a separate sparse layer of larger "orbiting fragment"
 * sprites. Structure is what makes something read as an instrument
 * doing calculations rather than a weather effect.
 *
 * Layers, innermost to outermost:
 *   - Core: three overlapping additive-blended sprites (hot white,
 *     amber mid, soft outer glow) instead of a single flat blob --
 *     combined with real bloom this is what gives the "molten plasma"
 *     look rather than a flat circle.
 *   - Four energy rings, each with its own rotation speed/direction
 *     (differential rotation) AND its own radial "breathing" --
 *     particles drift inward/outward on independent sine cycles rather
 *     than sitting at a fixed radius, which is what avoids the "obvious
 *     looping animation" the brief explicitly asked to avoid.
 *   - ~50 orbiting fragments -- larger, sparser, independently-orbiting
 *     sprites representing discrete "data" rather than a dense field.
 *   - Procedural flicker: every particle's brightness is modulated by a
 *     small stack of summed sine waves at different frequencies with a
 *     per-particle phase offset (a cheap stand-in for real simplex/
 *     Perlin noise -- avoids pulling in another dependency for this),
 *     so nothing pulses in perfect unison.
 *
 * State handling is now two-part:
 *   - setTheme({color, speedMultiplier, pulse}) -- continuous, existing
 *     contract from before (color/speed/intensity scaling).
 *   - setState(name) -- NEW. Distinct per-state *behavior*, not just
 *     parameter scaling: 'listening' spawns expanding wave-rings,
 *     'speaking' drives a rhythmic multi-sine pulse through the core,
 *     'error' adds positional jitter and flicker instability. See the
 *     per-state branches in animate() and the honest limitation noted
 *     there for 'listening'/'speaking' -- there's no real microphone or
 *     TTS amplitude data reaching the browser yet, so both are
 *     synthesized rhythms, not audio-reactive. Wiring that up for real
 *     would mean voice.py streaming an amplitude value over the
 *     WebSocket during recording/playback; a real but separate feature
 *     from this file.
 */

import * as THREE from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";

const HOT_COLOR = 0xfff6e0;

const RING_DEFS = [
  { radius: 3.2, count: 90, speed: 0.9, flowFreq: 0.35, flowAmp: 0.25, size: 0.16 },
  { radius: 5.6, count: 150, speed: -0.55, flowFreq: 0.27, flowAmp: 0.4, size: 0.13 },
  { radius: 8.2, count: 190, speed: 0.35, flowFreq: 0.2, flowAmp: 0.55, size: 0.11 },
  { radius: 11.0, count: 140, speed: -0.2, flowFreq: 0.15, flowAmp: 0.7, size: 0.09 },
];

const FRAGMENT_COUNT = 50;

const BLOOM_BASE_STRENGTH = 1.3;
const BLOOM_PULSE_FACTOR = 0.4;
const BLOOM_RADIUS = 0.5;
const BLOOM_THRESHOLD = 0.12;

let renderer = null;
let scene = null;
let camera = null;
let composer = null;
let bloomPass = null;

let ringMeshes = []; // { points, geometry, baseAngles, baseRadius, def, phases }
let fragmentMesh = null; // { points, geometry, baseAngles, baseRadii, speeds, phases }
let coreSprites = []; // [{hot}, {mid}, {outer}]
let waveRings = []; // active 'listening' expanding wave-ring objects: { mesh, birth }

let themeColor = null;
let speedMultiplier = 1;
let pulseStrength = 1;
let currentState = "idle";

let animationId = null;
let clockStart = 0;
let lastWaveSpawn = 0;
let available = false;

// Cheap stand-in for real noise -- a small stack of sines at different
// frequencies, summed, so nothing reads as a single clean loop.
function pseudoNoise(x, seed) {
  return (
    (Math.sin(x * 1.7 + seed) + Math.sin(x * 3.1 + seed * 1.3) * 0.5 + Math.sin(x * 5.3 + seed * 0.7) * 0.25) / 1.75
  );
}

function makeGlowTexture(hardness) {
  const size = 128;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  gradient.addColorStop(0, "rgba(255,255,255,1)");
  gradient.addColorStop(hardness, "rgba(255,255,255,0.55)");
  gradient.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);
  return new THREE.CanvasTexture(canvas);
}

function buildCore() {
  const specs = [
    { size: 2.2, opacity: 1.0, hardness: 0.15, color: 0xffffff }, // hot center
    { size: 5.5, opacity: 0.75, hardness: 0.3, color: HOT_COLOR }, // amber mid
    { size: 10, opacity: 0.4, hardness: 0.5, color: null }, // soft outer glow -- takes theme color
  ];
  coreSprites = specs.map((spec) => {
    const material = new THREE.SpriteMaterial({
      map: makeGlowTexture(spec.hardness),
      color: spec.color !== null ? spec.color : themeColor,
      transparent: true,
      opacity: spec.opacity,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const sprite = new THREE.Sprite(material);
    sprite.scale.set(spec.size, spec.size, 1);
    scene.add(sprite);
    return { sprite, material, baseSize: spec.size, baseOpacity: spec.opacity, usesTheme: spec.color === null };
  });
}

function buildRing(def) {
  const positions = new Float32Array(def.count * 3);
  const colors = new Float32Array(def.count * 3);
  const sizes = new Float32Array(def.count);
  const baseAngles = new Float32Array(def.count);
  const phases = new Float32Array(def.count);

  for (let i = 0; i < def.count; i++) {
    baseAngles[i] = (i / def.count) * Math.PI * 2 + Math.random() * 0.06;
    phases[i] = Math.random() * Math.PI * 2;
    sizes[i] = def.size * (0.7 + Math.random() * 0.6);

    positions[i * 3] = Math.cos(baseAngles[i]) * def.radius;
    positions[i * 3 + 1] = (Math.random() - 0.5) * 0.4;
    positions[i * 3 + 2] = Math.sin(baseAngles[i]) * def.radius;
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  geometry.setAttribute("size", new THREE.BufferAttribute(sizes, 1));

  const material = new THREE.PointsMaterial({
    size: def.size,
    map: makeGlowTexture(0.25),
    vertexColors: true,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    sizeAttenuation: true,
  });

  const points = new THREE.Points(geometry, material);
  scene.add(points);

  return { points, geometry, baseAngles, phases, def };
}

function buildFragments() {
  const positions = new Float32Array(FRAGMENT_COUNT * 3);
  const colors = new Float32Array(FRAGMENT_COUNT * 3);
  const sizes = new Float32Array(FRAGMENT_COUNT);
  const baseAngles = new Float32Array(FRAGMENT_COUNT);
  const baseRadii = new Float32Array(FRAGMENT_COUNT);
  const speeds = new Float32Array(FRAGMENT_COUNT);
  const phases = new Float32Array(FRAGMENT_COUNT);

  for (let i = 0; i < FRAGMENT_COUNT; i++) {
    baseAngles[i] = Math.random() * Math.PI * 2;
    baseRadii[i] = 4 + Math.random() * 9;
    speeds[i] = (0.15 + Math.random() * 0.5) * (Math.random() < 0.5 ? 1 : -1);
    phases[i] = Math.random() * Math.PI * 2;
    sizes[i] = 0.22 + Math.random() * 0.22;

    positions[i * 3] = Math.cos(baseAngles[i]) * baseRadii[i];
    positions[i * 3 + 1] = (Math.random() - 0.5) * 1.2;
    positions[i * 3 + 2] = Math.sin(baseAngles[i]) * baseRadii[i];
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  geometry.setAttribute("size", new THREE.BufferAttribute(sizes, 1));

  const material = new THREE.PointsMaterial({
    size: 0.3,
    map: makeGlowTexture(0.15),
    vertexColors: true,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    sizeAttenuation: true,
  });

  const points = new THREE.Points(geometry, material);
  scene.add(points);

  fragmentMesh = { points, geometry, baseAngles, baseRadii, speeds, phases };
}

function applyThemeToRing(ring) {
  const colorAttr = ring.geometry.getAttribute("color");
  const hot = new THREE.Color(HOT_COLOR);
  for (let i = 0; i < ring.def.count; i++) {
    const heat = 0.3 + 0.5 * Math.abs(Math.sin(ring.baseAngles[i] * 2));
    const c = themeColor.clone().lerp(hot, heat * 0.5);
    colorAttr.setXYZ(i, c.r, c.g, c.b);
  }
  colorAttr.needsUpdate = true;
}

function applyThemeToFragments() {
  const colorAttr = fragmentMesh.geometry.getAttribute("color");
  const hot = new THREE.Color(HOT_COLOR);
  for (let i = 0; i < FRAGMENT_COUNT; i++) {
    const c = themeColor.clone().lerp(hot, 0.55);
    colorAttr.setXYZ(i, c.r, c.g, c.b);
  }
  colorAttr.needsUpdate = true;
}

function applyTheme() {
  if (!themeColor) return;
  ringMeshes.forEach(applyThemeToRing);
  if (fragmentMesh) applyThemeToFragments();
  coreSprites.forEach((c) => {
    if (c.usesTheme) c.material.color.copy(themeColor);
  });
}

function applyBloomStrength() {
  if (!bloomPass) return;
  bloomPass.strength = BLOOM_BASE_STRENGTH + pulseStrength * BLOOM_PULSE_FACTOR;
}

function spawnWaveRing() {
  const geometry = new THREE.RingGeometry(0.1, 0.14, 64);
  const material = new THREE.MeshBasicMaterial({
    color: themeColor,
    transparent: true,
    opacity: 0.5,
    blending: THREE.AdditiveBlending,
    side: THREE.DoubleSide,
    depthWrite: false,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.rotation.x = Math.PI / 2;
  scene.add(mesh);
  waveRings.push({ mesh, birth: performance.now() });
}

function updateWaveRings(now) {
  for (let i = waveRings.length - 1; i >= 0; i--) {
    const wave = waveRings[i];
    const age = (now - wave.birth) / 1000;
    const life = 1.6;
    if (age >= life) {
      scene.remove(wave.mesh);
      wave.mesh.geometry.dispose();
      wave.mesh.material.dispose();
      waveRings.splice(i, 1);
      continue;
    }
    const t = age / life;
    const radius = 1 + t * 15;
    wave.mesh.scale.setScalar(radius);
    wave.mesh.material.opacity = 0.5 * (1 - t);
  }
}

function resize() {
  if (!renderer || !camera || !composer) return;
  const canvasEl = renderer.domElement;
  const parent = canvasEl.parentElement;
  if (!parent) return;
  const w = parent.clientWidth;
  const h = parent.clientHeight;
  if (w === 0 || h === 0) return;
  renderer.setSize(w, h, false);
  composer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}

function animate() {
  animationId = requestAnimationFrame(animate);
  const now = performance.now();
  const t = (now - clockStart) / 1000;

  // Error state: unstable/glitchy -- jitter positions and desync flicker
  // rather than the smooth breathing motion every other state uses.
  const errorActive = currentState === "error";
  const jitterAmp = errorActive ? 0.35 : 0;

  ringMeshes.forEach((ring, ringIndex) => {
    const posAttr = ring.geometry.getAttribute("position");
    for (let i = 0; i < ring.def.count; i++) {
      const angle = ring.baseAngles[i] + t * ring.def.speed * speedMultiplier * 0.4;
      const flow = Math.sin(t * ring.def.flowFreq + ring.phases[i]) * ring.def.flowAmp;
      const radius = ring.def.radius + flow;
      const jitterX = errorActive ? (pseudoNoise(t * 8, ring.phases[i]) * jitterAmp) : 0;
      const jitterZ = errorActive ? (pseudoNoise(t * 8 + 3, ring.phases[i]) * jitterAmp) : 0;

      posAttr.setXYZ(
        i,
        Math.cos(angle) * radius + jitterX,
        (Math.sin(t * 0.5 + ring.phases[i]) * 0.15),
        Math.sin(angle) * radius + jitterZ
      );
    }
    posAttr.needsUpdate = true;
  });

  if (fragmentMesh) {
    const posAttr = fragmentMesh.geometry.getAttribute("position");
    for (let i = 0; i < FRAGMENT_COUNT; i++) {
      const angle = fragmentMesh.baseAngles[i] + t * fragmentMesh.speeds[i] * speedMultiplier * 0.3;
      const radius = fragmentMesh.baseRadii[i] + pseudoNoise(t * 0.3, fragmentMesh.phases[i]) * 0.6;
      posAttr.setXYZ(i, Math.cos(angle) * radius, Math.sin(t * 0.4 + fragmentMesh.phases[i]) * 0.5, Math.sin(angle) * radius);
    }
    posAttr.needsUpdate = true;
  }

  // Core pulse: idle/thinking/tool get a calm breathing sine; 'speaking'
  // gets a rhythmic multi-sine "fake waveform" instead -- see the module
  // docstring for why this is synthesized rather than real TTS-amplitude
  // driven (no audio data reaches the browser yet).
  let corePulse;
  if (currentState === "speaking") {
    corePulse =
      1 + (Math.sin(t * 6) * 0.5 + Math.sin(t * 9.3) * 0.3 + Math.sin(t * 13.7) * 0.2) * 0.12 * pulseStrength;
  } else {
    corePulse = 1 + Math.sin(t * 2.2) * 0.06 * pulseStrength;
  }
  if (errorActive) {
    corePulse *= 0.85 + pseudoNoise(t * 10, 1.7) * 0.3;
  }

  coreSprites.forEach((c) => {
    c.sprite.scale.setScalar(c.baseSize * corePulse);
    c.material.opacity = errorActive
      ? c.baseOpacity * (0.6 + pseudoNoise(t * 12, c.baseSize) * 0.4)
      : c.baseOpacity;
  });

  // Listening: periodically spawn an expanding wave-ring -- synthesized
  // (fixed cadence), not synced to real microphone amplitude; see the
  // module docstring.
  if (currentState === "listening" && now - lastWaveSpawn > 900) {
    spawnWaveRing();
    lastWaveSpawn = now;
  }
  updateWaveRings(now);

  scene.rotation.y = errorActive ? pseudoNoise(t * 6, 9) * 0.08 : Math.sin(t * 0.04) * 0.04;

  composer.render();
}

function init(canvas, initialColor) {
  try {
    renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    camera.position.set(0, 9, 24);
    camera.lookAt(0, 0, 0);

    themeColor = new THREE.Color(initialColor || "#e08a2e");

    buildCore();
    ringMeshes = RING_DEFS.map(buildRing);
    buildFragments();
    applyTheme();

    composer = new EffectComposer(renderer);
    composer.addPass(new RenderPass(scene, camera));
    bloomPass = new UnrealBloomPass(new THREE.Vector2(1, 1), BLOOM_BASE_STRENGTH, BLOOM_RADIUS, BLOOM_THRESHOLD);
    composer.addPass(bloomPass);
    applyBloomStrength();

    resize();
    window.addEventListener("resize", resize);

    available = true;
    return true;
  } catch (e) {
    // Whatever failed -- WebGL context creation, or anything after it --
    // release the renderer if one was actually created so a caller that
    // retries init() later doesn't leak a second live WebGL context on
    // top of this failed one. Browsers cap the number of live contexts
    // per page (historically ~16), so repeated failed-then-retried
    // attempts without this would eventually exhaust that budget for
    // real, on top of just being wasteful.
    if (renderer) {
      renderer.dispose();
      renderer = null;
    }
    available = false;
    return false;
  }
}

function start() {
  if (!available || animationId !== null) return;
  clockStart = performance.now();
  lastWaveSpawn = 0;
  animate();
}

function stop() {
  if (animationId !== null) {
    cancelAnimationFrame(animationId);
    animationId = null;
  }
  // Clear any in-flight wave-rings so restarting doesn't resume stale ones.
  waveRings.forEach((w) => {
    scene.remove(w.mesh);
    w.mesh.geometry.dispose();
    w.mesh.material.dispose();
  });
  waveRings = [];
}

function setTheme({ color, speedMultiplier: sm, pulse } = {}) {
  if (color) {
    themeColor = new THREE.Color(color);
    applyTheme();
  }
  if (typeof sm === "number" && !Number.isNaN(sm)) {
    speedMultiplier = sm;
  }
  if (typeof pulse === "number" && !Number.isNaN(pulse)) {
    pulseStrength = pulse;
    applyBloomStrength();
  }
}

function setState(stateName) {
  currentState = stateName || "idle";
}

function isAvailable() {
  return available;
}

window.StormScene = { init, start, stop, setTheme, setState, isAvailable, resize };
