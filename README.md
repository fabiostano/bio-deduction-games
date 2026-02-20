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
- Live data integration (biosignalsplux-based, best-effort API compatibility)
- Hub discovery (best-effort) + manual MAC fallback
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

## Live Data (OpenSignals/BioPlux)
- Select **Live Data** in the start menu.
- Use **Hubs erkennen** or enter MACs manually.
- Mapping preview shows fixed channel assignment:
  - CH1/2 = Player1 EKG/EDA
  - CH3/4 = Player2 EKG/EDA
  - CH5/6 = Player3 EKG/EDA
  - CH7/8 = Player4 EKG/EDA

The app no longer hard-depends on `biosignalsplux` via pip because some environments do not provide a public wheel on PyPI. Install your OpenSignals/BioPlux Python package manually (vendor wheel/SDK) on the target machine for Live mode.

> Note: biosignalsplux APIs vary by version. The connector is implemented with runtime compatibility fallbacks; if your local stack differs, we can adapt quickly based on your error log.

## Build Windows EXE (later)
We’ll add a PyInstaller build pipeline once the core UI/data flow is stable.
