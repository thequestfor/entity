# Entity Visual Interface Prototype

Experimental real-time 3D visual shell for Entity.

This is intentionally separate from the Python assistant runtime and the older
`visual_mockup/` canvas sketch. It is a test environment for the eventual
fullscreen visual body.

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

## Next Integration Step

Add a local state bridge:

```json
{
  "mode": "speaking",
  "energy": 0.82,
  "audioLevel": 0.67,
  "message": "Answering"
}
```

The visual app should subscribe to Entity runtime state and replace the manual
test controls.
