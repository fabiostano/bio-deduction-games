# Bio Deduction Games

Generic live biosignal companion app for social deduction games (Werewolf, Impostor-like, etc.).

## Current scope (v0)
- Modern gameshow-style UI
- Generic mode (no game logic tied to a specific game yet)
- Up to **2 hubs × 3 players = 6 players**
- Per player:
  - Live HR (absolute value)
  - HR trend plot (last 60s)
  - EDA trend plot (last 60s)
- Data source abstraction for future OpenSignals Hub integration

## Stack
- Python 3.11+
- PySide6 (desktop UI)
- pyqtgraph (real-time plotting)

## Quick start
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
python -m bio_deduction_game
```

## Build Windows EXE (later)
We’ll add a PyInstaller build pipeline once the core UI/data flow is stable.
