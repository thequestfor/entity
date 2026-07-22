const canvas = document.getElementById("entity-canvas");
const ctx = canvas.getContext("2d");
const buttons = [...document.querySelectorAll("[data-mode]")];
const energyInput = document.getElementById("energy");
const bloomInput = document.getElementById("bloom");
const messageInput = document.getElementById("message");
const scanlineOverlay = document.querySelector(".scanline-overlay");
const scanlinesInput = document.getElementById("scanlines");
const modeReadout = document.getElementById("mode-readout");
const energyReadout = document.getElementById("energy-readout");
const messageReadout = document.getElementById("message-readout");

const palettes = {
  idle: {
    primary: "#edf8f8",
    secondary: "#53c5cf",
    accent: "#ffffff",
    label: "IDLE",
    message: "Soft standby",
    rotation: 0.18,
    pulse: 0.18
  },
  listening: {
    primary: "#eef6ff",
    secondary: "#4f8cff",
    accent: "#b8d8ff",
    label: "LISTENING",
    message: "Listening",
    rotation: 0.28,
    pulse: 0.36
  },
  thinking: {
    primary: "#f6f1ff",
    secondary: "#a56cff",
    accent: "#e0c9ff",
    label: "THINKING",
    message: "Planning",
    rotation: 0.95,
    pulse: 0.28
  },
  speaking: {
    primary: "#effff5",
    secondary: "#64ef91",
    accent: "#c8ffda",
    label: "SPEAKING",
    message: "Speaking",
    rotation: 0.42,
    pulse: 0.52
  },
  acting: {
    primary: "#fff8ed",
    secondary: "#ffad55",
    accent: "#ffe0ae",
    label: "ACTING",
    message: "Executing action",
    rotation: 0.7,
    pulse: 0.32
  },
  autonomous_goal: {
    primary: "#fffbea",
    secondary: "#ffd45f",
    accent: "#fff0ae",
    label: "AUTONOMOUS",
    message: "Autonomous goal active",
    rotation: 0.36,
    pulse: 0.24
  },
  waiting_confirmation: {
    primary: "#fff4d7",
    secondary: "#e2b45d",
    accent: "#ffe7ad",
    label: "WAITING",
    message: "Confirmation requested",
    rotation: 0.2,
    pulse: 0.4
  },
  service_issue: {
    primary: "#fff1e7",
    secondary: "#ff8664",
    accent: "#ffd3bd",
    label: "SERVICE",
    message: "Service attention needed",
    rotation: 0.14,
    pulse: 0.18
  },
  offline: {
    primary: "#a9b0b3",
    secondary: "#4d565b",
    accent: "#d2d7d9",
    label: "OFFLINE",
    message: "Low power standby",
    rotation: 0.04,
    pulse: 0.08
  }
};

const state = {
  mode: "idle",
  energy: 0.62,
  bloom: 0.74,
  targetEnergy: 0.62,
  targetBloom: 0.74,
  message: "Soft standby",
  speechActivity: 0,
  targetSpeechActivity: 0,
  hasLiveSpeechActivity: false,
  lastSpeechActivityAt: 0
};

let start = performance.now();
let dpr = 1;

function resize() {
  const rect = canvas.getBoundingClientRect();
  dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
  canvas.width = Math.floor(rect.width * dpr);
  canvas.height = Math.floor(rect.height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function setMode(mode) {
  if (!palettes[mode]) {
    return;
  }

  if (mode !== "speaking") {
    state.speechActivity = 0;
    state.targetSpeechActivity = 0;
    state.hasLiveSpeechActivity = false;
  }
  state.mode = mode;
  const palette = palettes[mode];
  state.message = palette.message;
  messageInput.value = palette.message;
  buttons.forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === mode);
  });
  syncReadouts();
}

function syncReadouts() {
  const palette = palettes[state.mode];
  modeReadout.textContent = palette.label;
  energyReadout.textContent = `${Math.round(state.targetEnergy * 100)}%`;
  messageReadout.textContent = state.message;
  scanlineOverlay.classList.toggle("off", !scanlinesInput.checked);
}

function lerp(a, b, t) {
  return a + (b - a) * t;
}

function hexToRgb(hex) {
  const clean = hex.replace("#", "");
  const value = parseInt(clean, 16);
  return {
    r: (value >> 16) & 255,
    g: (value >> 8) & 255,
    b: value & 255
  };
}

function rgba(hex, alpha) {
  const color = hexToRgb(hex);
  return `rgba(${color.r}, ${color.g}, ${color.b}, ${alpha})`;
}

function voiceIntensity(time, energy) {
  if (state.mode !== "speaking") {
    return 0;
  }

  if (state.hasLiveSpeechActivity) {
    return state.speechActivity * (0.55 + energy * 0.45);
  }

  const fast = Math.abs(Math.sin(time * 7.6));
  const syllable = Math.abs(Math.sin(time * 12.4 + Math.sin(time * 1.1) * 0.7));
  return (0.32 + fast * 0.38 + syllable * 0.3) * (0.55 + energy * 0.45);
}

function activeEnergy(time, energy) {
  const voice = voiceIntensity(time, energy);
  return Math.max(voice, palettes[state.mode].pulse * 0.35 + energy * 0.12);
}

function drawBackground(width, height, palette, time) {
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.min(width, height) * 0.42;
  const gradient = ctx.createRadialGradient(cx, cy, radius * 0.05, cx, cy, radius * 1.45);
  gradient.addColorStop(0, rgba("#ffffff", 0.32));
  gradient.addColorStop(0.38, rgba(palette.secondary, 0.18));
  gradient.addColorStop(0.72, "rgba(68, 103, 116, 0.16)");
  gradient.addColorStop(1, "rgba(8, 18, 22, 0.04)");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);

  ctx.save();
  ctx.globalAlpha = 0.028;
  ctx.strokeStyle = palette.primary;
  ctx.lineWidth = 1;
  const spacing = 34;
  const drift = (time * 8) % spacing;
  for (let x = -spacing; x < width + spacing; x += spacing) {
    ctx.beginPath();
    ctx.moveTo(x + drift, 0);
    ctx.lineTo(x - 90 + drift, height);
    ctx.stroke();
  }
  ctx.restore();
}

function drawLivingBackground(width, height, palette, time, energy) {
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.min(width, height) * 0.31;

  drawAeroContext(width, height, cx, cy, radius, palette, time, energy);

  ctx.save();
  ctx.globalCompositeOperation = "screen";
  ctx.lineCap = "round";
  ctx.lineWidth = 1;

  for (let i = 0; i < 9; i += 1) {
    const y = height * (0.18 + i * 0.075);
    const phase = time * (0.06 + i * 0.004) + i * 0.8;
    const alpha = 0.035 + energy * 0.018;
    const gradient = ctx.createLinearGradient(0, y, width, y);
    gradient.addColorStop(0, "rgba(255,255,255,0)");
    gradient.addColorStop(0.28, rgba(palette.secondary, alpha));
    gradient.addColorStop(0.52, "rgba(255,255,255,0.05)");
    gradient.addColorStop(0.76, rgba("#bff8ff", alpha * 0.8));
    gradient.addColorStop(1, "rgba(255,255,255,0)");

    ctx.strokeStyle = gradient;
    ctx.beginPath();
    for (let x = -24; x <= width + 24; x += 20) {
      const n = x / width;
      const lift = Math.sin(n * Math.PI * 2.2 + phase) * 8;
      const breathe = Math.cos(n * Math.PI * 1.6 - phase * 0.7) * 4;
      if (x === -24) {
        ctx.moveTo(x, y + lift + breathe);
      } else {
        ctx.lineTo(x, y + lift + breathe);
      }
    }
    ctx.globalAlpha = 0.7;
    ctx.stroke();
  }

  for (let i = 0; i < 18; i += 1) {
    const angle = time * (0.025 + i * 0.0008) + i * 2.399;
    const distance = radius * (1.55 + ((i * 31) % 70) / 100);
    const x = cx + Math.cos(angle) * distance * 1.45;
    const y = cy + Math.sin(angle * 0.82) * distance * 0.82;
    const size = 0.9 + ((i * 11) % 5) * 0.25;
    const twinkle = 0.24 + Math.sin(time * 0.5 + i) * 0.12;
    ctx.globalAlpha = twinkle * (0.45 + energy * 0.25);
    ctx.fillStyle = i % 4 === 0 ? rgba("#fff3bf", 0.36) : rgba(palette.primary, 0.42);
    ctx.shadowColor = i % 4 === 0 ? rgba("#fff3bf", 0.25) : rgba(palette.secondary, 0.3);
    ctx.shadowBlur = 9 * state.bloom;
    ctx.beginPath();
    ctx.arc(x, y, size, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.restore();
}

function drawAeroContext(width, height, cx, cy, radius, palette, time, energy) {
  const floorY = cy + radius * 1.03;
  const activity = activeEnergy(time, energy);

  drawControlRoom(width, height, cx, cy, radius, palette, time, energy);

  ctx.save();
  ctx.globalCompositeOperation = "screen";

  const horizon = ctx.createLinearGradient(0, floorY - radius * 1.2, 0, height);
  horizon.addColorStop(0, "rgba(255,255,255,0)");
  horizon.addColorStop(0.42, rgba("#d7fffb", 0.07));
  horizon.addColorStop(0.68, rgba("#ffffff", 0.1));
  horizon.addColorStop(1, rgba("#8fe7ef", 0.05));
  ctx.fillStyle = horizon;
  ctx.fillRect(0, floorY - radius * 1.2, width, height - floorY + radius * 1.2);

  const vanishingY = floorY - radius * 0.46;
  ctx.lineCap = "round";
  for (let i = -9; i <= 9; i += 1) {
    const startX = cx + i * radius * 0.34;
    const endX = cx + i * radius * 1.15;
    const alpha = 0.035 + activity * 0.018;
    const perspective = ctx.createLinearGradient(startX, vanishingY, endX, height);
    perspective.addColorStop(0, "rgba(255,255,255,0)");
    perspective.addColorStop(0.42, rgba("#ffffff", alpha));
    perspective.addColorStop(1, "rgba(255,255,255,0)");
    ctx.strokeStyle = perspective;
    ctx.lineWidth = 0.9;
    ctx.beginPath();
    ctx.moveTo(startX, vanishingY);
    ctx.lineTo(endX, height + radius * 0.3);
    ctx.stroke();
  }

  for (let i = 0; i < 7; i += 1) {
    const depth = i / 6;
    const y = floorY + radius * (0.02 + depth * 0.62);
    const widthScale = 0.85 + depth * 2.4;
    const alpha = 0.052 - depth * 0.022 + activity * 0.015;
    ctx.strokeStyle = rgba(i % 2 === 0 ? "#ffffff" : palette.secondary, alpha);
    ctx.lineWidth = 1.05;
    ctx.beginPath();
    ctx.ellipse(
      cx,
      y,
      radius * widthScale,
      radius * (0.11 + depth * 0.08),
      0,
      Math.PI * 1.02,
      Math.PI * 1.98
    );
    ctx.stroke();
  }

  for (let i = 0; i < 5; i += 1) {
    const panelX = cx + (i - 2) * radius * 0.82 + Math.sin(time * 0.08 + i) * radius * 0.03;
    const panelY = cy - radius * (0.92 - (i % 2) * 0.24);
    const panelW = radius * (0.42 + (i % 3) * 0.08);
    const panelH = radius * (0.58 + (i % 2) * 0.2);
    const panel = ctx.createLinearGradient(panelX, panelY, panelX + panelW, panelY + panelH);
    panel.addColorStop(0, "rgba(255,255,255,0)");
    panel.addColorStop(0.4, rgba("#ffffff", 0.035 + activity * 0.01));
    panel.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = panel;
    ctx.beginPath();
    ctx.moveTo(panelX - panelW * 0.5, panelY);
    ctx.lineTo(panelX + panelW * 0.45, panelY + panelH * 0.08);
    ctx.lineTo(panelX + panelW * 0.62, panelY + panelH);
    ctx.lineTo(panelX - panelW * 0.62, panelY + panelH * 0.88);
    ctx.closePath();
    ctx.fill();
  }

  for (let i = 0; i < 11; i += 1) {
    const spread = i - 5;
    const alpha = 0.035 + energy * 0.014;
    const x0 = cx + spread * radius * 0.24 + Math.sin(time * 0.05 + i) * 8;
    const y0 = floorY + radius * 0.18;
    const x1 = cx + spread * radius * 0.58;
    const y1 = height + radius * 0.4;
    const lane = ctx.createLinearGradient(x0, y0, x1, y1);
    lane.addColorStop(0, "rgba(255,255,255,0)");
    lane.addColorStop(0.36, rgba(palette.primary, alpha));
    lane.addColorStop(1, "rgba(255,255,255,0)");
    ctx.strokeStyle = lane;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.quadraticCurveTo(cx + spread * radius * 0.4, floorY + radius * 0.62, x1, y1);
    ctx.stroke();
  }

  for (let i = 0; i < 5; i += 1) {
    const y = floorY + radius * (0.02 + i * 0.075);
    const widthScale = 1.5 + i * 0.34;
    const alpha = 0.04 - i * 0.004 + energy * 0.01;
    ctx.strokeStyle = rgba(i % 2 === 0 ? "#ffffff" : palette.secondary, alpha);
    ctx.lineWidth = 1.15;
    ctx.beginPath();
    ctx.ellipse(
      cx,
      y + Math.sin(time * 0.12 + i) * 2.4,
      radius * widthScale,
      radius * (0.18 + i * 0.02),
      0,
      Math.PI * 1.04,
      Math.PI * 1.96
    );
    ctx.stroke();
  }

  const leftLeaf = ctx.createLinearGradient(cx - radius * 1.9, cy - radius * 0.45, cx, floorY);
  leftLeaf.addColorStop(0, "rgba(255,255,255,0)");
  leftLeaf.addColorStop(0.48, rgba("#b8fff0", 0.05));
  leftLeaf.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = leftLeaf;
  ctx.beginPath();
  ctx.moveTo(cx - radius * 2.25, floorY + radius * 0.08);
  ctx.bezierCurveTo(
    cx - radius * 1.35,
    cy - radius * 0.9,
    cx - radius * 0.6,
    cy - radius * 0.74,
    cx - radius * 0.22,
    floorY - radius * 0.1
  );
  ctx.bezierCurveTo(
    cx - radius * 0.75,
    floorY + radius * 0.2,
    cx - radius * 1.6,
    floorY + radius * 0.3,
    cx - radius * 2.25,
    floorY + radius * 0.08
  );
  ctx.fill();

  const rightLeaf = ctx.createLinearGradient(cx + radius * 2.0, cy - radius * 0.28, cx, floorY);
  rightLeaf.addColorStop(0, "rgba(255,255,255,0)");
  rightLeaf.addColorStop(0.5, rgba("#ccefff", 0.045));
  rightLeaf.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = rightLeaf;
  ctx.beginPath();
  ctx.moveTo(cx + radius * 2.22, floorY + radius * 0.02);
  ctx.bezierCurveTo(
    cx + radius * 1.42,
    cy - radius * 0.66,
    cx + radius * 0.74,
    cy - radius * 0.54,
    cx + radius * 0.3,
    floorY - radius * 0.04
  );
  ctx.bezierCurveTo(
    cx + radius * 0.82,
    floorY + radius * 0.22,
    cx + radius * 1.6,
    floorY + radius * 0.24,
    cx + radius * 2.22,
    floorY + radius * 0.02
  );
  ctx.fill();

  ctx.restore();
}

function drawControlRoom(width, height, cx, cy, radius, palette, time, energy) {
  const activity = activeEnergy(time, energy);
  const horizonY = cy + radius * 0.74;
  const floorY = cy + radius * 1.08;
  const leftWallX = cx - radius * 2.15;
  const rightWallX = cx + radius * 2.15;

  ctx.save();
  ctx.globalCompositeOperation = "source-over";

  const room = ctx.createLinearGradient(0, 0, 0, height);
  room.addColorStop(0, "rgba(231, 249, 255, 0.2)");
  room.addColorStop(0.38, "rgba(146, 193, 205, 0.2)");
  room.addColorStop(0.7, "rgba(57, 112, 127, 0.2)");
  room.addColorStop(1, "rgba(10, 39, 49, 0.28)");
  ctx.fillStyle = room;
  ctx.fillRect(0, 0, width, height);

  ctx.globalCompositeOperation = "multiply";
  const ceilingShade = ctx.createLinearGradient(0, 0, 0, height * 0.46);
  ceilingShade.addColorStop(0, "rgba(34, 79, 90, 0.1)");
  ceilingShade.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = ceilingShade;
  ctx.fillRect(0, 0, width, height * 0.46);

  const floorShade = ctx.createLinearGradient(0, horizonY, 0, height);
  floorShade.addColorStop(0, "rgba(255,255,255,0)");
  floorShade.addColorStop(0.58, "rgba(44, 91, 104, 0.08)");
  floorShade.addColorStop(1, "rgba(10, 35, 44, 0.2)");
  ctx.fillStyle = floorShade;
  ctx.beginPath();
  ctx.moveTo(leftWallX, horizonY);
  ctx.lineTo(rightWallX, horizonY);
  ctx.lineTo(width + radius * 0.6, height);
  ctx.lineTo(-radius * 0.6, height);
  ctx.closePath();
  ctx.fill();
  ctx.restore();

  ctx.save();
  ctx.globalCompositeOperation = "source-over";

  const leftWall = ctx.createLinearGradient(0, cy - radius, leftWallX, floorY);
  leftWall.addColorStop(0, "rgba(238, 253, 255, 0.06)");
  leftWall.addColorStop(0.52, "rgba(82, 137, 151, 0.14)");
  leftWall.addColorStop(1, "rgba(22, 61, 72, 0.2)");
  ctx.fillStyle = leftWall;
  ctx.beginPath();
  ctx.moveTo(0, cy - radius * 1.18);
  ctx.lineTo(leftWallX, horizonY);
  ctx.lineTo(leftWallX + radius * 0.42, height);
  ctx.lineTo(0, height);
  ctx.closePath();
  ctx.fill();

  const rightWall = ctx.createLinearGradient(width, cy - radius, rightWallX, floorY);
  rightWall.addColorStop(0, "rgba(238, 253, 255, 0.05)");
  rightWall.addColorStop(0.52, "rgba(72, 126, 142, 0.15)");
  rightWall.addColorStop(1, "rgba(18, 55, 68, 0.22)");
  ctx.fillStyle = rightWall;
  ctx.beginPath();
  ctx.moveTo(width, cy - radius * 1.18);
  ctx.lineTo(rightWallX, horizonY);
  ctx.lineTo(rightWallX - radius * 0.42, height);
  ctx.lineTo(width, height);
  ctx.closePath();
  ctx.fill();

  const backGlass = ctx.createRadialGradient(cx, cy - radius * 0.08, radius * 0.22, cx, cy, radius * 1.42);
  backGlass.addColorStop(0, "rgba(255,255,255,0.05)");
  backGlass.addColorStop(0.5, "rgba(91, 154, 169, 0.08)");
  backGlass.addColorStop(1, "rgba(20, 68, 81, 0.16)");
  ctx.fillStyle = backGlass;
  ctx.beginPath();
  ctx.moveTo(cx - radius * 1.46, cy - radius * 1.06);
  ctx.lineTo(cx + radius * 1.46, cy - radius * 1.06);
  ctx.lineTo(cx + radius * 1.86, floorY + radius * 0.1);
  ctx.lineTo(cx - radius * 1.86, floorY + radius * 0.1);
  ctx.closePath();
  ctx.fill();

  ctx.restore();

  ctx.save();
  ctx.globalCompositeOperation = "screen";
  ctx.lineCap = "round";

  const backPanel = ctx.createLinearGradient(cx, cy - radius * 1.2, cx, floorY);
  backPanel.addColorStop(0, "rgba(255,255,255,0.04)");
  backPanel.addColorStop(0.48, rgba("#dffcff", 0.055 + activity * 0.014));
  backPanel.addColorStop(1, "rgba(255,255,255,0.018)");
  ctx.fillStyle = backPanel;
  ctx.beginPath();
  ctx.moveTo(cx - radius * 1.3, cy - radius * 1.14);
  ctx.lineTo(cx + radius * 1.3, cy - radius * 1.14);
  ctx.lineTo(cx + radius * 1.74, floorY + radius * 0.05);
  ctx.lineTo(cx - radius * 1.74, floorY + radius * 0.05);
  ctx.closePath();
  ctx.fill();

  ctx.strokeStyle = rgba("#ffffff", 0.075 + activity * 0.018);
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(cx - radius * 1.3, cy - radius * 1.14);
  ctx.lineTo(cx - radius * 1.74, floorY + radius * 0.05);
  ctx.moveTo(cx + radius * 1.3, cy - radius * 1.14);
  ctx.lineTo(cx + radius * 1.74, floorY + radius * 0.05);
  ctx.moveTo(cx - radius * 1.74, floorY + radius * 0.05);
  ctx.lineTo(cx + radius * 1.74, floorY + radius * 0.05);
  ctx.stroke();

  drawRoomSidePanels(cx, cy, radius, palette, time, activity, -1);
  drawRoomSidePanels(cx, cy, radius, palette, time, activity, 1);
  drawRoomMonitorBanks(cx, cy, radius, palette, time, activity);
  drawRoomConsoles(width, height, cx, cy, radius, palette, time, activity);
  drawRoomLightRails(width, height, cx, cy, radius, palette, time, activity);

  ctx.restore();
}

function drawRoomMonitorBanks(cx, cy, radius, palette, time, activity) {
  const banks = [
    { x: -1.58, y: -0.76, tilt: -0.11 },
    { x: 1.58, y: -0.76, tilt: 0.11 },
    { x: -1.86, y: -0.14, tilt: -0.16 },
    { x: 1.86, y: -0.14, tilt: 0.16 }
  ];

  banks.forEach((bank, index) => {
    const x = cx + radius * bank.x;
    const y = cy + radius * bank.y;
    const w = radius * (0.54 + (index % 2) * 0.12);
    const h = radius * 0.3;
    const glow = 0.08 + activity * 0.06 + Math.sin(time * 0.7 + index) * 0.012;
    const panel = ctx.createLinearGradient(x - w, y - h, x + w, y + h);
    panel.addColorStop(0, "rgba(255,255,255,0.03)");
    panel.addColorStop(0.42, rgba(index % 2 === 0 ? "#ffffff" : palette.secondary, glow));
    panel.addColorStop(1, "rgba(16, 68, 82, 0.02)");
    ctx.fillStyle = panel;
    ctx.beginPath();
    ctx.moveTo(x - w * 0.5, y - h * 0.42);
    ctx.lineTo(x + w * 0.55, y - h * 0.28 + bank.tilt * radius);
    ctx.lineTo(x + w * 0.48, y + h * 0.54);
    ctx.lineTo(x - w * 0.58, y + h * 0.38 - bank.tilt * radius);
    ctx.closePath();
    ctx.fill();

    ctx.strokeStyle = rgba("#ffffff", 0.12 + activity * 0.035);
    ctx.lineWidth = 0.9;
    ctx.stroke();

    for (let i = 0; i < 5; i += 1) {
      const lineY = y - h * 0.16 + i * h * 0.13;
      const pulse = 0.055 + activity * 0.04 + Math.sin(time * 1.1 + i + index) * 0.01;
      ctx.strokeStyle = rgba(i % 2 === 0 ? palette.secondary : "#ffffff", pulse);
      ctx.beginPath();
      ctx.moveTo(x - w * 0.32, lineY);
      ctx.lineTo(x + w * (0.14 + i * 0.06), lineY + bank.tilt * radius * 0.18);
      ctx.stroke();
    }
  });
}

function drawRoomSidePanels(cx, cy, radius, palette, time, activity, side) {
  const wallX = cx + side * radius * 1.82;
  const slant = side * radius * 0.42;

  for (let i = 0; i < 3; i += 1) {
    const y = cy - radius * (0.9 - i * 0.48);
    const w = radius * (0.52 + i * 0.04);
    const h = radius * 0.3;
    const pulse = 0.075 + activity * 0.055 + Math.sin(time * 0.6 + i * 1.7) * 0.012;
    const panel = ctx.createLinearGradient(wallX, y, wallX + side * w, y + h);
    panel.addColorStop(0, "rgba(255,255,255,0)");
    panel.addColorStop(0.42, rgba(i % 2 === 0 ? palette.secondary : "#ffffff", pulse));
    panel.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = panel;
    ctx.beginPath();
    ctx.moveTo(wallX, y);
    ctx.lineTo(wallX + side * w, y + h * 0.12);
    ctx.lineTo(wallX + side * (w + slant * 0.28), y + h);
    ctx.lineTo(wallX + side * slant * 0.16, y + h * 0.86);
    ctx.closePath();
    ctx.fill();

    ctx.strokeStyle = rgba("#ffffff", 0.14 + activity * 0.04);
    ctx.lineWidth = 1;
    ctx.stroke();

    for (let j = 0; j < 4; j += 1) {
      const lineY = y + h * (0.25 + j * 0.14);
      ctx.strokeStyle = rgba(j % 2 === 0 ? "#ffffff" : palette.secondary, 0.08 + activity * 0.035);
      ctx.beginPath();
      ctx.moveTo(wallX + side * w * 0.13, lineY);
      ctx.lineTo(wallX + side * w * (0.72 + Math.sin(time * 0.5 + j) * 0.04), lineY + h * 0.04);
      ctx.stroke();
    }
  }
}

function drawRoomConsoles(width, height, cx, cy, radius, palette, time, activity) {
  const consoleY = cy + radius * 1.34;
  const consoleH = radius * 0.48;
  const console = ctx.createLinearGradient(cx, consoleY - consoleH, cx, height);
  console.addColorStop(0, "rgba(255,255,255,0.18)");
  console.addColorStop(0.34, rgba("#c8f7ff", 0.13 + activity * 0.03));
  console.addColorStop(1, "rgba(17, 54, 66, 0.2)");
  ctx.fillStyle = console;
  ctx.beginPath();
  ctx.moveTo(cx - radius * 2.35, consoleY);
  ctx.lineTo(cx + radius * 2.35, consoleY);
  ctx.lineTo(width + radius * 0.25, height + radius * 0.12);
  ctx.lineTo(-radius * 0.25, height + radius * 0.12);
  ctx.closePath();
  ctx.fill();

  ctx.strokeStyle = rgba("#ffffff", 0.24 + activity * 0.04);
  ctx.lineWidth = 1.35;
  ctx.beginPath();
  ctx.moveTo(cx - radius * 2.35, consoleY);
  ctx.quadraticCurveTo(cx, consoleY + radius * 0.16, cx + radius * 2.35, consoleY);
  ctx.stroke();

  for (let i = 0; i < 7; i += 1) {
    const t = i / 6;
    const x = cx - radius * 1.6 + t * radius * 3.2;
    const y = consoleY + radius * (0.16 + Math.sin(time * 0.5 + i) * 0.01);
    const w = radius * (0.22 + (i % 3) * 0.035);
    const alpha = 0.09 + activity * 0.075;
    const tile = ctx.createLinearGradient(x - w, y, x + w, y + radius * 0.18);
    tile.addColorStop(0, "rgba(255,255,255,0)");
    tile.addColorStop(0.5, rgba(i % 3 === 0 ? "#ffffff" : palette.secondary, alpha));
    tile.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = tile;
    ctx.beginPath();
    ctx.ellipse(x, y, w, radius * 0.055, 0, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.strokeStyle = rgba("#ffffff", 0.09 + activity * 0.025);
  ctx.lineWidth = 0.8;
  for (let i = 0; i < 9; i += 1) {
    const spread = i - 4;
    ctx.beginPath();
    ctx.moveTo(cx + spread * radius * 0.32, consoleY + radius * 0.02);
    ctx.lineTo(cx + spread * radius * 0.58, height + radius * 0.08);
    ctx.stroke();
  }
}

function drawRoomLightRails(width, height, cx, cy, radius, palette, time, activity) {
  const rails = [
    { y: cy - radius * 1.22, width: 1.95, alpha: 0.08 },
    { y: cy - radius * 0.98, width: 1.58, alpha: 0.055 },
    { y: cy + radius * 0.96, width: 2.05, alpha: 0.07 }
  ];

  rails.forEach((rail, index) => {
    const railWidth = radius * rail.width;
    const glow = ctx.createLinearGradient(cx - railWidth, rail.y, cx + railWidth, rail.y);
    glow.addColorStop(0, "rgba(255,255,255,0)");
    glow.addColorStop(0.22, rgba(palette.secondary, rail.alpha + activity * 0.025));
    glow.addColorStop(0.5, rgba("#ffffff", rail.alpha + activity * 0.02));
    glow.addColorStop(0.78, rgba("#bff8ff", rail.alpha * 0.8 + activity * 0.018));
    glow.addColorStop(1, "rgba(255,255,255,0)");
    ctx.strokeStyle = glow;
    ctx.lineWidth = index === 0 ? 1.8 : 1.1;
    ctx.beginPath();
    ctx.moveTo(cx - railWidth, rail.y + Math.sin(time * 0.2 + index) * 2);
    ctx.quadraticCurveTo(cx, rail.y + radius * 0.055, cx + railWidth, rail.y + Math.cos(time * 0.18 + index) * 2);
    ctx.stroke();
  });
}

function blobPoint(cx, cy, radius, angle, time, energy, wobble) {
  const softness =
    1
    + Math.sin(angle * 2.1 + time * 0.52) * wobble
    + Math.cos(angle * 3.4 - time * 0.32) * wobble * 0.34
    + Math.sin(angle * 5.7 + time * 0.2) * wobble * 0.12;
  const stretchX = 1.012 + energy * 0.006;
  const stretchY = 0.998 + Math.sin(time * 0.42) * 0.005;

  return {
    x: cx + Math.cos(angle) * radius * softness * stretchX,
    y: cy + Math.sin(angle) * radius * softness * stretchY
  };
}

function drawBlobPath(cx, cy, radius, time, energy, wobble) {
  const points = [];
  const count = 96;

  for (let i = 0; i < count; i += 1) {
    const angle = (Math.PI * 2 * i) / count;
    points.push(blobPoint(cx, cy, radius, angle, time, energy, wobble));
  }

  ctx.beginPath();
  for (let i = 0; i < points.length; i += 1) {
    const current = points[i];
    const next = points[(i + 1) % points.length];
    const midX = (current.x + next.x) / 2;
    const midY = (current.y + next.y) / 2;

    if (i === 0) {
      ctx.moveTo(midX, midY);
    } else {
      ctx.quadraticCurveTo(current.x, current.y, midX, midY);
    }
  }
  ctx.closePath();
}

function drawGlassBlob(cx, cy, radius, palette, time, energy) {
  const modePulse = palettes[state.mode].pulse;
  const voice = voiceIntensity(time, energy);
  const activity = activeEnergy(time, energy);
  const breathing =
    1
    + Math.sin(time * 1.12) * 0.014 * (0.5 + modePulse)
    + activity * 0.018;
  const blobRadius = radius * 0.94 * breathing;
  const wobble = 0.01 + energy * 0.006 + activity * 0.018;

  ctx.save();
  drawBlobPath(cx, cy, blobRadius * 1.12, time, energy, wobble);
  ctx.shadowColor = rgba(palette.secondary, 0.36 * state.bloom);
  ctx.shadowBlur = 86 * state.bloom;
  const aura = ctx.createRadialGradient(cx, cy, radius * 0.08, cx, cy, radius * 1.12);
  aura.addColorStop(0, rgba("#ffffff", 0.18 + energy * 0.04 + voice * 0.025));
  aura.addColorStop(0.52, rgba(palette.secondary, 0.095 + voice * 0.035));
  aura.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = aura;
  ctx.fill();
  ctx.restore();

  ctx.save();
  drawBlobPath(cx, cy, blobRadius, time, energy, wobble);
  const body = ctx.createRadialGradient(
    cx - radius * 0.22,
    cy - radius * 0.3,
    radius * 0.06,
    cx,
    cy,
    radius
  );
  body.addColorStop(0, rgba("#ffffff", 0.72));
  body.addColorStop(0.16, rgba(palette.primary, 0.24 + voice * 0.045));
  body.addColorStop(0.44, rgba(palette.secondary, 0.09 + voice * 0.035));
  body.addColorStop(0.76, rgba("#e9fdff", 0.04));
  body.addColorStop(1, rgba("#ffffff", 0.012));
  ctx.fillStyle = body;
  ctx.shadowColor = rgba(palette.primary, 0.22 * state.bloom);
  ctx.shadowBlur = 34 * state.bloom;
  ctx.fill();

  ctx.save();
  drawBlobPath(cx, cy, blobRadius * 0.96, time, energy, wobble);
  ctx.clip();
  drawInteriorShadow(cx, cy, radius, palette, time, energy);
  drawRefractionPools(cx, cy, radius, palette, time, energy);
  drawLivingCore(cx, cy, radius, palette, time, energy);
  drawNervePlexus(cx, cy, radius, palette, time, energy);
  drawFrostedSparkle(cx, cy, radius, palette, time, energy);
  ctx.restore();

  ctx.globalCompositeOperation = "screen";
  const highlight = ctx.createLinearGradient(
    cx - radius * 0.6,
    cy - radius * 0.72,
    cx + radius * 0.45,
    cy + radius * 0.1
  );
  highlight.addColorStop(0, "rgba(255,255,255,0.3)");
  highlight.addColorStop(0.2, "rgba(255,255,255,0.08)");
  highlight.addColorStop(0.5, "rgba(255,255,255,0.012)");
  highlight.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = highlight;
  ctx.fill();
  ctx.restore();

  drawBlobSpecular(cx, cy, radius, palette, time, energy);
  drawGlassCaustics(cx, cy, radius, palette, time, energy);
  drawEdgeOcclusion(cx, cy, blobRadius, palette, time, energy, wobble);
  drawGlassRim(cx, cy, blobRadius, palette, time, energy, wobble);
}

function seededWave(index, time, speed = 1) {
  const raw = Math.sin(index * 12.9898 + time * speed) * 43758.5453;
  return raw - Math.floor(raw);
}

function drawInteriorShadow(cx, cy, radius, palette, time, energy) {
  ctx.save();
  ctx.globalCompositeOperation = "source-over";
  ctx.filter = `blur(${radius * 0.018}px)`;
  const flowX = Math.sin(time * 0.18) * radius * 0.08;
  const flowY = Math.cos(time * 0.14) * radius * 0.035;
  const shadow = ctx.createRadialGradient(
    cx + radius * 0.1 + flowX,
    cy - radius * 0.34 + flowY,
    radius * 0.05,
    cx + flowX * 0.35,
    cy - radius * 0.24 + flowY,
    radius * 0.82
  );
  shadow.addColorStop(0, "rgba(11, 66, 92, 0.11)");
  shadow.addColorStop(0.44, "rgba(41, 124, 145, 0.05)");
  shadow.addColorStop(0.82, "rgba(255, 255, 255, 0)");
  shadow.addColorStop(1, "rgba(0, 0, 0, 0)");
  ctx.fillStyle = shadow;
  ctx.beginPath();
  ctx.ellipse(
    cx + radius * 0.08 + flowX,
    cy - radius * 0.3 + flowY,
    radius * (0.76 + Math.sin(time * 0.13) * 0.04),
    radius * (0.2 + Math.cos(time * 0.17) * 0.025),
    -0.12 + Math.sin(time * 0.16) * 0.08,
    0,
    Math.PI * 2
  );
  ctx.fill();
  ctx.restore();

  ctx.save();
  ctx.globalCompositeOperation = "screen";
  const glow = ctx.createRadialGradient(
    cx - radius * 0.18,
    cy + radius * 0.08,
    radius * 0.03,
    cx,
    cy,
    radius * 0.74
  );
  glow.addColorStop(0, rgba(palette.primary, 0.22 + energy * 0.08));
  glow.addColorStop(0.44, rgba("#78f5ef", 0.09));
  glow.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = glow;
  ctx.beginPath();
  ctx.arc(cx, cy, radius * 0.78, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function drawRefractionPools(cx, cy, radius, palette, time, energy) {
  const activity = activeEnergy(time, energy);
  const pools = [
    {
      x: -0.18,
      y: 0.32,
      rx: 0.52,
      ry: 0.16,
      color: "#28e7df",
      alpha: 0.13
    },
    {
      x: 0.26,
      y: 0.26,
      rx: 0.38,
      ry: 0.13,
      color: "#4ecfff",
      alpha: 0.11
    },
    {
      x: -0.05,
      y: 0.52,
      rx: 0.48,
      ry: 0.1,
      color: "#fff0ad",
      alpha: 0.032
    },
    {
      x: 0.08,
      y: -0.02,
      rx: 0.3,
      ry: 0.18,
      color: "#83f7ff",
      alpha: state.mode === "speaking" ? 0.16 : 0.075
    },
    {
      x: -0.24,
      y: -0.08,
      rx: 0.24,
      ry: 0.34,
      color: "#93ffe7",
      alpha: 0.055 + activity * 0.07
    },
    {
      x: 0.28,
      y: 0.1,
      rx: 0.22,
      ry: 0.3,
      color: "#74d8ff",
      alpha: 0.05 + activity * 0.06
    }
  ];

  ctx.save();
  ctx.globalCompositeOperation = "screen";
  pools.forEach((pool, index) => {
    const drift = Math.sin(time * (0.38 + activity * 0.16) + index) * radius * (0.025 + activity * 0.025);
    const gradient = ctx.createRadialGradient(
      cx + radius * pool.x + drift,
      cy + radius * pool.y,
      radius * 0.02,
      cx + radius * pool.x + drift,
      cy + radius * pool.y,
      radius * pool.rx
    );
    gradient.addColorStop(0, rgba(pool.color, pool.alpha + energy * 0.026 + activity * 0.035));
    gradient.addColorStop(0.48, rgba(pool.color, pool.alpha * 0.42));
    gradient.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = gradient;
    ctx.beginPath();
    ctx.ellipse(
      cx + radius * pool.x + drift,
      cy + radius * pool.y,
      radius * pool.rx,
      radius * pool.ry,
      -0.16 + Math.sin(time * 0.2 + index) * 0.06,
      0,
      Math.PI * 2
    );
    ctx.fill();
  });
  ctx.restore();

  ctx.save();
  ctx.globalCompositeOperation = "multiply";
  ctx.filter = `blur(${radius * 0.012}px)`;
  const innerDepth = ctx.createRadialGradient(
    cx + radius * 0.18,
    cy + radius * 0.1,
    radius * 0.04,
    cx + radius * 0.08,
    cy,
    radius * 0.66
  );
  innerDepth.addColorStop(0, "rgba(15, 91, 112, 0.075)");
  innerDepth.addColorStop(0.5, "rgba(28, 118, 130, 0.035)");
  innerDepth.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = innerDepth;
  ctx.beginPath();
  ctx.ellipse(
    cx + radius * 0.1 + Math.sin(time * 0.21) * radius * 0.03,
    cy + radius * 0.08,
    radius * 0.58,
    radius * 0.42,
    -0.18,
    0,
    Math.PI * 2
  );
  ctx.fill();
  ctx.restore();

  ctx.save();
  ctx.globalCompositeOperation = "screen";
  ctx.lineCap = "round";
  ctx.lineWidth = 1.05;
  for (let i = 0; i < 7; i += 1) {
    const y = cy + radius * (0.16 + i * 0.045);
    ctx.strokeStyle = i % 2 === 0
      ? rgba("#d7fffb", 0.1)
      : rgba("#fff2ab", 0.035);
    ctx.beginPath();
    for (let x = cx - radius * 0.58; x <= cx + radius * 0.58; x += 12) {
      const n = (x - cx) / radius;
      const curve = Math.sin(n * 6.5 + time * 0.65 + i) * radius * 0.024;
      const lens = (1 - Math.abs(n)) * radius * 0.08;
      const yy = y + curve - lens * Math.sin(i * 0.7 + time * 0.18);
      if (x === cx - radius * 0.58) {
        ctx.moveTo(x, yy);
      } else {
        ctx.lineTo(x, yy);
      }
    }
    ctx.globalAlpha = 0.22;
    ctx.stroke();
  }
  ctx.restore();
}

function drawAtmosphericBubbles(width, height, cx, cy, radius, palette, time, energy) {
  ctx.save();
  ctx.globalCompositeOperation = "screen";
  for (let i = 0; i < 24; i += 1) {
    const lane = i % 6;
    const side = lane % 2 === 0 ? -1 : 1;
    const phase = (time * (0.018 + lane * 0.002) + ((i * 17) % 100) / 100) % 1;
    const orbitOffset = radius * (1.08 + lane * 0.13);
    const verticalRange = height * 0.92;
    const baseY = height * 0.96 - phase * verticalRange;
    const sway = Math.sin(time * 0.26 + i * 1.9) * radius * (0.06 + lane * 0.012);
    const x = cx + side * orbitOffset + sway + Math.sin(i * 2.1) * radius * 0.12;
    const y = baseY + Math.cos(time * 0.2 + i) * radius * 0.025;
    const distance = Math.hypot(x - cx, y - cy);

    if (distance < radius * 1.02 || x < -40 || x > width + 40) {
      continue;
    }

    const size = radius * (0.012 + ((i * 13) % 9) / 420);
    const fadeTop = Math.min(1, Math.max(0, y / (height * 0.22)));
    const fadeBottom = Math.min(1, Math.max(0, (height - y) / (height * 0.18)));
    const alpha = fadeTop * fadeBottom * (0.26 + energy * 0.14);

    ctx.shadowColor = rgba(palette.primary, 0.2);
    ctx.shadowBlur = 7 * state.bloom;
    const bubble = ctx.createRadialGradient(
      x - size * 0.35,
      y - size * 0.35,
      size * 0.1,
      x,
      y,
      size
    );
    bubble.addColorStop(0, `rgba(255,255,255,${0.55 * alpha})`);
    bubble.addColorStop(0.28, rgba(palette.primary, alpha * 0.38));
    bubble.addColorStop(0.66, `rgba(255,255,255,${0.09 * alpha})`);
    bubble.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = bubble;
    ctx.beginPath();
    ctx.arc(x, y, size, 0, Math.PI * 2);
    ctx.fill();

    ctx.strokeStyle = `rgba(255,255,255,${0.24 * alpha})`;
    ctx.lineWidth = 0.7;
    ctx.beginPath();
    ctx.arc(x, y, size * 0.82, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.restore();
}

function drawLivingCore(cx, cy, radius, palette, time, energy) {
  const activity = activeEnergy(time, energy);

  ctx.save();
  ctx.globalCompositeOperation = "screen";
  ctx.filter = `blur(${radius * 0.006}px)`;

  for (let i = 0; i < 9; i += 1) {
    const phase = time * (0.44 + activity * 0.5) + i * 0.72;
    const x = cx + Math.sin(phase * 0.8) * radius * (0.18 + i * 0.018);
    const y = cy + Math.cos(phase * 0.7 + i) * radius * (0.18 + i * 0.014);
    const rx = radius * (0.16 + ((i * 13) % 7) * 0.018 + activity * 0.07);
    const ry = radius * (0.04 + ((i * 11) % 5) * 0.013 + activity * 0.018);
    const color = i % 3 === 0 ? "#ffffff" : i % 3 === 1 ? "#79fff0" : "#82d7ff";
    const alpha = 0.028 + activity * 0.075;
    const flow = ctx.createRadialGradient(x, y, radius * 0.02, x, y, rx);
    flow.addColorStop(0, rgba(color, alpha));
    flow.addColorStop(0.42, rgba(color, alpha * 0.42));
    flow.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = flow;
    ctx.beginPath();
    ctx.ellipse(x, y, rx, ry, phase * 0.28, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.filter = "none";
  ctx.lineCap = "round";
  for (let i = 0; i < 16; i += 1) {
    const phase = time * (1.1 + activity * 1.4) + i * 0.55;
    const y = cy + radius * (-0.36 + i * 0.047);
    const width = radius * (0.42 + Math.sin(phase) * 0.08);
    const alpha = 0.018 + activity * 0.075;
    const line = ctx.createLinearGradient(cx - width, y, cx + width, y);
    line.addColorStop(0, "rgba(255,255,255,0)");
    line.addColorStop(0.28, rgba("#dffffc", alpha * 0.65));
    line.addColorStop(0.5, rgba("#ffffff", alpha));
    line.addColorStop(0.72, rgba(palette.secondary, alpha * 0.55));
    line.addColorStop(1, "rgba(255,255,255,0)");
    ctx.strokeStyle = line;
    ctx.lineWidth = 0.55 + activity * 0.55;
    ctx.beginPath();
    ctx.moveTo(cx - width, y);
    ctx.bezierCurveTo(
      cx - width * 0.32,
      y + Math.sin(phase) * radius * 0.035,
      cx + width * 0.28,
      y - Math.cos(phase * 0.8) * radius * 0.035,
      cx + width,
      y + Math.sin(phase * 0.6) * radius * 0.018
    );
    ctx.stroke();
  }

  ctx.restore();
}

function drawNervePlexus(cx, cy, radius, palette, time, energy) {
  const activity = activeEnergy(time, energy);
  const cadence = 1.18 + activity * 0.65;
  const beatA = Math.pow(Math.max(0, Math.sin(time * cadence * Math.PI)), 12);
  const beatB = Math.pow(Math.max(0, Math.sin((time - 0.17) * cadence * Math.PI)), 16) * 0.46;
  const heartbeat = beatA + beatB;

  ctx.save();
  ctx.globalCompositeOperation = "screen";
  ctx.lineCap = "round";

  for (let i = 0; i < 14; i += 1) {
    const angle = (i / 14) * Math.PI * 2 + Math.sin(time * 0.16 + i) * 0.05;
    const innerX = cx + Math.cos(angle + 0.24) * radius * 0.16;
    const innerY = cy + Math.sin(angle + 0.24) * radius * 0.12;
    const outerX = cx + Math.cos(angle) * radius * (0.61 + (i % 3) * 0.07);
    const outerY = cy + Math.sin(angle) * radius * (0.48 + (i % 4) * 0.045);
    const pulse = 0.5 + 0.5 * Math.sin(time * (1.5 + activity) - i * 0.58);
    ctx.strokeStyle = rgba(
      i % 3 === 0 ? "#9affd2" : palette.secondary,
      0.035 + pulse * 0.07 + heartbeat * 0.05
    );
    ctx.lineWidth = 0.55 + pulse * 0.72;
    ctx.beginPath();
    ctx.moveTo(innerX, innerY);
    ctx.bezierCurveTo(
      cx + Math.cos(angle + 0.72) * radius * 0.34,
      cy + Math.sin(angle + 0.72) * radius * 0.28,
      cx + Math.cos(angle - 0.42) * radius * 0.5,
      cy + Math.sin(angle - 0.42) * radius * 0.4,
      outerX,
      outerY
    );
    ctx.stroke();

    const flow = (time * (0.2 + activity * 0.3) + i * 0.071) % 1;
    const nodeX = innerX + (outerX - innerX) * flow;
    const nodeY = innerY + (outerY - innerY) * flow;
    ctx.fillStyle = rgba("#dffff2", 0.14 + pulse * 0.22);
    ctx.beginPath();
    ctx.arc(nodeX, nodeY, 0.8 + heartbeat * 1.2, 0, Math.PI * 2);
    ctx.fill();
  }

  const sac = ctx.createRadialGradient(cx - radius * 0.025, cy - radius * 0.035, 0, cx, cy, radius * 0.23);
  sac.addColorStop(0, rgba("#ffffff", 0.42 + heartbeat * 0.2));
  sac.addColorStop(0.28, rgba("#9affd2", 0.2 + activity * 0.16));
  sac.addColorStop(0.7, rgba(palette.secondary, 0.08 + heartbeat * 0.08));
  sac.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = sac;
  ctx.beginPath();
  ctx.ellipse(
    cx, cy,
    radius * (0.18 + heartbeat * 0.018),
    radius * (0.14 + heartbeat * 0.025),
    Math.sin(time * 0.2) * 0.08,
    0, Math.PI * 2
  );
  ctx.fill();
  ctx.restore();
}

function drawEdgeOcclusion(cx, cy, radius, palette, time, energy, wobble) {
  const activity = activeEnergy(time, energy);

  ctx.save();
  drawBlobPath(cx, cy, radius * 0.985, time, energy, wobble);
  ctx.clip();
  ctx.globalCompositeOperation = "multiply";
  ctx.filter = `blur(${radius * 0.01}px)`;
  const edge = ctx.createRadialGradient(cx, cy - radius * 0.08, radius * 0.46, cx, cy, radius * 1.02);
  edge.addColorStop(0, "rgba(255,255,255,0)");
  edge.addColorStop(0.66, "rgba(255,255,255,0)");
  edge.addColorStop(0.88, `rgba(30, 102, 122, ${0.055 + activity * 0.02})`);
  edge.addColorStop(1, `rgba(8, 45, 57, ${0.13 + activity * 0.025})`);
  ctx.fillStyle = edge;
  ctx.beginPath();
  ctx.arc(cx, cy, radius * 1.08, 0, Math.PI * 2);
  ctx.fill();

  const lower = ctx.createRadialGradient(cx, cy + radius * 0.56, radius * 0.04, cx, cy + radius * 0.54, radius * 0.62);
  lower.addColorStop(0, `rgba(20, 78, 92, ${0.075 + activity * 0.035})`);
  lower.addColorStop(0.62, "rgba(50, 120, 130, 0.028)");
  lower.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = lower;
  ctx.beginPath();
  ctx.ellipse(cx, cy + radius * 0.52, radius * 0.72, radius * 0.19, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function drawPhysicalShadows(cx, cy, radius, palette, time, energy) {
  const baseY = cy + radius * 1.08;
  const voice = voiceIntensity(time, energy);

  ctx.save();
  ctx.globalCompositeOperation = "multiply";
  ctx.filter = `blur(${radius * 0.035}px)`;

  const ground = ctx.createRadialGradient(
    cx - radius * 0.08,
    baseY + radius * 0.16,
    radius * 0.12,
    cx,
    baseY + radius * 0.16,
    radius * 1.2
  );
  ground.addColorStop(0, `rgba(27, 67, 78, ${0.12 + voice * 0.025})`);
  ground.addColorStop(0.45, "rgba(38, 94, 106, 0.052)");
  ground.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = ground;
  ctx.beginPath();
  ctx.ellipse(
    cx,
    baseY + radius * 0.15,
    radius * (1.08 + voice * 0.06),
    radius * (0.25 + voice * 0.025),
    -0.03,
    0,
    Math.PI * 2
  );
  ctx.fill();

  ctx.filter = `blur(${radius * 0.014}px)`;
  const contact = ctx.createRadialGradient(cx, baseY + radius * 0.03, 0, cx, baseY + radius * 0.03, radius * 0.62);
  contact.addColorStop(0, `rgba(10, 41, 51, ${0.15 + voice * 0.035})`);
  contact.addColorStop(0.48, "rgba(30, 78, 88, 0.055)");
  contact.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = contact;
  ctx.beginPath();
  ctx.ellipse(
    cx,
    baseY + radius * 0.03,
    radius * (0.56 + voice * 0.045),
    radius * 0.09,
    0,
    0,
    Math.PI * 2
  );
  ctx.fill();

  ctx.restore();

  ctx.save();
  ctx.globalCompositeOperation = "screen";
  const reflected = ctx.createRadialGradient(cx, baseY - radius * 0.05, radius * 0.06, cx, baseY, radius * 0.95);
  reflected.addColorStop(0, rgba("#ffffff", 0.07 + voice * 0.025));
  reflected.addColorStop(0.46, rgba(palette.secondary, 0.055 + voice * 0.02));
  reflected.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = reflected;
  ctx.beginPath();
  ctx.ellipse(cx, baseY, radius * 0.92, radius * 0.18, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function drawGlassBody(cx, cy, radius, palette, time, energy) {
  const baseY = cy + radius * 1.02;
  const pulse = Math.sin(time * 1.1) * palettes[state.mode].pulse;
  const voice = voiceIntensity(time, energy);
  const activity = activeEnergy(time, energy);

  ctx.save();
  ctx.globalCompositeOperation = "screen";

  const cast = ctx.createRadialGradient(cx, baseY, radius * 0.18, cx, baseY, radius * 1.52);
  cast.addColorStop(0, rgba(palette.secondary, 0.1 + energy * 0.03 + voice * 0.035));
  cast.addColorStop(0.45, rgba("#ffffff", 0.05 + voice * 0.018));
  cast.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = cast;
  ctx.beginPath();
  ctx.ellipse(
    cx,
    baseY + radius * 0.15,
    radius * (1.38 + voice * 0.08),
    radius * (0.32 + voice * 0.025),
    0,
    0,
    Math.PI * 2
  );
  ctx.fill();

  const stem = ctx.createLinearGradient(cx, cy + radius * 0.46, cx, baseY + radius * 0.08);
  stem.addColorStop(0, "rgba(255,255,255,0)");
  stem.addColorStop(0.34, rgba(palette.primary, 0.06 + energy * 0.02 + activity * 0.055));
  stem.addColorStop(0.72, rgba(palette.secondary, 0.075 + activity * 0.045));
  stem.addColorStop(1, "rgba(255,255,255,0.02)");
  ctx.fillStyle = stem;
  ctx.beginPath();
  ctx.moveTo(cx - radius * 0.42, cy + radius * 0.5);
  ctx.bezierCurveTo(
    cx - radius * 0.28,
    cy + radius * 0.82,
    cx - radius * 0.5,
    baseY,
    cx - radius * 0.82,
    baseY + radius * 0.08
  );
  ctx.quadraticCurveTo(cx, baseY + radius * 0.3, cx + radius * 0.82, baseY + radius * 0.08);
  ctx.bezierCurveTo(
    cx + radius * 0.5,
    baseY,
    cx + radius * 0.28,
    cy + radius * 0.82,
    cx + radius * 0.42,
    cy + radius * 0.5
  );
  ctx.quadraticCurveTo(cx, cy + radius * 0.66, cx - radius * 0.42, cy + radius * 0.5);
  ctx.fill();

  for (let i = 0; i < 8; i += 1) {
    const phase = time * (1.0 + activity * 1.6) + i * 0.8;
    const offset = (i - 3.5) * radius * 0.075;
    const current = ctx.createLinearGradient(cx + offset, cy + radius * 0.42, cx + offset, baseY + radius * 0.2);
    current.addColorStop(0, "rgba(255,255,255,0)");
    current.addColorStop(0.42, rgba(i % 2 === 0 ? "#ffffff" : palette.secondary, 0.025 + activity * 0.08));
    current.addColorStop(1, "rgba(255,255,255,0)");
    ctx.strokeStyle = current;
    ctx.lineWidth = 0.75 + activity * 0.65;
    ctx.beginPath();
    ctx.moveTo(cx + offset, cy + radius * 0.5);
    ctx.bezierCurveTo(
      cx + offset + Math.sin(phase) * radius * 0.12,
      cy + radius * 0.7,
      cx + offset - Math.cos(phase * 0.7) * radius * 0.14,
      baseY - radius * 0.03,
      cx + offset + Math.sin(phase * 0.6) * radius * 0.08,
      baseY + radius * 0.17
    );
    ctx.stroke();
  }

  ctx.lineCap = "round";
  ctx.strokeStyle = rgba("#ffffff", 0.2);
  ctx.lineWidth = 1.1;
  ctx.beginPath();
  ctx.ellipse(cx, baseY + radius * 0.04, radius * 0.9, radius * 0.13, 0, 0, Math.PI * 2);
  ctx.stroke();

  const meniscus = ctx.createLinearGradient(cx - radius, baseY, cx + radius, baseY);
  meniscus.addColorStop(0, "rgba(255,255,255,0)");
  meniscus.addColorStop(0.28, rgba(palette.secondary, 0.11));
  meniscus.addColorStop(0.5, "rgba(255,255,255,0.22)");
  meniscus.addColorStop(0.72, rgba(palette.primary, 0.1));
  meniscus.addColorStop(1, "rgba(255,255,255,0)");
  ctx.strokeStyle = meniscus;
  ctx.lineWidth = 2.2;
  ctx.beginPath();
  ctx.ellipse(
    cx,
    baseY + Math.sin(time * 0.48) * radius * 0.012,
    radius * (0.78 + pulse * 0.02 + activity * 0.09),
    radius * (0.105 + activity * 0.032),
    0,
    0,
    Math.PI * 2
  );
  ctx.stroke();

  for (let i = 0; i < 3; i += 1) {
    ctx.globalAlpha = 0.08 - i * 0.016 + activity * 0.025;
    ctx.strokeStyle = i % 2 === 0 ? rgba(palette.primary, 0.55) : rgba(palette.secondary, 0.55);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.ellipse(
      cx,
      baseY + radius * (0.04 + i * 0.07),
      radius * (0.62 + i * 0.24 + pulse * 0.03),
      radius * (0.08 + i * 0.026),
      0,
      0,
      Math.PI * 2
    );
    ctx.stroke();
  }

  ctx.restore();
}

function drawFrostedSparkle(cx, cy, radius, palette, time, energy) {
  ctx.save();
  ctx.globalCompositeOperation = "screen";
  ctx.fillStyle = "rgba(255,255,255,0.24)";
  ctx.shadowColor = rgba(palette.primary, 0.26);
  ctx.shadowBlur = 4 * state.bloom;

  for (let i = 0; i < 48; i += 1) {
    const angle = -Math.PI * 0.9 + (i / 48) * Math.PI * 0.78;
    const band = radius * (0.7 + (((i * 19) % 100) / 100) * 0.14);
    const jitter = (seededWave(i, time, 0.08) - 0.5) * radius * 0.014;
    const x = cx + Math.cos(angle) * (band + jitter);
    const y = cy + Math.sin(angle) * (band * 0.74 + jitter) - radius * 0.05;
    const twinkle = 0.18 + Math.abs(Math.sin(time * 0.8 + i * 0.9)) * 0.22;
    ctx.globalAlpha = twinkle * (0.5 + energy * 0.16);
    ctx.beginPath();
    ctx.arc(x, y, 0.55 + ((i * 7) % 5) * 0.16, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}

function drawGlassRim(cx, cy, radius, palette, time, energy, wobble) {
  ctx.save();
  drawBlobPath(cx, cy, radius, time, energy, wobble);
  ctx.lineWidth = 0.55;
  ctx.strokeStyle = "rgba(255,255,255,0.13)";
  ctx.shadowColor = rgba(palette.primary, 0.28);
  ctx.shadowBlur = 7 * state.bloom;
  ctx.stroke();

  ctx.globalCompositeOperation = "screen";
  ctx.lineCap = "round";
  ctx.lineWidth = 1.45;
  ctx.strokeStyle = rgba("#ffffff", 0.58);
  ctx.beginPath();
  ctx.ellipse(cx, cy, radius * 1.015, radius * 0.985, 0, Math.PI * 1.08, Math.PI * 1.62);
  ctx.stroke();
  ctx.lineWidth = 0.95;
  ctx.strokeStyle = "rgba(255,255,255,0.4)";
  ctx.beginPath();
  ctx.ellipse(cx, cy, radius * 1.01, radius * 0.98, 0, Math.PI * 0.46, Math.PI * 0.75);
  ctx.stroke();
  ctx.lineWidth = 0.8;
  ctx.strokeStyle = rgba(palette.secondary, 0.24);
  ctx.beginPath();
  ctx.ellipse(cx, cy, radius * 1.012, radius * 0.984, 0, Math.PI * 1.88, Math.PI * 2.16);
  ctx.stroke();
  ctx.restore();
}

function drawBlobSpecular(cx, cy, radius, palette, time, energy) {
  ctx.save();
  ctx.globalCompositeOperation = "screen";
  ctx.shadowColor = "rgba(255,255,255,0.42)";
  ctx.shadowBlur = 22 * state.bloom;
  ctx.fillStyle = "rgba(255,255,255,0.18)";
  ctx.beginPath();
  ctx.ellipse(
    cx - radius * 0.31 + Math.sin(time * 0.7) * radius * 0.025,
    cy - radius * 0.42,
    radius * 0.35,
    radius * 0.056,
    -0.48,
    0,
    Math.PI * 2
  );
  ctx.fill();

  ctx.fillStyle = "rgba(255,255,255,0.095)";
  ctx.beginPath();
  ctx.ellipse(
    cx - radius * 0.46,
    cy - radius * 0.18,
    radius * 0.12,
    radius * 0.035,
    -1.1,
    0,
    Math.PI * 2
  );
  ctx.fill();

  ctx.fillStyle = rgba(palette.accent, 0.065 + energy * 0.026);
  ctx.beginPath();
  ctx.ellipse(
    cx + radius * 0.28,
    cy + radius * 0.28,
    radius * 0.2,
    radius * 0.052,
    -0.42,
    0,
    Math.PI * 2
  );
  ctx.fill();

  ctx.fillStyle = "rgba(255,255,255,0.64)";
  ctx.shadowBlur = 11 * state.bloom;
  ctx.beginPath();
  ctx.ellipse(
    cx - radius * 0.48,
    cy - radius * 0.5,
    radius * 0.035,
    radius * 0.012,
    -0.55,
    0,
    Math.PI * 2
  );
  ctx.fill();

  for (let i = 0; i < 5; i += 1) {
    const angle = Math.PI * (1.1 + i * 0.19) + Math.sin(time * 0.35 + i) * 0.025;
    const x = cx + Math.cos(angle) * radius * 0.99;
    const y = cy + Math.sin(angle) * radius * 0.96;
    ctx.fillStyle = `rgba(255,255,255,${0.22 + i * 0.035})`;
    ctx.shadowBlur = 8 * state.bloom;
    ctx.beginPath();
    ctx.ellipse(x, y, radius * 0.018, radius * 0.0045, angle + Math.PI * 0.5, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}

function drawGlassCaustics(cx, cy, radius, palette, time, energy) {
  ctx.save();
  ctx.globalCompositeOperation = "screen";
  ctx.lineCap = "round";
  ctx.lineWidth = 0.9;
  ctx.strokeStyle = rgba(palette.primary, 0.06 + energy * 0.035);
  ctx.shadowColor = rgba(palette.primary, 0.22);
  ctx.shadowBlur = 10 * state.bloom;

  for (let i = 0; i < 7; i += 1) {
    const y = cy - radius * 0.38 + i * radius * 0.13;
    const sway = Math.sin(time * 0.65 + i * 0.7) * radius * 0.06;
    ctx.beginPath();
    for (let x = cx - radius * 0.55; x <= cx + radius * 0.55; x += 16) {
      const n = (x - cx) / radius;
      const wave = Math.sin(n * 5 + time * 0.9 + i) * radius * 0.018;
      const yy = y + wave + sway * (1 - Math.abs(n));
      if (x === cx - radius * 0.55) {
        ctx.moveTo(x, yy);
      } else {
        ctx.lineTo(x, yy);
      }
    }
    ctx.globalAlpha = 0.07 - i * 0.006;
    ctx.stroke();
  }
  ctx.restore();
}

function drawGlassHalo(cx, cy, radius, palette, time, energy) {
  const pulse = Math.sin(time * 1.4) * palettes[state.mode].pulse;
  const glow = radius * (1.03 + pulse * 0.018);

  ctx.save();
  ctx.shadowColor = rgba(palette.secondary, 0.55 * state.bloom);
  ctx.shadowBlur = 66 * state.bloom;
  const outer = ctx.createRadialGradient(cx, cy, radius * 0.2, cx, cy, glow);
  outer.addColorStop(0, rgba("#ffffff", 0.08 + energy * 0.06));
  outer.addColorStop(0.58, rgba(palette.secondary, 0.14));
  outer.addColorStop(0.78, rgba(palette.primary, 0.045));
  outer.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = outer;
  ctx.beginPath();
  ctx.arc(cx, cy, glow, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();

  for (let i = 0; i < 4; i += 1) {
    ctx.save();
    ctx.globalAlpha = 0.048 - i * 0.007;
    ctx.strokeStyle = i % 2 === 0 ? palette.primary : palette.secondary;
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.arc(cx, cy, radius * (0.72 + i * 0.11 + pulse * 0.008), 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }
}

function drawSegmentedRing(cx, cy, radius, palette, time, offset, segments, width, alpha) {
  ctx.save();
  ctx.lineCap = "round";
  ctx.lineWidth = width;
  ctx.strokeStyle = rgba(palette.primary, alpha);
  ctx.shadowColor = rgba(palette.secondary, alpha * 0.48);
  ctx.shadowBlur = 12 * state.bloom;

  for (let i = 0; i < segments; i += 1) {
    const startAngle = offset + (Math.PI * 2 * i) / segments;
    const length = Math.PI * (0.18 + 0.05 * Math.sin(time * 0.9 + i));
    ctx.beginPath();
    ctx.arc(cx, cy, radius, startAngle, startAngle + length);
    ctx.stroke();
  }
  ctx.restore();
}

function drawIris(cx, cy, radius, palette, time, energy) {
  const speed = palette.rotation;
  const innerPulse = 1 + Math.sin(time * 1.8) * 0.015 * energy;

  drawSegmentedRing(cx, cy, radius * 0.68 * innerPulse, palette, time, time * speed, 10, 1.05, 0.105);
  drawSegmentedRing(cx, cy, radius * 0.48, palette, time, -time * speed * 1.4, 8, 0.9, 0.085);
  drawSegmentedRing(cx, cy, radius * 0.31, palette, time, time * speed * 1.9, 6, 0.75, 0.07);

  const core = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius * 0.32);
  core.addColorStop(0, rgba(palette.accent, 0.32 + energy * 0.08));
  core.addColorStop(0.24, rgba(palette.primary, 0.12));
  core.addColorStop(0.64, rgba(palette.secondary, 0.045));
  core.addColorStop(1, "rgba(255,255,255,0)");
  ctx.save();
  ctx.shadowColor = rgba(palette.accent, 0.28 * state.bloom);
  ctx.shadowBlur = 24 * state.bloom;
  ctx.fillStyle = core;
  ctx.beginPath();
  ctx.arc(cx, cy, radius * 0.34, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function drawRipples(cx, cy, radius, palette, time, energy) {
  if (state.mode !== "listening" && state.mode !== "waiting_confirmation") {
    return;
  }

  const warm = state.mode === "waiting_confirmation";
  ctx.save();
  ctx.strokeStyle = rgba(warm ? "#ffe2a3" : palette.primary, 0.22);
  ctx.lineWidth = 1.25;
  for (let i = 0; i < 5; i += 1) {
    const phase = (time * 0.52 + i * 0.19) % 1;
    const r = radius * (0.55 + phase * 0.65);
    ctx.globalAlpha = (1 - phase) * (0.2 + energy * 0.12);
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.restore();
}

function drawSpeakingWave(cx, cy, radius, palette, time, energy) {
  if (state.mode !== "speaking") {
    return;
  }

  const voice = voiceIntensity(time, energy);

  ctx.save();
  ctx.globalCompositeOperation = "screen";
  ctx.lineWidth = 1.3 + voice * 0.55;
  ctx.strokeStyle = rgba(palette.primary, 0.26 + voice * 0.18);
  ctx.shadowColor = rgba(palette.accent, 0.24 + voice * 0.12);
  ctx.shadowBlur = (12 + voice * 12) * state.bloom;

  for (let band = -4; band <= 4; band += 1) {
    ctx.beginPath();
    const yBase = cy + band * radius * 0.068;
    for (let x = cx - radius * 0.68; x <= cx + radius * 0.68; x += 6) {
      const local = (x - cx) / radius;
      const envelope = Math.max(0, 1 - Math.abs(local));
      const y =
        yBase
        + Math.sin(time * 8.7 + local * 9.4 + band) * radius * (0.02 + voice * 0.025) * energy * envelope
        + Math.sin(time * 15.5 + local * 4.1) * radius * 0.005 * voice;
      if (x === cx - radius * 0.68) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    }
    ctx.globalAlpha = 0.055 + Math.abs(band) * 0.01 + voice * 0.05;
    ctx.stroke();
  }

  for (let i = 0; i < 14; i += 1) {
    const phase = (time * (0.76 + voice * 0.32) + i * 0.071) % 1;
    const y = cy + radius * (0.18 + phase * 0.98);
    const width = radius * (0.34 + voice * 0.15 + Math.sin(time * 1.2 + i) * 0.035);
    const alpha = (1 - phase) * (0.08 + energy * 0.038 + voice * 0.095);
    const gradient = ctx.createLinearGradient(cx - width, y, cx + width, y);
    gradient.addColorStop(0, "rgba(255,255,255,0)");
    gradient.addColorStop(0.4, rgba("#dffcff", alpha * 0.65));
    gradient.addColorStop(0.52, rgba("#ffffff", alpha));
    gradient.addColorStop(0.64, rgba(palette.secondary, alpha * 0.55));
    gradient.addColorStop(1, "rgba(255,255,255,0)");
    ctx.strokeStyle = gradient;
    ctx.lineWidth = 0.75 + voice * 0.38;
    ctx.beginPath();
    ctx.ellipse(
      cx + Math.sin(time * 1.4 + i) * radius * 0.02,
      y,
      width,
      radius * (0.032 + voice * 0.018),
      Math.sin(time * 0.32 + i) * 0.08,
      0,
      Math.PI * 2
    );
    ctx.stroke();
  }

  for (let i = 0; i < 10; i += 1) {
    const offset = (i - 4.5) * radius * 0.075;
    const phase = time * (2.0 + voice * 1.2) + i * 0.52;
    const height = radius * (0.82 + Math.sin(phase) * 0.1);
    const alpha = 0.018 + voice * 0.08;
    const ribbon = ctx.createLinearGradient(cx + offset, cy - height * 0.55, cx + offset, cy + radius * 1.08);
    ribbon.addColorStop(0, "rgba(255,255,255,0)");
    ribbon.addColorStop(0.24, rgba("#ffffff", alpha * 0.6));
    ribbon.addColorStop(0.46, rgba("#dffcff", alpha));
    ribbon.addColorStop(0.72, rgba(palette.secondary, alpha * 0.82));
    ribbon.addColorStop(1, "rgba(255,255,255,0)");
    ctx.strokeStyle = ribbon;
    ctx.lineWidth = 0.65 + voice * 0.9;
    ctx.beginPath();
    ctx.moveTo(cx + offset, cy - height * 0.45);
    ctx.bezierCurveTo(
      cx + offset + Math.sin(phase) * radius * 0.12,
      cy - height * 0.12,
      cx + offset - Math.cos(phase * 0.8) * radius * 0.1,
      cy + radius * 0.42,
      cx + offset + Math.sin(phase * 0.7) * radius * 0.04,
      cy + radius * 1.08
    );
    ctx.stroke();
  }

  for (let i = 0; i < 18; i += 1) {
    const phase = time * (1.4 + i * 0.018) + i * 0.9;
    const angle = phase % (Math.PI * 2);
    const orbit = radius * (0.46 + ((i * 17) % 30) / 100);
    const x = cx + Math.cos(angle) * orbit;
    const y = cy + Math.sin(angle * 1.2) * orbit * 0.82;
    const alpha = (0.04 + voice * 0.12) * (0.55 + Math.sin(phase * 1.7) * 0.25);
    ctx.fillStyle = rgba(i % 3 === 0 ? "#ffffff" : palette.secondary, alpha);
    ctx.shadowColor = rgba(palette.secondary, alpha);
    ctx.shadowBlur = (8 + voice * 10) * state.bloom;
    ctx.beginPath();
    ctx.ellipse(x, y, radius * 0.011, radius * 0.0035, angle, 0, Math.PI * 2);
    ctx.fill();
  }

  for (let i = 0; i < 24; i += 1) {
    const phase = time * (2.8 + voice * 2.4) + i * 0.33;
    const angle = (i / 24) * Math.PI * 2 + Math.sin(phase * 0.22) * 0.14;
    const inner = radius * (0.28 + ((i * 19) % 40) / 100);
    const outer = inner + radius * (0.16 + voice * 0.1);
    const sx = cx + Math.cos(angle) * inner;
    const sy = cy + Math.sin(angle * 1.08) * inner * 0.88;
    const ex = cx + Math.cos(angle + Math.sin(phase) * 0.12) * outer;
    const ey = cy + Math.sin((angle + Math.cos(phase) * 0.08) * 1.08) * outer * 0.88;
    const alpha = 0.018 + voice * 0.085;
    const spark = ctx.createLinearGradient(sx, sy, ex, ey);
    spark.addColorStop(0, "rgba(255,255,255,0)");
    spark.addColorStop(0.5, rgba(i % 4 === 0 ? "#ffffff" : palette.secondary, alpha));
    spark.addColorStop(1, "rgba(255,255,255,0)");
    ctx.strokeStyle = spark;
    ctx.lineWidth = 0.55 + voice * 0.7;
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.lineTo(ex, ey);
    ctx.stroke();
  }
  ctx.restore();
}

function drawConstellation(cx, cy, radius, palette, time, energy) {
  if (state.mode !== "autonomous_goal") {
    return;
  }

  const points = 12;
  const positions = [];
  for (let i = 0; i < points; i += 1) {
    const angle = time * 0.12 + i * 2.399;
    const r = radius * (0.28 + ((i * 37) % 55) / 100);
    positions.push({
      x: cx + Math.cos(angle) * r,
      y: cy + Math.sin(angle * 1.13) * r * 0.76
    });
  }

  ctx.save();
  ctx.strokeStyle = rgba(palette.secondary, 0.16);
  ctx.fillStyle = rgba(palette.accent, 0.54);
  ctx.shadowColor = rgba(palette.secondary, 0.3);
  ctx.shadowBlur = 12 * state.bloom;
  for (let i = 0; i < positions.length; i += 1) {
    const a = positions[i];
    const b = positions[(i + 3) % positions.length];
    ctx.globalAlpha = 0.12 + energy * 0.08;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
    ctx.globalAlpha = 0.48;
    ctx.beginPath();
    ctx.arc(a.x, a.y, 2.1, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}

function drawSignalPoints(cx, cy, radius, palette, time, energy) {
  const count = Math.round(4 + energy * 5);
  ctx.save();
  ctx.fillStyle = rgba(palette.accent, 0.5);
  ctx.shadowColor = rgba(palette.accent, 0.34);
  ctx.shadowBlur = 10 * state.bloom;
  for (let i = 0; i < count; i += 1) {
    const angle = time * (0.18 + i * 0.006) + (Math.PI * 2 * i) / count;
    const orbit = radius * (0.86 + (i % 3) * 0.035);
    const x = cx + Math.cos(angle) * orbit;
    const y = cy + Math.sin(angle) * orbit;
    const size = 1.15 + (i % 4) * 0.32;
    ctx.globalAlpha = 0.22 + energy * 0.28;
    ctx.beginPath();
    ctx.arc(x, y, size, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}

function drawFocusedSweep(cx, cy, radius, palette, time) {
  if (state.mode !== "acting" && state.mode !== "service_issue") {
    return;
  }

  const angle = time * (state.mode === "acting" ? 1.2 : 0.45);
  ctx.save();
  ctx.globalCompositeOperation = "screen";
  ctx.lineCap = "round";
  ctx.shadowColor = rgba(palette.secondary, 0.25);
  ctx.shadowBlur = 16 * state.bloom;

  for (let i = 0; i < 3; i += 1) {
    ctx.strokeStyle = rgba(palette.secondary, 0.12 - i * 0.02);
    ctx.lineWidth = 1.2 - i * 0.2;
    ctx.beginPath();
    ctx.ellipse(
      cx,
      cy + radius * (0.02 + i * 0.06),
      radius * (0.8 + i * 0.08),
      radius * (0.32 + i * 0.06),
      Math.sin(time * 0.2) * 0.06,
      angle + i * 0.22,
      angle + Math.PI * 0.56 + i * 0.22
    );
    ctx.stroke();
  }

  const sheen = ctx.createLinearGradient(
    cx - radius * 0.42,
    cy - radius * 0.46,
    cx + radius * 0.48,
    cy + radius * 0.36
  );
  sheen.addColorStop(0, "rgba(255,255,255,0)");
  sheen.addColorStop(0.5, rgba(palette.secondary, state.mode === "service_issue" ? 0.07 : 0.105));
  sheen.addColorStop(1, "rgba(255,255,255,0)");
  ctx.strokeStyle = sheen;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(cx - radius * 0.5, cy - radius * 0.24 + Math.sin(time * 0.6) * radius * 0.02);
  ctx.bezierCurveTo(
    cx - radius * 0.15,
    cy - radius * 0.08,
    cx + radius * 0.1,
    cy + radius * 0.1,
    cx + radius * 0.54,
    cy + radius * 0.34
  );
  ctx.stroke();
  ctx.restore();
}

function drawFrame(now) {
  const rect = canvas.getBoundingClientRect();
  const width = rect.width;
  const height = rect.height;
  const time = (now - start) / 1000;
  const palette = palettes[state.mode];

  state.energy = lerp(state.energy, state.targetEnergy, 0.035);
  state.bloom = lerp(state.bloom, state.targetBloom, 0.035);
  if (
    state.hasLiveSpeechActivity
    && performance.now() - state.lastSpeechActivityAt > 160
  ) {
    state.targetSpeechActivity = 0;
  }
  const speechSmoothing = state.targetSpeechActivity > state.speechActivity
    ? 0.32
    : 0.18;
  state.speechActivity = lerp(
    state.speechActivity,
    state.targetSpeechActivity,
    speechSmoothing
  );

  ctx.clearRect(0, 0, width, height);
  drawBackground(width, height, palette, time);

  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.min(width, height) * 0.31;
  const energy = state.energy;

  drawLivingBackground(width, height, palette, time, energy);
  drawAtmosphericBubbles(width, height, cx, cy, radius, palette, time, energy);
  drawPhysicalShadows(cx, cy, radius, palette, time, energy);
  drawGlassHalo(cx, cy, radius, palette, time, energy);
  drawGlassBody(cx, cy, radius, palette, time, energy);
  drawGlassBlob(cx, cy, radius, palette, time, energy);
  drawRipples(cx, cy, radius, palette, time, energy);
  drawIris(cx, cy, radius, palette, time, energy);
  drawSpeakingWave(cx, cy, radius, palette, time, energy);
  drawConstellation(cx, cy, radius, palette, time, energy);
  drawFocusedSweep(cx, cy, radius, palette, time);
  drawSignalPoints(cx, cy, radius, palette, time, energy);

  requestAnimationFrame(drawFrame);
}

buttons.forEach((button) => {
  button.addEventListener("click", () => setMode(button.dataset.mode));
});

energyInput.addEventListener("input", () => {
  state.targetEnergy = Number(energyInput.value) / 100;
  syncReadouts();
});

bloomInput.addEventListener("input", () => {
  state.targetBloom = Number(bloomInput.value) / 100;
});

messageInput.addEventListener("input", () => {
  state.message = messageInput.value || palettes[state.mode].message;
  syncReadouts();
});

scanlinesInput.addEventListener("change", syncReadouts);
window.addEventListener("resize", resize);

const runtimeLink = document.getElementById("runtime-link");
const runtimeLabel = document.getElementById("runtime-label");
const lifecycleModes = {
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
const lifecycleEnergy = {
  booting: 0.42,
  wake_detected: 0.84,
  listening: 0.72,
  transcribing: 0.64,
  thinking: 0.76,
  tool_started: 0.9,
  tool_finished: 0.58,
  speaking: 0.86,
  autonomous: 0.78,
  waiting_confirmation: 0.54,
  recovering: 0.74,
  service_error: 0.94,
  error: 1,
  idle: 0.42,
  stopping: 0.18,
  stopped: 0.05
};

function applyLifecycleEvent(event) {
  const lifecycleState = String(event?.state || "idle");
  if (lifecycleState === "speech_activity") {
    const activity = Number(event?.details?.activity);
    if (Number.isFinite(activity)) {
      if (state.mode !== "speaking") {
        setMode("speaking");
      }
      state.targetSpeechActivity = Math.max(0, Math.min(1, activity));
      state.hasLiveSpeechActivity = true;
      state.lastSpeechActivityAt = performance.now();
    }
    return;
  }

  const mode = lifecycleModes[lifecycleState] || "idle";
  setMode(mode);
  state.targetEnergy = lifecycleEnergy[lifecycleState] ?? 0.55;
  energyInput.value = String(Math.round(state.targetEnergy * 100));
  const detail = event?.details || {};
  state.message = detail.message || (detail.tool
    ? `${palettes[mode].message} · ${detail.tool}`
    : palettes[mode].message);
  messageInput.value = state.message;
  syncReadouts();
}

function connectRuntime() {
  if (window.location.protocol === "file:" || !window.EventSource) {
    runtimeLabel.textContent = "MANUAL PREVIEW";
    return;
  }

  const events = new EventSource("/events");
  events.onopen = () => {
    runtimeLink.dataset.connected = "true";
    runtimeLabel.textContent = "ENTITY LINKED";
  };
  events.onmessage = (message) => {
    try {
      applyLifecycleEvent(JSON.parse(message.data));
    } catch (error) {
      console.warn("Ignored malformed Entity lifecycle event.", error);
    }
  };
  events.onerror = () => {
    runtimeLink.dataset.connected = "false";
    runtimeLabel.textContent = "RECONNECTING";
  };
}

window.EntityVisual = { setMode, applyLifecycleEvent };

resize();
syncReadouts();
connectRuntime();
requestAnimationFrame(drawFrame);
