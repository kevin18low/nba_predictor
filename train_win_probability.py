import pandas as pd
import pickle
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split, cross_validate
from sklearn.metrics import log_loss
from db import get_connection

# for each game, compute each team's win rate from all prior games. Captures hot streaks and team stength
def compute_winrates():
    conn = get_connection()

    games = pd.read_sql_query("""
        SELECT game_id, game_date, home_team, away_team, home_win
        FROM games
        ORDER BY game_date ASC
    """, conn)
    conn.close()

    records = []
    for _, row in games.iterrows():
        records.append({
            "team": row["home_team"],
            "game_id": row["game_id"],
            "game_date": row["game_date"],
            "won": row["home_win"]
        })
        records.append({
            "team": row["away_team"],
            "game_id": row["game_id"],
            "game_date": row["game_date"],
            "won": 1 - row["home_win"]
        })

    df = pd.DataFrame(records).sort_values("game_date")

    # rolling win rate; win rate based on last 10 games
    df["win_rate"] = (
        df.groupby("team")["won"]
        .transform(lambda x: x.shift(1).expanding(min_periods=10).mean())
    )

    home_wr = df[["game_id", "team", "win_rate"]].copy()
    home_wr = home_wr.merge(
        games[["game_id", "home_team"]],
        on="game_id"
    )
    home_wr = home_wr[home_wr["team"] == home_wr["home_team"]][["game_id", "win_rate"]]
    home_wr.columns = ["game_id", "home_win_rate"]

    away_wr = df[["game_id", "team", "win_rate"]].copy()
    away_wr = away_wr.merge(
        games[["game_id", "away_team"]],
        on="game_id"
    )
    away_wr = away_wr[away_wr["team"] == away_wr["away_team"]][["game_id", "win_rate"]]
    away_wr.columns = ["game_id", "away_win_rate"]

    result = home_wr.merge(away_wr, on="game_id")

    result = result.dropna()

    print(f"Computed win rates for {len(result)} games")
    return result

# load game states from database
def load_game_states():
    conn = get_connection()

    df = pd.read_sql_query("""
        SELECT game_id, quarter, time_remaining_secs, home_score, away_score, score_diff, home_win
        FROM game_states
    """, conn)

    print(f"Loaded {len(df)} rows")

    conn.close()

    win_rates = compute_winrates()
    df = df.merge(win_rates, on="game_id", how="inner")

    print(f"After joining win rates: {len(df):,} rows")

    return df

# engineer usable features from raw game state data
def engineer_feats(df):
    df['total_secs_remaining'] = (4 - df["quarter"]).clip(lower=0) * 720 + df["time_remaining_secs"]

    # for overtime, quarter will be > 4 and the quarter length is 5 minutes
    ot_mask = df["quarter"] > 4
    df.loc[ot_mask, "total_secs_remaining"] = df.loc[ot_mask, "time_remaining_secs"]

    # percentage progress through the game; 0 -> start, 1 -> end
    df["game_progress"] = 1 - (df["total_secs_remaining"] / 2880).clip(0, 1)

    # high-scoring games are more volatile
    df['total_points'] = df['home_score'] + df['away_score']

    # weighted difference in score; difference is more impactful near the end of the game 
    df["diff_x_progress"] = df["score_diff"] * df["game_progress"]

    df["is_ot"] = (df["quarter"] > 4).astype(int)

    df["close_game"] = ((df["score_diff"].abs() <= 5) & (df["quarter"] >= 4)).astype(int)

    # win rate differential; positive means home team is stronger. Shrunk towards zero to reduce influence
    df["winrate_diff"] = (df["home_win_rate"] - df["away_win_rate"]) * 0.5

    # weighted winrate; stronger teams protecting a lead late is impactful
    df["winrate_diff_x_progress"] = df["winrate_diff"] * df["game_progress"]

    df = df.dropna()

    return df

# train and evaluate model
def train(df):
    feats = [
        "quarter",
        "time_remaining_secs",
        "score_diff",
        "total_secs_remaining",
        "game_progress",
        "diff_x_progress",
        "total_points",
        "is_ot",
        "close_game",
        "winrate_diff",
        "winrate_diff_x_progress"
    ]

    X = df[feats]
    y = df["home_win"]
    w = 0.5 + df["game_progress"] # weigh late game states as more impactful

    X_train, X_test, y_train, y_test, w_train, w_test = train_test_split(
        X, y, w, test_size=0.3, random_state=18
    )

    scoring = ["accuracy", "neg_log_loss"]

    print("\nTraining Gradient Boosting.")
    gb = GradientBoostingClassifier(n_estimators=100, max_depth=4, random_state=18)
    gb_cv = cross_validate(gb, X_train, y_train, cv=5, scoring=scoring, n_jobs=-1, params={"sample_weight": w_train})
    print(f"CV Accuracy: {gb_cv['test_accuracy'].mean():.4f} ± {gb_cv['test_accuracy'].std():.4f}")
    print(f"CV Log Loss: {-gb_cv['test_neg_log_loss'].mean():.4f} ± {gb_cv['test_neg_log_loss'].std():.4f}")

    print("\nFitting on full training set.")
    gb.fit(X_train, y_train, sample_weight=w_train)
    final_acc = gb.score(X_test, y_test)
    final_ll = log_loss(y_test, gb.predict_proba(X_test))

    print(f"\nFinal Test Scores:")
    print(f"Accuracy: {final_acc:.4f}")
    print(f"Log Loss: {final_ll:.4f}")

    with open("models/win_prob_model.pkl", "wb") as f:
        pickle.dump(gb, f)

    print("\nModel saved to models/")
    return gb

if __name__ == "__main__":
    df = load_game_states()
    df = engineer_feats(df)
    train(df)