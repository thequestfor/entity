# Entity Visual Interface Prototype

Real-time 3D visual shell for Entity.

The Three.js scene is served by Entity in `3d` mode and reacts to the same
lifecycle events as the 2D and Unreal interfaces.

## Goal

- Render Entity as a real 3D glass body, not a flat CSS/canvas illusion.
- Place the body inside an Aero cybercore control room.
- Drive animation from Entity-style states.
- Prepare for a later local WebSocket/SSE bridge from the Python runtime.

## Run

```sh
cd visual_interface
npm install
npm run dev
```

Then open the Vite URL, usually `http://127.0.0.1:5173`.

To run it connected to Entity from the project root:

```sh
.venv/bin/python main.py 3d
```

## Current Prototype

- Three.js scene with real camera, perspective, lights, shadows, and bloom.
- Procedural glossy Aero room based on the new references: white molded
  shelves, aqua glass columns, bubble-wall motifs, porthole windows, ceiling
  discs/rings, lime mobiles, chrome rails, colored indicator gems, and real
  glass bubbles.
- Glass entity body with central orb, support stem, base, and internal lights.
- State controls for idle, listening, thinking, speaking, acting, autonomous,
  service issue, and offline.
- Entity body uses colored mode rings, internal energy, particles, bubbles,
  room panels, and light intensity to show state.
- Mode color is isolated to the entity body, inner shell, local glow, core, and
  mode rings so the room stays neutral glossy Aero.
- Foreground floor/deck geometry is modeled so the room fills the camera view
  instead of fading into an unfinished dark strip.

## Runtime bridge

Add a local state bridge:

```json
{
  "mode": "speaking",
  "energy": 0.82,
  "audioLevel": 0.67,
  "message": "Answering"
}
```

Entity streams renderer-neutral lifecycle events over local Server-Sent Events.
The collapsed interface laboratory remains available for manual state previews.
