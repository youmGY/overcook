# Overcook 🍳

A gesture-controlled multiplayer cooking game built with Python and Pygame.

![Screenshot placeholder](docs/screenshot.png)

## Features

- **Gesture control**: Play using hand gestures detected via webcam (MediaPipe + custom MLP)
- **Multiplayer**: LAN-based multiplayer for up to 4 players
- **Recipes**: Chop, cook, and serve dishes before time runs out
- **Audio**: Full sound effects and background music

## Requirements

- Python 3.9+
- pygame
- mediapipe
- opencv-python
- onnxruntime

## Installation

```bash
git clone <repo-url>
cd overcook
pip install -r requirements.txt
```

## Usage

```bash
# Standard keyboard/mouse mode
python main.py

# Gesture control mode
python main.py --gesture

# Multiplayer mode
python main.py --multiplayer --name "YourName"
```

## Architecture

```
overcook/           # Main package
├── constants.py    # Game constants and configuration
├── engine.py       # Pygame initialization, font/image utilities
├── entities.py     # Game entities: Station, Player, Order
├── audio.py        # Audio manager (SFX + BGM)
├── network.py      # LAN multiplayer networking
├── utils.py        # Drawing utilities
├── game.py         # Main game loop and state machine
├── ui/             # UI components
│   ├── game_ui.py  # In-game HUD, overlays, buttons
│   └── lobby_ui.py # Multiplayer lobby UI
└── recognition/    # Gesture recognition pipeline
    ├── camera.py
    ├── gesture.py
    ├── hand_tracker.py
    ├── interface.py
    └── models/     # ML model files
assets/
├── images/         # Game sprites and backgrounds
└── audio/          # BGM and SFX
tests/              # Unit tests
docs/               # Documentation
```

## Controls

| Action | Keyboard | Gesture |
|--------|----------|---------|
| Move   | Arrow keys / WASD | Hand position |
| Interact | Space / E | Grab gesture |
| Chop   | Hold Space | Chop motion |
| Stir   | Hold S | Stir motion |
| Menu   | Escape | — |

## License

MIT — see [LICENSE](LICENSE)
