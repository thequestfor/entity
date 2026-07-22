import "./styles.css";
import * as THREE from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";

type Mode =
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "acting"
  | "waiting_confirmation"
  | "autonomous_goal"
  | "service_issue"
  | "offline";

type Palette = {
  primary: THREE.Color;
  secondary: THREE.Color;
  accent: THREE.Color;
  room: THREE.Color;
  label: string;
  pulse: number;
};

const palettes: Record<Mode, Palette> = {
  idle: makePalette("#eaffff", "#16b8c4", "#a9fff3", "#c8d8da", "IDLE", 0.16),
  listening: makePalette("#eef8ff", "#297dff", "#72d9ff", "#cbd7df", "LISTENING", 0.34),
  thinking: makePalette("#fbf4ff", "#9d42e8", "#d3a1ff", "#d2cedd", "THINKING", 0.46),
  speaking: makePalette("#e4ffed", "#0ca854", "#72e99d", "#c6d8ce", "SPEAKING", 0.76),
  acting: makePalette("#fff7ed", "#ff7b25", "#ffc16d", "#ddd2c8", "ACTING", 0.4),
  waiting_confirmation: makePalette("#fff8ec", "#ff9e2c", "#ffe0a1", "#ded5c9", "WAITING", 0.22),
  autonomous_goal: makePalette("#fffce8", "#e9b51f", "#fff088", "#ddd9c7", "AUTONOMOUS", 0.28),
  service_issue: makePalette("#fff0ec", "#f04438", "#ff9177", "#ddcecb", "SERVICE ISSUE", 0.42),
  offline: makePalette("#d9dde0", "#7c878c", "#f0f3f4", "#a8adb0", "OFFLINE", 0.05)
};

const modeMessages: Record<Mode, string> = {
  idle: "Present · listening for you",
  listening: "Receiving your voice",
  thinking: "Gathering context and forming a response",
  speaking: "Speaking with you",
  acting: "Working with a connected service",
  waiting_confirmation: "Waiting for your confirmation",
  autonomous_goal: "Pursuing an autonomous goal",
  service_issue: "A service needs attention",
  offline: "Entity is offline"
};

const lifecycleModes: Record<string, Mode> = {
  created: "offline",
  booting: "thinking",
  wake_detected: "listening",
  listening: "listening",
  transcribing: "thinking",
  thinking: "thinking",
  tool_started: "acting",
  tool_finished: "acting",
  speaking: "speaking",
  autonomous: "autonomous_goal",
  waiting_confirmation: "waiting_confirmation",
  recovering: "service_issue",
  service_error: "service_issue",
  error: "service_issue",
  idle: "idle",
  stopping: "offline",
  stopped: "offline"
};

const lifecycleEnergy: Record<string, number> = {
  created: 20, booting: 50, wake_detected: 68, listening: 72,
  transcribing: 65, thinking: 76, tool_started: 82, tool_finished: 58,
  speaking: 88, autonomous: 70, waiting_confirmation: 54,
  recovering: 72, service_error: 78, error: 88, idle: 42,
  stopping: 14, stopped: 0
};

const canvas = document.querySelector<HTMLCanvasElement>("#scene");
const modeLabel = document.querySelector<HTMLElement>("#mode-label");
const energyLabel = document.querySelector<HTMLElement>("#energy-label");
const modeSwatch = document.querySelector<HTMLElement>("#mode-swatch");
const energyInput = document.querySelector<HTMLInputElement>("#energy");
const runtimeLink = document.querySelector<HTMLElement>("#runtime-link");
const runtimeLabel = document.querySelector<HTMLElement>("#runtime-label");
const messageLabel = document.querySelector<HTMLElement>("#message-label");
const buttons = [...document.querySelectorAll<HTMLButtonElement>("[data-mode]")];

if (!canvas || !modeLabel || !energyLabel || !modeSwatch || !energyInput ||
    !runtimeLink || !runtimeLabel || !messageLabel) {
  throw new Error("Visual interface DOM is incomplete.");
}

const modeLabelEl = modeLabel;
const energyLabelEl = energyLabel;
const modeSwatchEl = modeSwatch;
const energyInputEl = energyInput;
const runtimeLinkEl = runtimeLink;
const runtimeLabelEl = runtimeLabel;
const messageLabelEl = messageLabel;
const previewParams = new URLSearchParams(window.location.search);

const state = {
  mode: "idle" as Mode,
  energy: 0.62,
  targetEnergy: 0.62,
  palette: palettes.idle,
  displayPrimary: palettes.idle.primary.clone(),
  displaySecondary: palettes.idle.secondary.clone(),
  displayAccent: palettes.idle.accent.clone(),
  displayRoom: palettes.idle.room.clone()
};

const renderer = new THREE.WebGLRenderer({
  canvas,
  antialias: true,
  alpha: false,
  powerPreference: "high-performance"
});
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.62;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;

const scene = new THREE.Scene();
scene.background = new THREE.Color("#829397");
scene.fog = new THREE.FogExp2("#93a4a7", 0.0042);

const environment = new RoomEnvironment();
const pmremGenerator = new THREE.PMREMGenerator(renderer);
scene.environment = pmremGenerator.fromScene(environment, 0.04).texture;

const camera = new THREE.PerspectiveCamera(43, window.innerWidth / window.innerHeight, 0.1, 120);
camera.position.set(0.58, 1.55, 8.45);
camera.lookAt(0, 1.05, -0.25);

const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloomPass = new UnrealBloomPass(new THREE.Vector2(window.innerWidth, window.innerHeight), 0.42, 0.64, 0.58);
composer.addPass(bloomPass);
composer.addPass(new OutputPass());

const room = new THREE.Group();
const entity = new THREE.Group();
const particles = new THREE.Group();
const bubbles = new THREE.Group();
scene.add(room, entity, particles, bubbles);

const clock = new THREE.Clock();
const tmpVector = new THREE.Vector3();
const livingGreen = new THREE.Color("#91ffd0");
const softRoomWhite = new THREE.Color("#d9e9e7");
const floorTexture = createPanelTexture("#dde8e8", "#ffffff", 1024, 1024, 12, 0.18);
const wallTexture = createPanelTexture("#c9dde3", "#eaffff", 1024, 1024, 8, 0.11);
const consoleTexture = createPanelTexture("#e8f0f0", "#ffffff", 1024, 512, 8, 0.16);

const orbMaterial = new THREE.MeshPhysicalMaterial({
  color: "#dffbff",
  emissive: "#63f6ff",
  emissiveIntensity: 0.06,
  roughness: 0.2,
  metalness: 0.04,
  transmission: 0.1,
  thickness: 1.5,
  ior: 1.42,
  transparent: false,
  opacity: 1,
  clearcoat: 0.82,
  clearcoatRoughness: 0.1,
  attenuationColor: "#9eefff",
  attenuationDistance: 0.7,
  envMapIntensity: 1.05
});

const stemMaterial = new THREE.MeshPhysicalMaterial({
  color: "#c8f8ff",
  roughness: 0.16,
  metalness: 0,
  transmission: 0.45,
  thickness: 1.4,
  ior: 1.37,
  transparent: true,
  opacity: 0.38,
  clearcoat: 0.9,
  clearcoatRoughness: 0.1,
  envMapIntensity: 1.5
});

const panelMaterial = new THREE.MeshPhysicalMaterial({
  color: "#bdeeff",
  roughness: 0.22,
  metalness: 0,
  transmission: 0.28,
  transparent: true,
  opacity: 0.22,
  side: THREE.DoubleSide,
  clearcoat: 0.7,
  clearcoatRoughness: 0.18
});

const roomMaterial = new THREE.MeshStandardMaterial({
  color: "#c5d0d2",
  roughness: 0.34,
  metalness: 0.18,
  map: floorTexture,
  emissive: "#141a1c",
  emissiveIntensity: 0.03
});

const darkGlassMaterial = new THREE.MeshPhysicalMaterial({
  color: "#aebabe",
  roughness: 0.18,
  metalness: 0.14,
  transmission: 0.16,
  transparent: true,
  opacity: 0.66,
  clearcoat: 0.85,
  clearcoatRoughness: 0.14,
  map: wallTexture,
  envMapIntensity: 1.35
});

const chromeMaterial = new THREE.MeshStandardMaterial({
  color: "#d9e1e3",
  roughness: 0.18,
  metalness: 0.72,
  envMapIntensity: 2.1
});

const glossyWhiteMaterial = new THREE.MeshPhysicalMaterial({
  color: "#eef5f6",
  roughness: 0.16,
  metalness: 0.08,
  transmission: 0.06,
  transparent: true,
  opacity: 0.86,
  clearcoat: 1,
  clearcoatRoughness: 0.08,
  envMapIntensity: 2.4
});

const aquaGlassMaterial = new THREE.MeshPhysicalMaterial({
  color: "#7fe8ff",
  roughness: 0.04,
  metalness: 0,
  transmission: 0.58,
  thickness: 1.2,
  ior: 1.34,
  transparent: true,
  opacity: 0.34,
  clearcoat: 1,
  clearcoatRoughness: 0.04,
  attenuationColor: "#56dfff",
  attenuationDistance: 3.4,
  envMapIntensity: 2.8
});

const limeAccentMaterial = new THREE.MeshPhysicalMaterial({
  color: "#d8ff61",
  roughness: 0.18,
  metalness: 0.05,
  clearcoat: 1,
  clearcoatRoughness: 0.12,
  emissive: "#9dff2e",
  emissiveIntensity: 0.12
});

const haloMaterial = new THREE.MeshBasicMaterial({
  color: "#b8fbff",
  transparent: true,
  opacity: 0.18,
  depthWrite: false,
  blending: THREE.AdditiveBlending
});

const orb = new THREE.Mesh(new THREE.SphereGeometry(1.45, 96, 64), orbMaterial);
orb.position.set(0, 1.7, 0);
orb.castShadow = true;
orb.receiveShadow = true;
entity.add(orb);

const core = new THREE.Mesh(
  new THREE.IcosahedronGeometry(0.45, 5),
  new THREE.MeshBasicMaterial({
    color: "#eaffff",
    transparent: true,
    opacity: 0.72,
    blending: THREE.AdditiveBlending,
    depthWrite: false
  })
);
core.position.copy(orb.position);
entity.add(core);

const innerShell = new THREE.Mesh(
  new THREE.SphereGeometry(0.94, 64, 32),
  new THREE.MeshBasicMaterial({
    color: "#68f2ff",
    transparent: true,
    opacity: 0.11,
    wireframe: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false
  })
);
innerShell.position.copy(orb.position);
entity.add(innerShell);

const stem = new THREE.Mesh(new THREE.CapsuleGeometry(0.42, 1.08, 18, 44), stemMaterial);
stem.position.set(0, 0.54, 0);
stem.scale.set(1.0, 0.96, 0.72);
stem.castShadow = true;
stem.receiveShadow = true;
entity.add(stem);

const base = new THREE.Mesh(new THREE.CylinderGeometry(1.46, 1.9, 0.18, 96), stemMaterial);
base.position.set(0, -0.1, 0);
base.scale.set(1.0, 1.0, 0.45);
base.castShadow = true;
base.receiveShadow = true;
entity.add(base);

const bodyHalo = new THREE.Mesh(new THREE.SphereGeometry(1.8, 64, 32), haloMaterial);
bodyHalo.position.copy(orb.position);
bodyHalo.scale.set(1, 0.96, 1);
bodyHalo.renderOrder = 8;
entity.add(bodyHalo);

const colorShell = new THREE.Mesh(
  new THREE.SphereGeometry(1.462, 96, 64),
  new THREE.ShaderMaterial({
    uniforms: {
      tintColor: { value: new THREE.Color("#63f6ff") },
      baseAlpha: { value: 0.62 },
      visibility: { value: 1 }
    },
    vertexShader: `
      varying vec3 vViewNormal;
      varying vec3 vViewPosition;
      varying float vLocalY;

      void main() {
        vec4 viewPosition = modelViewMatrix * vec4(position, 1.0);
        vViewPosition = viewPosition.xyz;
        vViewNormal = normalize(normalMatrix * normal);
        vLocalY = position.y / 1.462;
        gl_Position = projectionMatrix * viewPosition;
      }
    `,
    fragmentShader: `
      uniform vec3 tintColor;
      uniform float baseAlpha;
      uniform float visibility;
      varying vec3 vViewNormal;
      varying vec3 vViewPosition;
      varying float vLocalY;

      void main() {
        vec3 viewDirection = normalize(-vViewPosition);
        float fresnel = pow(1.0 - max(dot(vViewNormal, viewDirection), 0.0), 2.2);
        float alpha = (baseAlpha + fresnel * 0.26) * visibility;
        float verticalShade = mix(0.64, 0.98, clamp(vLocalY * 0.5 + 0.5, 0.0, 1.0));
        gl_FragColor = vec4(tintColor * verticalShade, alpha);
      }
    `,
    transparent: true,
    blending: THREE.NormalBlending,
    depthTest: true,
    depthWrite: false,
    toneMapped: false
  })
);
colorShell.position.copy(orb.position);
colorShell.renderOrder = 12;
entity.add(colorShell);

const lowerColorWell = new THREE.Mesh(
  new THREE.SphereGeometry(0.72, 48, 24),
  new THREE.MeshBasicMaterial({
    color: "#63f6ff",
    transparent: true,
    opacity: 0.28,
    blending: THREE.AdditiveBlending,
    depthTest: false,
    depthWrite: false
  })
);
lowerColorWell.position.set(0, 1.0, 0.05);
lowerColorWell.scale.set(1.1, 0.46, 0.72);
lowerColorWell.renderOrder = 13;
entity.add(lowerColorWell);

const outerModeAura = new THREE.Mesh(
  new THREE.SphereGeometry(1.62, 64, 32),
  new THREE.MeshBasicMaterial({
    color: "#63f6ff",
    transparent: true,
    opacity: 0.12,
    blending: THREE.AdditiveBlending,
    depthTest: false,
    depthWrite: false,
    side: THREE.BackSide
  })
);
outerModeAura.position.copy(orb.position);
outerModeAura.scale.set(1, 0.98, 1);
outerModeAura.renderOrder = 7;
entity.add(outerModeAura);

const causticRings = createCausticRings();
const energyThreads = createEnergyThreads();
const visceralNetwork = createVisceralNetwork();
const modeRings = createModeRings();
const particleField = createParticleField();
entity.add(causticRings, energyThreads, visceralNetwork, modeRings);
particles.add(particleField);
createBubbleField();

const lights = createLighting();
createControlRoom();

const requestedMode = previewParams.get("mode") as Mode | null;
const initialMode = hasPalette(requestedMode)
  ? requestedMode
  : "idle";
const requestedEnergyParam = previewParams.get("energy");
const requestedEnergy = Number(requestedEnergyParam);
if (requestedEnergyParam !== null && Number.isFinite(requestedEnergy)) {
  const previewEnergy = THREE.MathUtils.clamp(requestedEnergy, 0, 100) / 100;
  state.energy = previewEnergy;
  state.targetEnergy = previewEnergy;
  energyInputEl.value = String(Math.round(previewEnergy * 100));
}
setMode(initialMode);
animate();

function makePalette(primary: string, secondary: string, accent: string, roomColor: string, label: string, pulse: number): Palette {
  return {
    primary: new THREE.Color(primary),
    secondary: new THREE.Color(secondary),
    accent: new THREE.Color(accent),
    room: new THREE.Color(roomColor),
    label,
    pulse
  };
}

function hasPalette(mode: string | null): mode is Mode {
  return mode !== null && Object.prototype.hasOwnProperty.call(palettes, mode);
}

function createPanelTexture(base: string, line: string, width: number, height: number, divisions: number, lineAlpha: number) {
  const textureCanvas = document.createElement("canvas");
  textureCanvas.width = width;
  textureCanvas.height = height;
  const textureCtx = textureCanvas.getContext("2d");

  if (!textureCtx) {
    throw new Error("Could not create procedural texture canvas.");
  }

  const gradient = textureCtx.createLinearGradient(0, 0, width, height);
  gradient.addColorStop(0, base);
  gradient.addColorStop(0.48, "#376c78");
  gradient.addColorStop(1, "#102b34");
  textureCtx.fillStyle = gradient;
  textureCtx.fillRect(0, 0, width, height);

  textureCtx.globalAlpha = lineAlpha;
  textureCtx.strokeStyle = line;
  textureCtx.lineWidth = 1;
  const cellW = width / divisions;
  const cellH = height / Math.max(4, Math.floor(divisions * 0.6));

  for (let x = 0; x <= width; x += cellW) {
    textureCtx.beginPath();
    textureCtx.moveTo(x, 0);
    textureCtx.lineTo(x + width * 0.05, height);
    textureCtx.stroke();
  }

  for (let y = 0; y <= height; y += cellH) {
    textureCtx.beginPath();
    textureCtx.moveTo(0, y);
    textureCtx.lineTo(width, y + height * 0.025);
    textureCtx.stroke();
  }

  textureCtx.globalAlpha = lineAlpha * 0.75;
  for (let i = 0; i < 38; i += 1) {
    const x = Math.random() * width;
    const y = Math.random() * height;
    const length = 26 + Math.random() * 120;
    textureCtx.beginPath();
    textureCtx.moveTo(x, y);
    textureCtx.lineTo(x + length, y + Math.random() * 8 - 4);
    textureCtx.stroke();
  }

  const texture = new THREE.CanvasTexture(textureCanvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(2, 2);
  texture.anisotropy = 8;
  return texture;
}

function createLighting() {
  const ambient = new THREE.HemisphereLight("#e7f0f0", "#526267", 0.48);
  scene.add(ambient);

  const key = new THREE.SpotLight("#eef7f7", 5.2, 18, Math.PI * 0.24, 0.62, 1.08);
  key.position.set(-3.0, 5.4, 4.6);
  key.target.position.set(0, 1.1, -0.4);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  key.shadow.camera.near = 0.5;
  key.shadow.camera.far = 24;
  scene.add(key);
  scene.add(key.target);

  const rim = new THREE.SpotLight("#dffbff", 3.8, 13, Math.PI * 0.24, 0.65, 1.28);
  rim.position.set(4.2, 3.6, -2.4);
  rim.target.position.set(0, 1.6, 0);
  rim.castShadow = true;
  scene.add(rim);
  scene.add(rim.target);

  const coreLight = new THREE.PointLight("#aefcff", 2.2, 6.4, 1.5);
  coreLight.position.copy(core.position);
  coreLight.castShadow = true;
  scene.add(coreLight);

  const roomPulse = new THREE.PointLight("#8ff8ff", 0.7, 12, 1.6);
  roomPulse.position.set(0, 1.25, 2.2);
  scene.add(roomPulse);

  const modeGlow = new THREE.PointLight("#63f6ff", 0, 3.2, 2.4);
  modeGlow.position.copy(orb.position);
  entity.add(modeGlow);

  const spillLight = new THREE.PointLight("#63f6ff", 0, 7.5, 1.8);
  spillLight.position.set(0, 1.45, 1.65);
  scene.add(spillLight);

  const consoleLight = new THREE.RectAreaLight("#e9f3f3", 1.8, 5.8, 0.55);
  consoleLight.position.set(0, 0.48, 2.15);
  consoleLight.rotation.x = -Math.PI * 0.48;
  scene.add(consoleLight);

  return { ambient, key, rim, coreLight, roomPulse, modeGlow, spillLight };
}

function createControlRoom() {
  const floor = new THREE.Mesh(new THREE.BoxGeometry(13.5, 0.26, 14.8), roomMaterial);
  floor.position.set(0, -0.38, -1.7);
  floor.receiveShadow = true;
  floor.castShadow = true;
  room.add(floor);

  const foregroundFloor = new THREE.Mesh(new THREE.BoxGeometry(16, 0.18, 5.8), glossyWhiteMaterial.clone());
  foregroundFloor.position.set(0, -0.5, 5.15);
  foregroundFloor.receiveShadow = true;
  foregroundFloor.castShadow = true;
  room.add(foregroundFloor);

  const floorInset = new THREE.Mesh(
    new THREE.BoxGeometry(8.6, 0.024, 2.2),
    new THREE.MeshPhysicalMaterial({
      color: "#bdf7ff",
      roughness: 0.08,
      metalness: 0,
      transmission: 0.28,
      transparent: true,
      opacity: 0.42,
      clearcoat: 1,
      clearcoatRoughness: 0.04,
      emissive: "#55e8ff",
      emissiveIntensity: 0.08
    })
  );
  floorInset.position.set(0, -0.38, 4.65);
  floorInset.receiveShadow = true;
  room.add(floorInset);

  const backWall = new THREE.Mesh(new THREE.BoxGeometry(10.2, 5.8, 0.38), darkGlassMaterial);
  backWall.position.set(0, 2.28, -4.68);
  backWall.receiveShadow = true;
  backWall.castShadow = true;
  room.add(backWall);

  const leftWall = makeWall(-1);
  const rightWall = makeWall(1);
  room.add(leftWall, rightWall);

  const ceiling = new THREE.Mesh(new THREE.BoxGeometry(12.6, 0.28, 10.8), darkGlassMaterial);
  ceiling.position.set(0, 5.08, -1.55);
  ceiling.receiveShadow = true;
  ceiling.castShadow = true;
  room.add(ceiling);

  createArchitecture();
  createFloorGrid();
  createMonitorBanks();
  createConsoleDeck();
  createLightRails();
  createFloatingPanels();
  createEquipmentRacks();
  createSkeuomorphicGoodies();
  createReferenceRoomFeatures();
}

function makeWall(side: -1 | 1) {
  const wall = new THREE.Mesh(new THREE.BoxGeometry(0.34, 5.8, 8.8), darkGlassMaterial);
  wall.position.set(side * 5.12, 2.08, -1.1);
  wall.rotation.y = side * -Math.PI * 0.34;
  wall.receiveShadow = true;
  wall.castShadow = true;
  return wall;
}

function createArchitecture() {
  const beamMaterial = new THREE.MeshStandardMaterial({
    color: "#14333d",
    roughness: 0.34,
    metalness: 0.28,
    map: wallTexture,
    emissive: "#061217",
    emissiveIntensity: 0.08
  });

  const beamPositions = [
    [-4.18, 2.2, -4.05, 0.18, 4.8, 0.28],
    [4.18, 2.2, -4.05, 0.18, 4.8, 0.28],
    [0, 4.48, -4.0, 8.5, 0.18, 0.26],
    [0, 0.15, -4.0, 8.5, 0.22, 0.34],
    [-5.0, 0.16, 1.6, 0.42, 0.26, 5.2],
    [5.0, 0.16, 1.6, 0.42, 0.26, 5.2]
  ];

  beamPositions.forEach(([x, y, z, sx, sy, sz]) => {
    const beam = new THREE.Mesh(new THREE.BoxGeometry(sx, sy, sz), beamMaterial);
    beam.position.set(x, y, z);
    beam.castShadow = true;
    beam.receiveShadow = true;
    room.add(beam);
  });

  const apertureMaterial = new THREE.MeshPhysicalMaterial({
    color: "#82d6e5",
    roughness: 0.18,
    metalness: 0.05,
    transmission: 0.18,
    transparent: true,
    opacity: 0.52,
    clearcoat: 1,
    clearcoatRoughness: 0.08,
    map: wallTexture
  });

  const aperture = new THREE.Mesh(new THREE.TorusGeometry(2.52, 0.065, 18, 160), apertureMaterial);
  aperture.position.set(0, 1.72, -3.82);
  aperture.scale.set(1.18, 1.18, 0.18);
  aperture.castShadow = true;
  aperture.receiveShadow = true;
  room.add(aperture);
}

function createFloorGrid() {
  const gridMaterial = new THREE.LineBasicMaterial({
    color: "#d9fbff",
    transparent: true,
    opacity: 0.16,
    blending: THREE.AdditiveBlending
  });
  const lines = new THREE.Group();

  for (let i = -8; i <= 8; i += 1) {
    const geometry = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(i * 0.42, -0.205, 3.3),
      new THREE.Vector3(i * 1.1, -0.205, -6.4)
    ]);
    lines.add(new THREE.Line(geometry, gridMaterial));
  }

  for (let i = 0; i < 14; i += 1) {
    const z = 3.3 - i * 0.72;
    const geometry = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(-5.6, -0.2, z),
      new THREE.Vector3(5.6, -0.2, z)
    ]);
    lines.add(new THREE.Line(geometry, gridMaterial));
  }

  room.add(lines);
}

function createMonitorBanks() {
  const monitorMaterial = new THREE.MeshPhysicalMaterial({
    color: "#72cddd",
    roughness: 0.18,
    transmission: 0.08,
    transparent: true,
    opacity: 0.68,
    side: THREE.DoubleSide,
    clearcoat: 0.8,
    map: consoleTexture,
    emissive: "#1f8ca0",
    emissiveIntensity: 0.22
  });

  for (const side of [-1, 1] as const) {
    for (let row = 0; row < 4; row += 1) {
      const panel = new THREE.Mesh(new THREE.BoxGeometry(1.22, 0.5, 0.035), monitorMaterial.clone());
      panel.position.set(side * 3.55, 3.25 - row * 0.64, -2.35 + row * 0.05);
      panel.rotation.y = side * -0.84;
      panel.rotation.z = side * 0.03;
      panel.castShadow = true;
      panel.receiveShadow = true;
      room.add(panel);

      const bars = new THREE.Group();
      for (let i = 0; i < 7; i += 1) {
        const bar = new THREE.Mesh(
          new THREE.BoxGeometry(0.66 - i * 0.052, 0.012, 0.012),
          new THREE.MeshBasicMaterial({
            color: i % 2 === 0 ? "#ffffff" : "#78f7ff",
            transparent: true,
            opacity: 0.48,
            blending: THREE.AdditiveBlending
          })
        );
        bar.position.set(-0.2 + i * 0.035, 0.16 - i * 0.047, 0.04);
        bars.add(bar);
      }
      panel.add(bars);
    }
  }
}

function createConsoleDeck() {
  const deckMaterial = new THREE.MeshPhysicalMaterial({
    color: "#dce8e8",
    roughness: 0.2,
    metalness: 0.12,
    transmission: 0.08,
    transparent: true,
    opacity: 0.72,
    clearcoat: 0.9,
    clearcoatRoughness: 0.16,
    map: consoleTexture
  });
  const deck = new THREE.Mesh(new THREE.BoxGeometry(8.4, 0.24, 1.35), deckMaterial);
  deck.position.set(0, 0.02, 2.02);
  deck.rotation.x = -0.08;
  deck.castShadow = true;
  deck.receiveShadow = true;
  room.add(deck);

  const rearLip = new THREE.Mesh(new THREE.BoxGeometry(7.7, 0.1, 0.16), glossyWhiteMaterial.clone());
  rearLip.position.set(0, 0.28, 1.35);
  rearLip.castShadow = true;
  rearLip.receiveShadow = true;
  room.add(rearLip);

  for (let i = 0; i < 17; i += 1) {
    const pad = new THREE.Mesh(
      new THREE.CylinderGeometry(0.08 + (i % 3) * 0.025, 0.1, 0.014, 28),
      new THREE.MeshBasicMaterial({
        color: i % 3 === 0 ? "#ffffff" : "#84f7ff",
        transparent: true,
        opacity: 0.34,
        blending: THREE.AdditiveBlending
      })
    );
    pad.position.set(-3.9 + i * 0.48, 0.26, 2.0 + Math.sin(i) * 0.18);
    pad.scale.z = 0.38;
    room.add(pad);
  }
}

function createEquipmentRacks() {
  const rackMaterial = new THREE.MeshStandardMaterial({
    color: "#183b46",
    roughness: 0.45,
    metalness: 0.22,
    map: wallTexture,
    emissive: "#06161b",
    emissiveIntensity: 0.05
  });

  for (const side of [-1, 1] as const) {
    for (let i = 0; i < 3; i += 1) {
      const rack = new THREE.Mesh(new THREE.BoxGeometry(0.58, 1.15, 0.48), rackMaterial);
      rack.position.set(side * (4.05 + i * 0.28), 0.62 + i * 0.12, -1.0 - i * 0.78);
      rack.rotation.y = side * -0.42;
      rack.castShadow = true;
      rack.receiveShadow = true;
      room.add(rack);

      for (let j = 0; j < 5; j += 1) {
        const diode = new THREE.Mesh(
          new THREE.BoxGeometry(0.1, 0.018, 0.012),
          new THREE.MeshBasicMaterial({
            color: j % 2 === 0 ? "#9ffbff" : "#ffffff",
            transparent: true,
            opacity: 0.48,
            blending: THREE.AdditiveBlending
          })
        );
        diode.position.set(side * (4.05 + i * 0.28), 0.92 + i * 0.12 - j * 0.12, -0.75 - i * 0.78);
        diode.rotation.y = side * -0.42;
        room.add(diode);
      }
    }
  }
}

function createSkeuomorphicGoodies() {
  const gemColors = ["#ff7d61", "#84ffbd", "#7defff", "#ffe38a", "#c6a7ff"];

  for (const side of [-1, 1] as const) {
    const rail = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 3.8, 32), chromeMaterial);
    rail.position.set(side * 2.72, 2.25, -3.32);
    rail.rotation.x = Math.PI / 2;
    rail.castShadow = true;
    rail.receiveShadow = true;
    room.add(rail);

    for (let i = 0; i < 6; i += 1) {
      const gem = new THREE.Mesh(
        new THREE.SphereGeometry(0.07 + (i % 2) * 0.018, 32, 16),
        new THREE.MeshPhysicalMaterial({
          color: gemColors[(i + (side === 1 ? 2 : 0)) % gemColors.length],
          roughness: 0.05,
          metalness: 0,
          transmission: 0.28,
          transparent: true,
          opacity: 0.88,
          clearcoat: 1,
          clearcoatRoughness: 0.03,
          emissive: gemColors[(i + (side === 1 ? 2 : 0)) % gemColors.length],
          emissiveIntensity: 0.18
        })
      );
      gem.position.set(side * (2.28 + i * 0.13), 0.34, 2.2 + Math.sin(i) * 0.18);
      gem.castShadow = true;
      room.add(gem);
    }

    for (let i = 0; i < 4; i += 1) {
      const knob = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.16, 0.07, 40), chromeMaterial);
      knob.position.set(side * (1.45 + i * 0.34), 0.31, 2.62);
      knob.rotation.x = Math.PI / 2;
      knob.castShadow = true;
      knob.receiveShadow = true;
      room.add(knob);

      const cap = new THREE.Mesh(new THREE.SphereGeometry(0.09, 32, 16), glossyWhiteMaterial);
      cap.position.set(side * (1.45 + i * 0.34), 0.36, 2.58);
      cap.scale.set(1, 0.42, 1);
      cap.castShadow = true;
      room.add(cap);
    }
  }

  for (let i = 0; i < 5; i += 1) {
    const shelf = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.04, 0.32), glossyWhiteMaterial);
    shelf.position.set(-1.8 + i * 0.9, 3.78 + Math.sin(i) * 0.04, -3.82);
    shelf.castShadow = true;
    shelf.receiveShadow = true;
    room.add(shelf);
  }
}

function createReferenceRoomFeatures() {
  createBubbleWallpaper();
  createAquariumColumns();
  createRoundedShelves();
  createPortholeWindows();
  createCeilingFixtures();
  createLimeMobiles();
}

function createBubbleWallpaper() {
  const bubbleRimMaterial = new THREE.MeshPhysicalMaterial({
    color: "#eaffff",
    roughness: 0.04,
    transmission: 0.55,
    thickness: 0.18,
    transparent: true,
    opacity: 0.48,
    clearcoat: 1,
    clearcoatRoughness: 0.03,
    attenuationColor: "#72ddff",
    attenuationDistance: 1.6,
    envMapIntensity: 2.5
  });

  const positions = [
    [-3.75, 3.0, -4.42, 0.24],
    [-3.2, 2.25, -4.38, 0.14],
    [-2.45, 3.46, -4.36, 0.18],
    [-1.78, 2.72, -4.34, 0.11],
    [2.95, 3.24, -4.38, 0.23],
    [3.55, 2.38, -4.4, 0.14],
    [2.2, 2.72, -4.36, 0.12],
    [1.62, 3.58, -4.34, 0.18],
    [-4.82, 2.75, -1.55, 0.2],
    [-4.74, 1.82, 0.08, 0.13],
    [4.82, 2.78, -1.58, 0.2],
    [4.74, 1.82, 0.08, 0.13]
  ];

  positions.forEach(([x, y, z, size], index) => {
    const sphere = new THREE.Mesh(new THREE.SphereGeometry(size, 48, 24), bubbleRimMaterial.clone());
    sphere.position.set(x, y, z);
    sphere.scale.z = 0.22;
    sphere.userData.baseOpacity = 0.38 + (index % 3) * 0.035;
    sphere.castShadow = true;
    sphere.receiveShadow = true;
    room.add(sphere);

    const glint = new THREE.Mesh(
      new THREE.SphereGeometry(size * 0.18, 16, 8),
      new THREE.MeshBasicMaterial({
        color: "#ffffff",
        transparent: true,
        opacity: 0.5,
        blending: THREE.AdditiveBlending
      })
    );
    glint.position.set(x - size * 0.28, y + size * 0.2, z + 0.04);
    glint.scale.set(1, 0.45, 0.12);
    room.add(glint);
  });
}

function createAquariumColumns() {
  const tankPositions = [
    [-3.55, 1.72, -3.65, 0.58, 2.75],
    [3.55, 1.72, -3.65, 0.58, 2.75],
    [-4.35, 1.08, 0.4, 0.42, 1.75],
    [4.35, 1.08, 0.4, 0.42, 1.75]
  ];

  tankPositions.forEach(([x, y, z, radius, height], index) => {
    const tank = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, height, 64, 1, true), aquaGlassMaterial.clone());
    tank.position.set(x, y, z);
    tank.castShadow = true;
    tank.receiveShadow = true;
    room.add(tank);

    const waterGlow = new THREE.PointLight(index % 2 === 0 ? "#37e6ff" : "#a0ffeb", 1.1, 2.5, 1.8);
    waterGlow.position.set(x, y + height * 0.12, z);
    room.add(waterGlow);

    for (let i = 0; i < 8; i += 1) {
      const plant = new THREE.Mesh(
        new THREE.ConeGeometry(0.045 + (i % 3) * 0.018, 0.34 + (i % 4) * 0.08, 8),
        new THREE.MeshStandardMaterial({
          color: i % 2 === 0 ? "#4ed07d" : "#97ff64",
          roughness: 0.45,
          metalness: 0
        })
      );
      const angle = (i / 8) * Math.PI * 2;
      plant.position.set(x + Math.cos(angle) * radius * 0.36, y - height * 0.43 + plant.geometry.parameters.height * 0.5, z + Math.sin(angle) * radius * 0.36);
      plant.rotation.z = Math.sin(i) * 0.18;
      room.add(plant);
    }
  });
}

function createRoundedShelves() {
  const shelves = [
    [-2.55, 2.85, -4.08, 1.35],
    [-2.48, 2.35, -4.05, 1.1],
    [2.55, 2.85, -4.08, 1.35],
    [2.48, 2.35, -4.05, 1.1],
    [0, 3.76, -4.18, 1.9]
  ];

  shelves.forEach(([x, y, z, width], index) => {
    const shelf = new THREE.Mesh(new THREE.BoxGeometry(width, 0.1, 0.34), glossyWhiteMaterial.clone());
    shelf.position.set(x, y, z);
    shelf.castShadow = true;
    shelf.receiveShadow = true;
    room.add(shelf);

    const leftCap = new THREE.Mesh(new THREE.SphereGeometry(0.17, 24, 12), glossyWhiteMaterial.clone());
    leftCap.position.set(x - width * 0.5, y, z);
    leftCap.scale.set(1, 0.3, 1);
    room.add(leftCap);

    const rightCap = leftCap.clone();
    rightCap.position.x = x + width * 0.5;
    room.add(rightCap);

    for (let i = 0; i < 5; i += 1) {
      const bottle = new THREE.Mesh(
        new THREE.CapsuleGeometry(0.035, 0.16, 8, 16),
        new THREE.MeshPhysicalMaterial({
          color: ["#67f5ff", "#d9ff61", "#79ffb5", "#ffac72", "#ffffff"][(i + index) % 5],
          roughness: 0.08,
          transmission: 0.28,
          transparent: true,
          opacity: 0.82,
          clearcoat: 1,
          emissive: ["#00cfff", "#aaff00", "#00ff8a", "#ff7a2f", "#ffffff"][(i + index) % 5],
          emissiveIntensity: 0.08
        })
      );
      bottle.position.set(x - width * 0.36 + i * width * 0.18, y + 0.16, z + 0.02);
      room.add(bottle);
    }
  });
}

function createPortholeWindows() {
  const ringMaterial = new THREE.MeshPhysicalMaterial({
    color: "#eef4f5",
    roughness: 0.14,
    metalness: 0.18,
    clearcoat: 1,
    clearcoatRoughness: 0.06,
    envMapIntensity: 2.4
  });

  for (let i = -1; i <= 1; i += 1) {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.42, 0.045, 18, 64), ringMaterial);
    ring.position.set(i * 1.22, 3.32, -4.3);
    ring.scale.set(1, 1.18, 0.18);
    ring.castShadow = true;
    room.add(ring);

    const pane = new THREE.Mesh(new THREE.CircleGeometry(0.39, 64), aquaGlassMaterial.clone());
    pane.position.set(i * 1.22, 3.32, -4.31);
    pane.scale.y = 1.18;
    room.add(pane);
  }
}

function createCeilingFixtures() {
  for (let i = -2; i <= 2; i += 1) {
    const fixture = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.34, 0.06, 64), glossyWhiteMaterial.clone());
    fixture.position.set(i * 1.35, 4.82, -0.9 - Math.abs(i) * 0.22);
    fixture.rotation.x = Math.PI / 2;
    room.add(fixture);

    const bulb = new THREE.PointLight(i % 2 === 0 ? "#ffffff" : "#c8fbff", 0.75, 3.5, 1.8);
    bulb.position.set(i * 1.35, 4.55, -0.9 - Math.abs(i) * 0.22);
    room.add(bulb);
  }

  for (let i = 0; i < 3; i += 1) {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.54 + i * 0.18, 0.018, 12, 96), limeAccentMaterial.clone());
    ring.position.set(0, 4.72 - i * 0.02, -2.35);
    ring.rotation.x = Math.PI / 2;
    room.add(ring);
  }
}

function createLimeMobiles() {
  for (let i = 0; i < 7; i += 1) {
    const mobile = new THREE.Group();
    const stemMesh = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, 0.62, 12), limeAccentMaterial);
    stemMesh.rotation.z = Math.PI * 0.5;
    mobile.add(stemMesh);

    const podA = new THREE.Mesh(new THREE.SphereGeometry(0.09, 24, 12), limeAccentMaterial);
    podA.scale.set(1.8, 0.5, 0.5);
    podA.position.x = -0.33;
    mobile.add(podA);

    const podB = podA.clone();
    podB.position.x = 0.33;
    mobile.add(podB);

    mobile.position.set(-2.0 + i * 0.64, 4.28 - (i % 2) * 0.2, -1.5 - (i % 3) * 0.35);
    mobile.rotation.y = i * 0.6;
    mobile.rotation.z = Math.sin(i) * 0.38;
    mobile.userData.spin = 0.18 + i * 0.025;
    room.add(mobile);
  }
}

function createBubbleField() {
  const bubbleMaterial = new THREE.MeshPhysicalMaterial({
    color: "#f9ffff",
    roughness: 0.02,
    metalness: 0,
    transmission: 0.72,
    thickness: 0.35,
    ior: 1.34,
    transparent: true,
    opacity: 0.34,
    clearcoat: 1,
    clearcoatRoughness: 0.02,
    envMapIntensity: 2.8
  });

  for (let i = 0; i < 44; i += 1) {
    const bubble = new THREE.Mesh(new THREE.SphereGeometry(0.035 + Math.random() * 0.075, 24, 16), bubbleMaterial.clone());
    const side = i % 3 === 0 ? -1 : i % 3 === 1 ? 1 : 0;
    bubble.position.set(
      side * (1.8 + Math.random() * 2.7) + (Math.random() - 0.5) * 0.8,
      Math.random() * 4.6,
      -3.2 + Math.random() * 5.8
    );
    bubble.userData.baseX = bubble.position.x;
    bubble.userData.speed = 0.08 + Math.random() * 0.18;
    bubble.userData.phase = Math.random() * Math.PI * 2;
    bubble.userData.range = 4.6 + Math.random() * 1.2;
    bubble.castShadow = true;
    bubbles.add(bubble);
  }
}

function createLightRails() {
  const railMaterial = new THREE.MeshBasicMaterial({
    color: "#dffcff",
    transparent: true,
    opacity: 0.34,
    blending: THREE.AdditiveBlending
  });

  const positions = [
    [0, 4.45, -2.7, 5.2, 0.024, 0.024],
    [0, 3.88, -4.05, 6.8, 0.018, 0.018],
    [0, 0.28, 2.08, 6.8, 0.014, 0.014]
  ];

  positions.forEach(([x, y, z, sx, sy, sz]) => {
    const rail = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), railMaterial);
    rail.position.set(x, y, z);
    rail.scale.set(sx, sy, sz);
    room.add(rail);
  });
}

function createFloatingPanels() {
  for (let i = 0; i < 7; i += 1) {
    const panel = new THREE.Mesh(new THREE.PlaneGeometry(0.56 + (i % 2) * 0.24, 0.9), panelMaterial.clone());
    const side = i % 2 === 0 ? -1 : 1;
    panel.position.set(side * (1.55 + i * 0.16), 1.5 + (i % 3) * 0.46, -1.7 - i * 0.3);
    panel.rotation.y = side * -0.38;
    panel.rotation.z = side * 0.06;
    room.add(panel);
  }
}

function createCausticRings() {
  const group = new THREE.Group();
  const material = new THREE.MeshBasicMaterial({
    color: "#dffcff",
    transparent: true,
    opacity: 0.18,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    side: THREE.DoubleSide
  });

  for (let i = 0; i < 9; i += 1) {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.38 + i * 0.09, 0.004, 8, 96), material.clone());
    ring.position.set(0, 1.25 + i * 0.085, 0);
    ring.rotation.x = Math.PI / 2;
    group.add(ring);
  }

  return group;
}

function createModeRings() {
  const group = new THREE.Group();
  const material = new THREE.MeshBasicMaterial({
    color: "#ffffff",
    transparent: true,
    opacity: 0.42,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    side: THREE.DoubleSide
  });

  const configs = [
    [1.6, 0.018, 1.7, 0],
    [1.86, 0.012, 1.7, Math.PI / 2],
    [1.08, 0.014, 0.52, Math.PI / 2],
    [1.36, 0.01, 2.22, Math.PI / 2]
  ];

  configs.forEach(([radius, tube, y, rotateZ], index) => {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(radius, tube, 16, 160), material.clone());
    ring.position.set(0, y, 0);
    ring.rotation.x = Math.PI / 2;
    ring.rotation.z = rotateZ;
    ring.userData.offset = index * 0.7;
    group.add(ring);
  });

  return group;
}

function createEnergyThreads() {
  const group = new THREE.Group();
  const material = new THREE.LineBasicMaterial({
    color: "#dffcff",
    transparent: true,
    opacity: 0.28,
    blending: THREE.AdditiveBlending
  });

  for (let i = 0; i < 18; i += 1) {
    const points = [];
    const phase = i * 0.7;
    for (let j = 0; j < 32; j += 1) {
      const t = j / 31;
      const angle = phase + t * Math.PI * 1.3;
      points.push(
        new THREE.Vector3(
          Math.cos(angle) * (0.16 + t * 0.72),
          0.86 + t * 1.32,
          Math.sin(angle) * (0.16 + t * 0.72)
        )
      );
    }
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), material.clone());
    group.add(line);
  }

  return group;
}

function createVisceralNetwork() {
  const group = new THREE.Group();
  const strandMaterial = new THREE.MeshBasicMaterial({
    color: "#86ffd0",
    transparent: true,
    opacity: 0.16,
    blending: THREE.AdditiveBlending,
    depthWrite: false
  });

  for (let i = 0; i < 12; i += 1) {
    const angle = (i / 12) * Math.PI * 2;
    const elevation = -0.72 + (i % 5) * 0.34;
    const points = [
      new THREE.Vector3(Math.cos(angle) * 0.16, 1.7 + elevation * 0.12, Math.sin(angle) * 0.16),
      new THREE.Vector3(Math.cos(angle + 0.7) * 0.43, 1.7 + elevation * 0.48, Math.sin(angle + 0.7) * 0.43),
      new THREE.Vector3(Math.cos(angle - 0.36) * 0.72, 1.7 + elevation * 0.78, Math.sin(angle - 0.36) * 0.72),
      new THREE.Vector3(Math.cos(angle) * 1.02, 1.7 + elevation, Math.sin(angle) * 1.02)
    ];
    const curve = new THREE.CatmullRomCurve3(points);
    const strand = new THREE.Mesh(
      new THREE.TubeGeometry(curve, 36, 0.008 + (i % 3) * 0.004, 6, false),
      strandMaterial.clone()
    );
    strand.userData.phase = i * 0.57;
    group.add(strand);

    const node = new THREE.Mesh(
      new THREE.SphereGeometry(0.025 + (i % 3) * 0.008, 12, 8),
      strandMaterial.clone()
    );
    node.position.copy(points[2]);
    node.userData.phase = i * 0.57 + 0.8;
    node.userData.node = true;
    group.add(node);
  }

  const heart = new THREE.Mesh(
    new THREE.DodecahedronGeometry(0.31, 2),
    new THREE.MeshBasicMaterial({
      color: "#c8ffe2",
      transparent: true,
      opacity: 0.3,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    })
  );
  heart.position.copy(orb.position);
  heart.scale.set(0.92, 1.12, 0.88);
  heart.userData.heart = true;
  group.add(heart);
  return group;
}

function createParticleField() {
  const geometry = new THREE.BufferGeometry();
  const positions = new Float32Array(360 * 3);
  for (let i = 0; i < 360; i += 1) {
    positions[i * 3] = (Math.random() - 0.5) * 9.4;
    positions[i * 3 + 1] = Math.random() * 4.8;
    positions[i * 3 + 2] = (Math.random() - 0.5) * 7.2;
  }
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));

  const material = new THREE.PointsMaterial({
    color: "#eaffff",
    size: 0.035,
    transparent: true,
    opacity: 0.28,
    blending: THREE.AdditiveBlending,
    depthWrite: false
  });

  return new THREE.Points(geometry, material);
}

function setMode(mode: Mode, message = modeMessages[mode]) {
  if (!hasPalette(mode)) return;
  state.mode = mode;
  state.palette = palettes[mode];
  modeLabelEl.textContent = state.palette.label;
  modeSwatchEl.style.color = `#${state.palette.secondary.getHexString()}`;
  messageLabelEl.textContent = message;
  buttons.forEach((button) => button.classList.toggle("active", button.dataset.mode === mode));
}

function applyLifecycleEvent(event: { state?: string; details?: Record<string, unknown> }) {
  const lifecycleState = event.state ?? "idle";
  const mode = lifecycleModes[lifecycleState] ?? "idle";
  const detailMessage = typeof event.details?.message === "string" ? event.details.message : undefined;
  const tool = typeof event.details?.tool === "string" ? event.details.tool : undefined;
  const message = detailMessage ?? (tool ? `${modeMessages[mode]} · ${tool}` : modeMessages[mode]);
  setMode(mode, message);
  const energy = lifecycleEnergy[lifecycleState] ?? 50;
  state.targetEnergy = energy / 100;
  energyInputEl.value = String(energy);
}

function connectRuntime() {
  if (!("EventSource" in window)) {
    runtimeLabelEl.textContent = "MANUAL PREVIEW";
    return;
  }

  const source = new EventSource("/events");
  source.onopen = () => {
    runtimeLinkEl.dataset.connected = "true";
    runtimeLabelEl.textContent = "ENTITY CONNECTED";
  };
  source.onmessage = (message) => {
    try {
      applyLifecycleEvent(JSON.parse(message.data));
    } catch {
      messageLabelEl.textContent = "Received an unreadable lifecycle event";
    }
  };
  source.onerror = () => {
    runtimeLinkEl.dataset.connected = "false";
    runtimeLabelEl.textContent = "RECONNECTING";
  };
}

(window as unknown as { EntityVisual: object }).EntityVisual = { setMode, applyLifecycleEvent };

function animate() {
  const delta = clock.getDelta();
  const elapsed = clock.elapsedTime;
  state.energy = THREE.MathUtils.lerp(state.energy, state.targetEnergy, 1 - Math.exp(-delta * 3.2));

  const palette = state.palette;
  state.displayPrimary.lerp(palette.primary, 1 - Math.exp(-delta * 2.8));
  state.displaySecondary.lerp(palette.secondary, 1 - Math.exp(-delta * 2.8));
  state.displayAccent.lerp(palette.accent, 1 - Math.exp(-delta * 2.8));
  state.displayRoom.lerp(palette.room, 1 - Math.exp(-delta * 1.8));

  const voice = state.mode === "speaking"
    ? (0.32 + Math.abs(Math.sin(elapsed * 9.4)) * 0.46 + Math.abs(Math.sin(elapsed * 15.2)) * 0.22) * state.energy
    : 0;
  const activity = Math.max(voice, palette.pulse * 0.55 + state.energy * 0.18);
  const offline = state.mode === "offline" ? 0.22 : 1;

  (scene.background as THREE.Color).copy(state.displayRoom).multiplyScalar(0.58);
  (scene.fog as THREE.FogExp2).color.copy(state.displayRoom).multiplyScalar(0.66);
  (scene.fog as THREE.FogExp2).density = 0.0038 + (1 - offline) * 0.01;

  orbMaterial.color.copy(state.displaySecondary).multiplyScalar(0.72);
  orbMaterial.emissive.copy(state.displaySecondary);
  orbMaterial.emissiveIntensity = (0.035 + activity * 0.1) * offline;
  orbMaterial.attenuationColor.copy(state.displaySecondary);
  orbMaterial.roughness = 0.2 - Math.min(activity * 0.045, 0.06);

  stemMaterial.color.copy(state.displaySecondary).lerp(state.displayPrimary, 0.28);
  stemMaterial.opacity = 0.34 + activity * 0.18;

  const coreMaterial = core.material as THREE.MeshBasicMaterial;
  coreMaterial.color.copy(state.displayAccent);
  coreMaterial.opacity = (0.2 + activity * 0.22) * offline;

  const shellMaterial = innerShell.material as THREE.MeshBasicMaterial;
  shellMaterial.color.copy(state.displaySecondary);
  shellMaterial.opacity = (0.055 + activity * 0.14) * offline;

  const halo = bodyHalo.material as THREE.MeshBasicMaterial;
  halo.color.copy(state.displaySecondary);
  halo.opacity = (0.07 + activity * 0.13) * offline;

  const colorShellMaterial = colorShell.material as THREE.ShaderMaterial;
  (colorShellMaterial.uniforms.tintColor.value as THREE.Color).copy(state.displaySecondary);
  colorShellMaterial.uniforms.baseAlpha.value = 0.54 + activity * 0.12;
  colorShellMaterial.uniforms.visibility.value = offline;

  const lowerColorMaterial = lowerColorWell.material as THREE.MeshBasicMaterial;
  lowerColorMaterial.color.copy(state.displayAccent).lerp(state.displaySecondary, 0.5);
  lowerColorMaterial.opacity = (0.1 + activity * 0.18) * offline;

  const outerAuraMaterial = outerModeAura.material as THREE.MeshBasicMaterial;
  outerAuraMaterial.color.copy(state.displaySecondary);
  outerAuraMaterial.opacity = (0.05 + activity * 0.11) * offline;

  orb.scale.setScalar((1 + Math.sin(elapsed * 1.08) * 0.012 + activity * 0.025) * offline);
  orb.scale.x += Math.sin(elapsed * 3.2) * voice * 0.018;
  orb.scale.y += Math.cos(elapsed * 2.8) * voice * 0.03;
  core.scale.setScalar(0.82 + activity * 0.52 + Math.sin(elapsed * 6.4) * voice * 0.12);
  colorShell.scale.setScalar(1.002 + activity * 0.012 + Math.sin(elapsed * 2.4) * voice * 0.006);
  colorShell.rotation.y += delta * (0.2 + activity * 0.75);
  lowerColorWell.scale.set(1.1 + activity * 0.12, 0.46 + activity * 0.08, 0.72 + activity * 0.08);
  outerModeAura.scale.setScalar(1.0 + activity * 0.1 + Math.sin(elapsed * 1.8) * voice * 0.04);
  innerShell.rotation.y += delta * (0.14 + activity * 0.9);
  innerShell.rotation.x = Math.sin(elapsed * 0.42) * 0.08;
  stem.scale.set(1 + voice * 0.08, 0.96 + activity * 0.08, 0.72 + voice * 0.04);
  base.scale.set(1 + activity * 0.08, 1, 0.45 + activity * 0.035);

  causticRings.children.forEach((child, index) => {
    const ring = child as THREE.Mesh<THREE.TorusGeometry, THREE.MeshBasicMaterial>;
    const phase = (elapsed * (0.3 + voice * 1.0) + index * 0.12) % 1;
    ring.position.y = 0.58 + phase * 1.7;
    ring.scale.setScalar(0.72 + phase * (0.7 + voice * 0.3));
    ring.material.color.copy(state.displayAccent);
    ring.material.opacity = (1 - phase) * (0.08 + activity * 0.24) * offline;
  });

  energyThreads.children.forEach((child, index) => {
    const line = child as THREE.Line<THREE.BufferGeometry, THREE.LineBasicMaterial>;
    line.rotation.y = elapsed * (0.14 + voice * 0.8) + index * 0.22;
    line.rotation.x = Math.sin(elapsed * 0.6 + index) * 0.12;
    line.material.color.copy(index % 2 === 0 ? state.displaySecondary : state.displayAccent);
    line.material.opacity = (0.04 + activity * 0.32) * offline;
  });

  const beatA = Math.pow(
    Math.max(0, Math.sin(elapsed * Math.PI * (1.05 + activity * 0.34))),
    12
  );
  const beatB = Math.pow(
    Math.max(0, Math.sin((elapsed - 0.17) * Math.PI * (1.05 + activity * 0.34))),
    16
  ) * 0.44;
  const heartbeat = beatA + beatB;
  visceralNetwork.children.forEach((child) => {
    const mesh = child as THREE.Mesh;
    const material = mesh.material as THREE.MeshBasicMaterial;
    const phase = (child.userData.phase as number) ?? 0;
    const flow = 0.5 + Math.sin(elapsed * (2.2 + activity) - phase) * 0.5;
    material.color.copy(state.displaySecondary).lerp(livingGreen, 0.34);
    material.opacity = (0.045 + flow * 0.13 + heartbeat * 0.09) * offline;

    if (child.userData.heart) {
      const heartScale = 1 + heartbeat * 0.13 + Math.sin(elapsed * 1.1) * 0.02;
      child.scale.set(0.92 * heartScale, 1.12 * heartScale, 0.88 * heartScale);
      child.rotation.y += delta * (0.12 + activity * 0.3);
    } else if (child.userData.node) {
      child.scale.setScalar(0.8 + flow * 0.9 + heartbeat * 0.45);
    }
  });

  modeRings.children.forEach((child, index) => {
    const ring = child as THREE.Mesh<THREE.TorusGeometry, THREE.MeshBasicMaterial>;
    ring.material.color.copy(index % 2 === 0 ? state.displaySecondary : state.displayAccent);
    ring.material.opacity = (0.12 + activity * 0.34) * offline;
    ring.rotation.z = (ring.userData.offset as number) + elapsed * (0.18 + activity * 0.5) * (index % 2 === 0 ? 1 : -1);
    const scale = 1 + Math.sin(elapsed * 1.6 + index) * 0.025 + activity * 0.035;
    ring.scale.set(scale, scale, scale);
  });

  particleField.rotation.y = elapsed * 0.025;
  const particleMaterial = particleField.material as THREE.PointsMaterial;
  particleMaterial.color.copy(state.displayAccent);
  particleMaterial.opacity = (0.14 + activity * 0.18) * offline;
  particleMaterial.size = 0.026 + activity * 0.018;

  room.children.forEach((child, index) => {
    if (child instanceof THREE.Mesh && child.material instanceof THREE.Material) {
      if ("opacity" in child.material && typeof child.material.opacity === "number") {
        const baseOpacity = child.userData.baseOpacity ?? child.material.opacity;
        child.userData.baseOpacity = baseOpacity;
        child.material.opacity = THREE.MathUtils.clamp(baseOpacity + Math.sin(elapsed * 0.5 + index) * activity * 0.018, 0.08, 0.9);
      }
    }

    if (child instanceof THREE.Group && typeof child.userData.spin === "number") {
      child.rotation.y += delta * child.userData.spin;
      child.rotation.z += Math.sin(elapsed * 0.6 + index) * delta * 0.08;
    }
  });

  bubbles.children.forEach((child, index) => {
    const bubble = child as THREE.Mesh<THREE.SphereGeometry, THREE.MeshPhysicalMaterial>;
    const speed = bubble.userData.speed as number;
    const phase = bubble.userData.phase as number;
    const range = bubble.userData.range as number;
    const normalized = (elapsed * speed + phase) % range;
    bubble.position.y = normalized;
    bubble.position.x = (bubble.userData.baseX as number) + Math.sin(elapsed * 0.6 + phase) * 0.12;
    bubble.position.z += Math.sin(elapsed * 0.4 + index) * 0.0008;
    bubble.scale.setScalar(1 + Math.sin(elapsed * 1.2 + phase) * 0.08);
    bubble.material.attenuationColor.copy(state.displaySecondary);
    bubble.material.opacity = 0.22 + activity * 0.08;
  });

  lights.rim.color.copy(state.displaySecondary);
  lights.coreLight.color.copy(state.displayAccent);
  lights.roomPulse.color.copy(state.displaySecondary).lerp(softRoomWhite, 0.56);
  lights.modeGlow.color.copy(state.displaySecondary);
  lights.spillLight.color.copy(state.displaySecondary);
  lights.rim.intensity = (1.3 + activity * 1.4) * offline;
  lights.coreLight.intensity = (1.8 + activity * 3.4) * offline;
  lights.roomPulse.intensity = (0.25 + activity * 0.35) * offline;
  lights.modeGlow.intensity = (0.8 + activity * 2.3) * offline;
  lights.spillLight.intensity = (0.35 + activity * 1.45) * offline;

  bloomPass.strength = (0.055 + activity * 0.17) * offline;
  bloomPass.radius = 0.2 + activity * 0.1;

  camera.position.x = Math.sin(elapsed * 0.12) * 0.16 + voice * Math.sin(elapsed * 1.4) * 0.045;
  camera.position.y = 1.55 + Math.sin(elapsed * 0.17) * 0.035;
  camera.lookAt(tmpVector.set(0, 1.05 + Math.sin(elapsed * 0.2) * 0.028, -0.22));

  energyLabelEl.textContent = `${Math.round(state.targetEnergy * 100)}%`;
  composer.render();
  requestAnimationFrame(animate);
}

buttons.forEach((button) => {
  button.addEventListener("click", () => setMode(button.dataset.mode as Mode));
});

energyInputEl.addEventListener("input", () => {
  state.targetEnergy = Number(energyInputEl.value) / 100;
});

if (previewParams.get("standalone") !== "1") {
  connectRuntime();
}

window.addEventListener("resize", () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  composer.setSize(window.innerWidth, window.innerHeight);
  bloomPass.setSize(window.innerWidth, window.innerHeight);
});
