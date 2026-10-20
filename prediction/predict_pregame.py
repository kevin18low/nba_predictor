import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pickle
import pandas as pd
from datetime import date
from ingestion.db import get_connection
from ingestion.compute_elo import get_elo_ratings

def current_season():
    today = date.today()
    year = today.year
    month = today.month
    season_start = year if month >= 10 else year - 1
    return f"{season_start}-{str(season_start + 1)[-2:]}"

def load_pregame_model():
    with open("models/pregame_model.pkl", "rb") as f:
        return pickle.load(f)

def predict_pregame(home_team, away_team, model=None):
    if model is None:
        model = load_pregame_model()

    season = current_season()
    conn = get_connection()

    # early in a new season there are no team stats yet, so use the latest season recorded
    has_stats = conn.execute("SELECT 1 FROM team_stats WHERE season = ? LIMIT 1", (season,)).fetchone()
    if has_stats is None:
        season = conn.execute("SELECT MAX(season) FROM team_stats").fetchone()[0]

    home_stats = conn.execute("""
        SELECT off_rating, def_rating, pace
        FROM team_stats WHERE season = ? AND team = ?
    """, (season, home_team)).fetchone()

    away_stats = conn.execute("""
        SELECT off_rating, def_rating, pace
        FROM team_stats WHERE season = ? AND team = ?
    """, (season, away_team)).fetchone()

    conn.close()

    if home_stats is None or away_stats is None:
        missing = home_team if home_stats is None else away_team
        raise ValueError(f"No team stats found for {missing} in {season}")

    elo = get_elo_ratings()
    home_elo = elo.get(home_team, 1500)
    away_elo = elo.get(away_team, 1500)

    h = dict(home_stats)
    a = dict(away_stats)

    feats = pd.DataFrame([{
        "home_elo": home_elo,
        "away_elo": away_elo,
        "elo_diff": home_elo - away_elo,
        "home_off": h["off_rating"],
        "home_def": h["def_rating"],
        "home_pace": h["pace"],
        "away_off": a["off_rating"],
        "away_def": a["def_rating"],
        "away_pace": a["pace"],
        "off_diff": h["off_rating"] - a["off_rating"],
        "def_diff": a["def_rating"] - h["def_rating"],
        "pace_diff": h["pace"] - a["pace"],
        "home_off_vs_away_def": h["off_rating"] - a["def_rating"],
        "away_off_vs_home_def": a["off_rating"] - h["def_rating"],
    }])

    proba = model.predict_proba(feats)[0]
    home_win_prob = round(float(proba[1]), 4)

    return {
        "home_team": home_team,
        "away_team": away_team,
        "home_win_prob": home_win_prob,
        "away_win_prob": round(1 - home_win_prob, 4),
        "home_elo": round(home_elo, 1),
        "away_elo": round(away_elo, 1),
        "season": season,
    }

if __name__ == "__main__":
    home = sys.argv[1] if len(sys.argv) > 2 else "BOS"
    away = sys.argv[2] if len(sys.argv) > 2 else "LAL"

    result = predict_pregame(home, away)
    print(f"\n{result['away_team']} @ {result['home_team']}  ({result['season']})")
    print(f"{result['home_team']} win prob: {result['home_win_prob']:.1%}  (Elo: {result['home_elo']})")
    print(f"{result['away_team']} win prob: {result['away_win_prob']:.1%}  (Elo: {result['away_elo']})")
