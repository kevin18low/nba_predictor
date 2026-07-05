# NBA Predictor

Real-time NBA game analysis with live win probability and per-shot quality predictions, served through a Flask web UI.

**Live demo:** https://nba-predictor-f2lw.onrender.com

## Overview

Two machine learning models run together during live games:

- **Win Probability Model**
Gradient Boosting classifier trained on historical play-by-play game states. Predicts the home team's win probability given the current score, time remaining, quarter, and rolling team win rates.
- **Shot Quality Model**
Gradient Boosting classifier trained on shot attempt data. Predicts the probability that a shot goes in based on location, shot type, player skill, and in-game context such as having a 'hot hand', and player FG% throughout the game.

The UI lets you watch live games or step through replays of past games, with a shot chart and probability tracker updating in real time.

## Project Structure

```
nba_predictor/
├── app.py                        # Flask app - web routes and API endpoints
├── state.py                      # Shared in-memory game state (thread-safe)
├── ingestion/
│   ├── db.py                     # SQLite connection and schema initialization
│   ├── fetch_games.py            # Fetch and store historical game results
│   ├── fetch_playbyplay.py       # Fetch and store play-by-play game states
│   └── fetch_shots.py            # Fetch and store shot attempt data
├── prediction/
│   ├── train_win_probability.py  # Train win probability model
│   ├── train_shot_model.py       # Train shot quality model
│   ├── predict_score.py          # Project final score from current game state
│   └── predict_shot.py           # Load shot model and run inference
├── live/
│   ├── live_data.py              # Pull live scoreboard and play-by-play from NBA API
│   ├── live_predictor.py         # Run predictions against live game data
│   ├── poller.py                 # Background thread polling live games every 30s
│   └── replay.py                 # Build replay sequences from historical games
├── models/                       # Saved .pkl model files (not committed)
├── data/                         # SQLite database (not committed)
└── test/
    └── test_predictions.py
```

## Setup

**Prerequisites:** Python 3.10+

```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
```

## Usage

### 1. Initialize the database

```bash
python ingestion/db.py
```

### 2. Fetch historical data

```bash
python ingestion/fetch_games.py
python ingestion/fetch_playbyplay.py
python ingestion/fetch_shots.py
```

### 3. Train the models

```bash
python prediction/train_win_probability.py
python prediction/train_shot_model.py
```

Trained models are saved to `models/`.

### 4. Run the web app

```bash
python app.py
```

Open `http://localhost:5000`. The poller starts automatically and polls live games every 30 seconds.

## Models

### Win Probability

Features: score differential, time remaining, quarter, game progress, total points, overtime flag, close-game flag, rolling team win rates (last 10 games), and interaction terms. Late-game states are upweighted during training.

### Shot Quality

Features: court coordinates (x, y, distance), shot zone and area (label-encoded), action type, 2PT/3PT flag, player career FG%, player 3PT% (Bayesian-shrunk by attempt rate), player zone FG%, and in-game context (shots taken this game, rolling FG% tonight, hot hand over last 3 shots).

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /api/games` | All games for today |
| `GET /api/game/<id>/state` | Live scores, win probabilities, projected final |
| `GET /api/game/<id>/shots` | All shot events with quality probabilities |
| `GET /api/game/<id>/replay` | Full shot-by-shot replay sequence |

## Deployment

Deployed on [Render](https://render.com) via [render.yaml](render.yaml), running under gunicorn with a single worker (the live-game poller and in-memory state live in one process).

The full `data/nba.db` (~300 MB of training data) stays local. A slim `data/runtime.db` (~0.5 MB) is committed instead, containing only what the app needs at runtime: game results, team stats, elo ratings, and play-by-play for the 12 featured replay games. The `NBA_DB_FILE` env var selects the database (`nba.db` locally, `runtime.db` in production).

To refresh the deployed site with recent games:

```bash
# 1. update local data (ingestion + elo/team stats)
# 2. rebuild the slim database
python ingestion/build_runtime_db.py
# 3. commit data/runtime.db and push — Render redeploys automatically
```

## Dependencies

See [requirements.txt](requirements.txt). Key packages: `flask`, `nba_api`, `scikit-learn`, `pandas`, `plotly`.
