# Bio Deduction Games

Generic live biosignal companion app for social deduction games (Werewolf, Impostor-like, etc.).

## Current scope (v0)
- Modern gameshow-style UI
- Start menu with:
  - Data source toggle: **Mock Data / Live Data (scaffold)**
  - Dynamic player setup via `+`
  - Hub MAC section with detect button + manual fallback
  - Auto-mapping preview player → hub MAC → EKG/EDA channels
  - Game mode selector (currently: **Generic**)
- Generic mode (no game logic tied to a specific game yet)
- Up to **8 players with 2 hubs** / **4 players with 1 hub**
- Per player:
  - Live HR (absolute value)
  - HR trend plot (last 60s)
  - EDA trend plot (last 60s)
- Live data integration scaffold for OpenSignals Hub (backend hook prepared)
- In-game elimination helper: click player card to hide, restore from bottom bar

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
