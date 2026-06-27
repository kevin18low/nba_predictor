import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pickle
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split, cross_validate
from sklearn.metrics import log_loss
from ingestion.db import get_connection
from ingestion.compute_elo import compute_elo_history

def date_to_season(game_date):
    year = int(game_date[:4])
    month = int(game_date[5:7])
    season_start = year if month >= 10 else year - 1
    return f"{season_start}-{str(season_start + 1)[-2:]}"

def load_data():
    conn = get_connection()

    games = pd.read_sql_query("""
        SELECT game_id, game_date, home_team, away_team, home_win
        FROM games ORDER BY game_date ASC
    """, conn)

    team_stats = pd.read_sql_query("""
        SELECT season, team, off_rating, def_rating, pace
        FROM team_stats
    """, conn)

    conn.close()

    games["season"] = games["game_date"].apply(date_to_season)

    # pre-game Elo for each historical game (no leakage — recorded before each game)
    elo_history = compute_elo_history()
    games = games.merge(elo_history, on="game_id", how="inner")

    home_stats = team_stats.rename(columns={"team": "home_team", "off_rating": "home_off", "def_rating": "home_def", "pace": "home_pace"})
    away_stats = team_stats.rename(columns={"team": "away_team", "off_rating": "away_off", "def_rating": "away_def", "pace": "away_pace"})

    df = games.merge(home_stats, on=["season", "home_team"], how="inner")
    df = df.merge(away_stats, on=["season", "away_team"], how="inner")

    print(f"Loaded {len(df)} games")
    return df

def engineer_feats(df):
    df["elo_diff"] = df["home_elo"] - df["away_elo"]
    df["off_diff"] = df["home_off"] - df["away_off"]
    df["def_diff"] = df["away_def"] - df["home_def"]   # flipped: lower is better
    df["pace_diff"] = df["home_pace"] - df["away_pace"]
    df["home_off_vs_away_def"] = df["home_off"] - df["away_def"]
    df["away_off_vs_home_def"] = df["away_off"] - df["home_def"]

    return df.dropna()

def train(df):
    feats = [
        "home_elo", "away_elo", "elo_diff",
        "home_off", "home_def", "home_pace",
        "away_off", "away_def", "away_pace",
        "off_diff", "def_diff", "pace_diff",
        "home_off_vs_away_def", "away_off_vs_home_def",
    ]

    X = df[feats]
    y = df["home_win"]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=18)

    scoring = ["accuracy", "neg_log_loss"]

    print("\nTraining Pre-Game Model with Gradient Boosting.")
    gb = GradientBoostingClassifier(n_estimators=200, max_depth=3, learning_rate=0.05, random_state=18)
    gb_cv = cross_validate(gb, X_train, y_train, cv=5, scoring=scoring, n_jobs=-1)
    print(f"CV Accuracy: {gb_cv['test_accuracy'].mean():.4f} ± {gb_cv['test_accuracy'].std():.4f}")
    print(f"CV Log Loss: {-gb_cv['test_neg_log_loss'].mean():.4f} ± {gb_cv['test_neg_log_loss'].std():.4f}")

    print("\nFitting on full training set.")
    gb.fit(X_train, y_train)
    final_acc = gb.score(X_test, y_test)
    final_ll = log_loss(y_test, gb.predict_proba(X_test))

    print(f"\nFinal Test Scores:")
    print(f"Accuracy: {final_acc:.4f}")
    print(f"Log Loss: {final_ll:.4f}")

    print("\nTop features by importance:")
    importances = sorted(zip(feats, gb.feature_importances_), key=lambda x: -x[1])
    for name, imp in importances:
        print(f"{name:<30s} {imp:.4f}")

    with open("models/pregame_model.pkl", "wb") as f:
        pickle.dump(gb, f)

    print("\nModel saved to models/pregame_model.pkl")
    return gb

if __name__ == "__main__":
    df = load_data()
    df = engineer_feats(df)
    train(df)
