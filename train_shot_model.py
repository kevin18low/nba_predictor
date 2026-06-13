import pandas as pd
import pickle
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split, cross_validate
from sklearn.metrics import log_loss
from sklearn.preprocessing import LabelEncoder
from db import get_connection

# load shot data from shot attempts table and game states table
def load_shot_data():
    conn = get_connection()

    # base player shot details from shot attempts
    shots = pd.read_sql_query("""
        SELECT sa.player_id, sa.game_id, sa.x, sa.y, sa.shot_distance, sa.shot_zone, sa.shot_zone_area, sa.shot_type, sa.action_type, sa.made
        FROM shot_attempts sa
        WHERE sa.x IS NOT NULL
        AND sa.y IS NOT NULL
        AND sa.shot_distance IS NOT NULL
    """, conn)

    print(f"Loaded {len(shots):,} shots from shot_attempts")

    # in-game context from game_states; rolling FG% and attempts so far by the player
    game_states = pd.read_sql_query("""
        SELECT game_id, person_id, shot_result, quarter, time_remaining_secs
        FROM game_states
        WHERE shot_result IS NOT NULL
        AND person_id IS NOT NULL
        AND person_id != 0
        ORDER BY game_id, quarter, time_remaining_secs DESC
    """, conn)

    conn.close()

    print(f"Loaded {len(game_states):,} in-game shot events")
    return shots, game_states

# compute in-game stats: shots attempted, current FG%, last 3 shot outcomes
def compute_ingame_context(game_states):
    game_states = game_states.copy()
    game_states["made"] = (game_states["shot_result"] == "Made").astype(int)

    game_states = game_states.sort_values(
        ["game_id", "quarter", "time_remaining_secs"],
        ascending=[True, True, False]
    )

    game_states["shots_taken"] = (
        game_states.groupby(["game_id", "person_id"])["made"]
        .transform(lambda x: x.shift(1).expanding().count())
        .fillna(0)
    )

    game_states["fg_pct_tonight"] = (
        game_states.groupby(["game_id", "person_id"])["made"]
        .transform(lambda x: x.shift(1).expanding(min_periods=1).mean())
        .fillna(0.45)  # fall back to league average
    )

    # last 3 shots: sum of makes in previous 3 attempts
    game_states["hot_hand"] = (
        game_states.groupby(["game_id", "person_id"])["made"]
        .transform(lambda x: x.shift(1).rolling(window=3, min_periods=1).sum())
        .fillna(0)
    )

    return game_states[["game_id", "person_id", "shots_taken", "fg_pct_tonight", "hot_hand"]]

# add extra context features
def engineer_feats(shots, context):
    context_agg = context.groupby(["game_id", "person_id"]).agg(
        shots_taken=("shots_taken", "mean"),
        fg_pct_tonight=("fg_pct_tonight", "mean"),
        hot_hand=("hot_hand", "mean")
    ).reset_index()

    df = shots.merge(
        context_agg,
        left_on=["game_id", "player_id"],
        right_on=["game_id", "person_id"],
        how="left"
    )

    # fill missing context with neutral values
    df["shots_taken"] = df["shots_taken"].fillna(0)
    df["fg_pct_tonight"] = df["fg_pct_tonight"].fillna(0.45)
    df["hot_hand"] = df["hot_hand"].fillna(0)

    # encode shot zone
    le_zone = LabelEncoder()
    df["zone_enc"] = le_zone.fit_transform(df["shot_zone"].fillna("Unknown"))

    # encode shot zone area
    le_area = LabelEncoder()
    df["area_enc"] = le_area.fit_transform(df["shot_zone_area"].fillna("Unknown"))

    # encode action type
    le_action = LabelEncoder()
    df["action_enc"] = le_action.fit_transform(df["action_type"].fillna("Unknown"))

    # encode shot type (2pt vs 3pt)
    df["is_three"] = (df["shot_type"] == "3PT Field Goal").astype(int)

    df["distance_sq"] = df["shot_distance"] ** 2

    # shots from the same spot on either side should be the treated the same
    df["abs_x"] = df["x"].abs()

    df = df.dropna(subset=["x", "y", "shot_distance", "made"])

    return df, le_zone, le_area, le_action

# train and evaluate model
def train(df):
    feats = [
        "x",
        "y",
        "abs_x",
        "shot_distance",
        "distance_sq",
        "zone_enc",
        "area_enc",
        "action_enc",
        "is_three",
        "player_id",
        "shots_taken",
        "fg_pct_tonight",
        "hot_hand"
    ]

    X = df[feats]
    y = df["made"]

    print(f"\nClass balance: {y.mean():.3f} made rate")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.3, random_state=18
    )

    scoring = ["accuracy", "neg_log_loss"]

    print("\nTraining Shot Quality Model With Gradient Boosting.")
    gb = GradientBoostingClassifier(n_estimators=100, max_depth=4, random_state=18)
    gb_cv = cross_validate(gb, X_train, y_train, cv=5, scoring=scoring, n_jobs=-1)
    print(f"CV Accuracy: {gb_cv['test_accuracy'].mean():.4f} +/- {gb_cv['test_accuracy'].std():.4f}")
    print(f"CV Log Loss: {-gb_cv['test_neg_log_loss'].mean():.4f} +/- {gb_cv['test_neg_log_loss'].std():.4f}")

    print("\nFitting on full training set.")
    gb.fit(X_train, y_train)
    final_acc = gb.score(X_test, y_test)
    final_ll = log_loss(y_test, gb.predict_proba(X_test))

    print(f"\nFinal Test Scores:")
    print(f"Accuracy: {final_acc:.4f}")
    print(f"Log Loss: {final_ll:.4f}")

    with open("models/shot_model.pkl", "wb") as f:
        pickle.dump(gb, f)

    print("\nShot model saved to models/")
    return gb

if __name__ == "__main__":
    shots, game_states = load_shot_data()
    context = compute_ingame_context(game_states)
    df, le_zone, le_area, le_action = engineer_feats(shots, context)
    train(df)