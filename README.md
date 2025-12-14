# Elden Ring Fog Gate Randomizer Tracker

A web-based tool to visualize and track exploration progress for the [Fog Gate Randomizer](https://www.nexusmods.com/eldenring/mods/3295) mod for Elden Ring. Includes an optional in-game mod for automatic discovery tracking.

![Status](https://img.shields.io/badge/status-active-brightgreen) ![License](https://img.shields.io/badge/license-MIT-blue)

**Try it online:** [https://fogvizu.malenia.win](https://fogvizu.malenia.win)

## Features

- **Interactive Graph Visualization** - Explore fog gate connections as a force-directed graph powered by D3.js
- **Explorer Mode** - Discover areas progressively as you play, with automatic save/load per seed
- **Full Spoiler Mode** - View the entire randomized map at once
- **Pathfinding** - Click any node to highlight the shortest path from Chapel of Anticipation
- **Frontier Highlighting** - See unexplored areas and their access points at a glance
- **Item Log Integration** - Load Item Randomizer logs to see key item locations on gates
- **Area Tagging** - Mark areas with custom tags for tracking your progress
- **Stream to OBS** - Real-time synchronization via WebSocket for OBS browser sources
- **In-Game Mod** - Automatic discovery tracking when traversing fog gates (optional)

## Quick Start

### Online Mode (with account)

1. Go to [fogvizu.malenia.win](https://fogvizu.malenia.win)
2. Log in with your Twitch account
3. Upload your spoiler log to create a game
4. Start exploring!

### Offline Mode (no account required)

1. Go to [fogvizu.malenia.win](https://fogvizu.malenia.win)
2. Click "Use Offline" on the landing page
3. Drag and drop your spoiler log file
4. Your progress is saved locally in your browser

### Running Locally

```bash
# Clone the repository
git clone https://github.com/rbignon/er-fog-vizu.git
cd er-fog-vizu

# Option 1: Simple mode (no database)
pip install fastapi uvicorn
python server.py

# Option 2: Full mode (with database, auth, mod support)
cd server
pip install -e .
cp .env.example .env  # Configure your environment
alembic upgrade head
uvicorn fogvizu.main:app --reload --port 8001
```

See `server/README.md` for detailed backend setup instructions.

## In-Game Mod Integration

The optional FogRandoTracker mod automatically detects when you traverse fog gates and syncs discoveries to the web interface in real-time.

### Setup

1. Build the mod (requires Rust + Windows target):
   ```bash
   cd mod
   cargo build --release
   ```

2. Copy these files to your game folder:
   - `fog_rando_tracker.dll`
   - `fog_rando_tracker.toml`

3. Configure the mod:
   - Log in to the website and create a game
   - Click "Mod Config" on your game card
   - Copy the configuration to your `fog_rando_tracker.toml`

4. Inject the DLL into Elden Ring using the included injector or a mod loader

See `mod/README.md` for detailed mod documentation.

## Stream to OBS

Display the graph on your stream with real-time synchronization.

### Setup

1. Click the **Stream** button in the main UI
2. Copy the generated URL
3. In OBS:
   - Click **+** under Sources
   - Select **Browser**
   - Paste the URL
   - Set dimensions to **1920 x 1080** (or your canvas size)

The browser source will mirror your interactions in real-time: navigation, zoom, node selection, and exploration progress.

## Project Structure

```
er-fog-vizu/
├── web/                    # Frontend (vanilla JS + D3.js)
├── server/                 # Backend (Python FastAPI + PostgreSQL)
├── mod/                    # In-game mod (Rust DLL)
├── docs/                   # Specifications
└── server.py               # Simple server (no database)
```

## Technical Details

- **Pure Frontend** - No build step required, ES6 modules run directly in browser
- **FastAPI + WebSocket** - Python backend for real-time sync and mod integration
- **PostgreSQL** - Database for user accounts, games, and discoveries
- **Twitch OAuth** - Authentication via Twitch
- **D3.js** - Force-directed graph simulation for automatic layout
- **Rust + hudhook** - In-game overlay mod using ImGui

## Browser Support

Tested on:
- Chrome 90+
- Firefox 88+
- Edge 90+
- Safari 14+

## Contributing

Contributions are welcome! Feel free to open issues or submit pull requests.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

- [thefifthmatt](https://www.nexusmods.com/eldenring/users/58426171) for creating the Fog Gate Randomizer mod
- [D3.js](https://d3js.org/) for the visualization library
- [veeenu](https://github.com/veeenu) for hudhook and libeldenring
