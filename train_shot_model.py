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

# compute per-player historical skill features
# returns player_stats dict, zone_stats dict, league averages, and zone league averages
def compute_player_stats(shots_train):
    league_avg = shots_train["made"].mean()
    league_3pt_avg = shots_train[shots_train["shot_type"] == "3PT Field Goal"]["made"].mean()
    league_3pt_attempt_rate = (shots_train["shot_type"] == "3PT Field Goal").mean()

    # league FG% per zone — used as fallback for sparse player zone data
    zone_league_avgs = shots_train.groupby("shot_zone")["made"].mean().to_dict()

    # overall FG% per player
    overall = shots_train.groupby("player_id")["made"].agg(["mean", "count"])
    overall.columns = ["fg_pct", "shot_volume"]

    # 3PT makes and attempts per player (raw counts for Bayesian shrinkage)
    threes = shots_train[shots_train["shot_type"] == "3PT Field Goal"].groupby("player_id")["made"].agg(["sum", "count"])
    threes.columns = ["three_makes", "three_attempts"]

    # zone FG% per player
    zone = shots_train.groupby(["player_id", "shot_zone"])["made"].agg(["mean", "count"])
    zone.columns = ["zone_fg_pct", "zone_volume"]

    player_stats = {}
    for pid in overall.index:
        row = overall.loc[pid]
        total_shots = row["shot_volume"]
        fg = row["fg_pct"] if total_shots >= 20 else league_avg

        # Bayesian shrinkage for 3PT%:
        # prior is scaled by how often the player actually attempts 3s vs the league rate.
        # a center who never shoots 3s gets a prior near 0; a wing gets a prior near league avg.
        if pid in threes.index:
            trow = threes.loc[pid]
            n_attempts = trow["three_attempts"]
            n_makes = trow["three_makes"]
        else:
            n_attempts = 0
            n_makes = 0

        player_3pt_rate = n_attempts / total_shots if total_shots > 0 else 0
        rate_ratio = min(player_3pt_rate / league_3pt_attempt_rate, 1.0) if league_3pt_attempt_rate > 0 else 0
        prior = league_3pt_avg * rate_ratio

        shrink_factor = 20
        tpct = (n_makes + shrink_factor * prior) / (n_attempts + shrink_factor)

        player_stats[pid] = {"overall_fg_pct": fg, "three_pt_pct": tpct}

    zone_stats = {}
    for (pid, zone_name), row in zone.iterrows():
        if row["zone_volume"] >= 10:
            zone_stats[(pid, zone_name)] = row["zone_fg_pct"]

    return player_stats, zone_stats, league_avg, league_3pt_avg, zone_league_avgs

# compute in-game stats: shots attempted, current FG%, last 3 shot outcomes
def compute_ingame_context(game_states):
    game_states = game_states.copy()
    game_states["made"] = (game_states["shot_result"] == "Made").astype(int)
    
    game_states = game_states.sort_values(
        ["game_id", "person_id", "quarter", "time_remaining_secs"],
        ascending=[True, True, True, False]
    ).reset_index(drop=True)

    shots_taken = []
    fg_pct_tonight = []
    hot_hand = []

    # track state per (game_id, person_id) pair
    state = {}

    for _, row in game_states.iterrows():
        key = (row["game_id"], row["person_id"])

        if key not in state:
            state[key] = {"count": 0, "made": 0, "last3": []}

        s = state[key]
        shots_taken.append(s["count"])
        fg_pct_tonight.append(s["made"] / s["count"] if s["count"] > 0 else 0.45)
        hot_hand.append(sum(s["last3"]))

        m = int(row["made"])
        s["count"] += 1
        s["made"] += m
        s["last3"].append(m)
        if len(s["last3"]) > 3:
            s["last3"].pop(0)

    game_states["shots_taken"] = shots_taken
    game_states["fg_pct_tonight"] = fg_pct_tonight
    game_states["hot_hand"] = hot_hand

    return game_states[["game_id", "person_id", "shots_taken", "fg_pct_tonight", "hot_hand"]]

# add extra context features, considering shots sequentially
# player_stats and zone_stats must be computed from training data only to avoid leakage
def engineer_feats(shots, context, player_stats, zone_stats, league_avg, league_3pt_avg, zone_league_avgs, le_zone=None, le_area=None, le_action=None):
    shots = shots.reset_index(drop=True)
    shots["shot_order"] = shots.groupby(["game_id", "player_id"]).cumcount()

    context = context.reset_index(drop=True)
    context["shot_order"] = context.groupby(["game_id", "person_id"]).cumcount()

    df = shots.merge(
        context,
        left_on=["game_id", "player_id", "shot_order"],
        right_on=["game_id", "person_id", "shot_order"],
        how="left"
    )

    df["shots_taken"] = df["shots_taken"].fillna(0)
    df["fg_pct_tonight"] = df["fg_pct_tonight"].fillna(0.45)
    df["hot_hand"] = df["hot_hand"].fillna(0)

    # replace raw player_id with player skill features
    df["player_overall_fg_pct"] = df["player_id"].map(
        lambda pid: player_stats.get(pid, {}).get("overall_fg_pct", league_avg)
    )
    df["player_3pt_pct"] = df["player_id"].map(
        lambda pid: player_stats.get(pid, {}).get("three_pt_pct", league_3pt_avg)
    )
    def get_zone_fg_pct(row):
        key = (row["player_id"], row["shot_zone"])
        if key in zone_stats:
            return zone_stats[key]
        if row["shot_type"] == "3PT Field Goal":
            return player_stats.get(row["player_id"], {}).get("three_pt_pct", league_3pt_avg)
        
        # fall back to league average for people who rarely take certain shot types
        return zone_league_avgs.get(row["shot_zone"], league_avg)

    df["player_zone_fg_pct"] = df.apply(get_zone_fg_pct, axis=1)

    # fit encoders on training data
    if le_zone is None:
        le_zone = LabelEncoder()
        df["zone_enc"] = le_zone.fit_transform(df["shot_zone"].fillna("Unknown"))
    else:
        df["zone_enc"] = df["shot_zone"].fillna("Unknown").map(
            lambda v: le_zone.transform([v])[0] if v in le_zone.classes_ else 0
        )

    if le_area is None:
        le_area = LabelEncoder()
        df["area_enc"] = le_area.fit_transform(df["shot_zone_area"].fillna("Unknown"))
    else:
        df["area_enc"] = df["shot_zone_area"].fillna("Unknown").map(
            lambda v: le_area.transform([v])[0] if v in le_area.classes_ else 0
        )

    if le_action is None:
        le_action = LabelEncoder()
        df["action_enc"] = le_action.fit_transform(df["action_type"].fillna("Unknown"))
    else:
        df["action_enc"] = df["action_type"].fillna("Unknown").map(
            lambda v: le_action.transform([v])[0] if v in le_action.classes_ else 0
        )

    df["is_three"] = (df["shot_type"] == "3PT Field Goal").astype(int)
    df["distance_sq"] = df["shot_distance"] ** 2
    df["abs_x"] = df["x"].abs()

    df = df.dropna(subset=["x", "y", "shot_distance", "made"])

    return df, le_zone, le_area, le_action

# train and evaluate model
def train(df, le_zone, le_area, le_action, player_stats, zone_stats, league_avg, league_3pt_avg, zone_league_avgs):
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
        "player_overall_fg_pct",
        "player_3pt_pct",
        "player_zone_fg_pct",
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

    with open("models/shot_encoders.pkl", "wb") as f:
        pickle.dump({"le_zone": le_zone, "le_area": le_area, "le_action": le_action}, f)

    with open("models/player_stats.pkl", "wb") as f:
        pickle.dump({
            "player_stats": player_stats,
            "zone_stats": zone_stats,
            "league_avg": league_avg,
            "league_3pt_avg": league_3pt_avg,
            "zone_league_avgs": zone_league_avgs
        }, f)

    print("\nShot model, encoders, and player stats saved to models/")
    return gb

if __name__ == "__main__":
    shots, game_states = load_shot_data()
    context = compute_ingame_context(game_states)
    player_stats, zone_stats, league_avg, league_3pt_avg, zone_league_avgs = compute_player_stats(shots)
    df, le_zone, le_area, le_action = engineer_feats(shots, context, player_stats, zone_stats, league_avg, league_3pt_avg, zone_league_avgs)
    train(df, le_zone, le_area, le_action, player_stats, zone_stats, league_avg, league_3pt_avg, zone_league_avgs)