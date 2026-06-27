import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
from ingestion.db import get_connection, init_db

BASE_ELO = 1500
K = 20
HOME_ADVANTAGE = 100  # added to home team elo when computing expected win prob
SEASON_REGRESSION = 0.25  # each new season, ratings move 25% back toward BASE_ELO

# Probability that the home team wins given current elo ratings
def expected_win_prob(home_elo, away_elo):
    return 1 / (1 + 10 ** (-(home_elo - away_elo + HOME_ADVANTAGE) / 400))

# Public-facing version - same formula, used at prediction time
def elo_to_win_prob(home_elo, away_elo):
    return expected_win_prob(home_elo, away_elo)

def date_to_season(game_date):
    year = int(game_date[:4])
    month = int(game_date[5:7])
    season_start = year if month >= 10 else year - 1
    return f"{season_start}-{str(season_start + 1)[-2:]}"

# Process games in order and return (final ratings, per-game pre-game snapshot)
# Snapshot records each team's rlo before the game is played
def run_elo(games):
    ratings = {}
    current_season = None
    history = []  # list of {game_id, home_elo, away_elo} before each game

    for _, row in games.iterrows():
        season = date_to_season(row["game_date"])

        if season != current_season:
            if current_season is not None:
                for team in ratings:
                    ratings[team] = ratings[team] + SEASON_REGRESSION * (BASE_ELO - ratings[team])
            current_season = season

        home = row["home_team"]
        away = row["away_team"]

        home_elo = ratings.get(home, BASE_ELO)
        away_elo = ratings.get(away, BASE_ELO)

        history.append({"game_id": row["game_id"], "home_elo": home_elo, "away_elo": away_elo})

        expected = expected_win_prob(home_elo, away_elo)
        actual = float(row["home_win"])
        delta = K * (actual - expected)
        ratings[home] = home_elo + delta
        ratings[away] = away_elo - delta

    return ratings, pd.DataFrame(history)

# Returns a DataFrame of pre-game Elo values for every historical game — used in training.
def compute_elo_history():
    conn = get_connection()
    games = pd.read_sql_query("""
        SELECT game_id, game_date, home_team, away_team, home_win
        FROM games ORDER BY game_date ASC
    """, conn)
    conn.close()
    _, history = run_elo(games)
    return history

# Compute current Elo ratings from all games and store them in the DB.
def compute_and_store():
    conn = get_connection()
    games = pd.read_sql_query("""
        SELECT game_id, game_date, home_team, away_team, home_score, away_score, home_win
        FROM games ORDER BY game_date ASC
    """, conn)

    ratings, _ = run_elo(games)

    conn.execute("DELETE FROM elo_ratings")
    for team, elo in ratings.items():
        conn.execute("INSERT INTO elo_ratings (team, elo) VALUES (?, ?)", (team, round(elo, 2)))

    conn.commit()
    conn.close()
    return ratings

def get_elo_ratings():
    conn = get_connection()
    rows = conn.execute("SELECT team, elo FROM elo_ratings").fetchall()
    conn.close()
    return {r["team"]: r["elo"] for r in rows}

if __name__ == "__main__":
    init_db()
    ratings = compute_and_store()
    sorted_ratings = sorted(ratings.items(), key=lambda x: -x[1])
    print(f"\nElo ratings after {len(ratings)} teams processed:\n")
    for team, elo in sorted_ratings:
        print(f"{team:4s} {elo:7.1f}")
