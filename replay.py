import pandas as pd
from db import get_connection
from predict_shot import load_shot_model, load_encoders, load_player_stats, predict_shot_probability
from live_predictor import load_model, build_features, predict, get_team_winrates
from train_win_probability import compute_winrates
from state import app_state, _lock

_featured_games = None

def get_featured_games():
    global _featured_games
    if _featured_games is not None:
        return _featured_games

    conn = get_connection()
    rows = pd.read_sql_query("""
        SELECT g.game_id, g.game_date, g.home_team, g.away_team
        FROM games g
        WHERE g.home_score IS NOT NULL
        AND EXISTS (
            SELECT 1 FROM game_states gs
            WHERE gs.game_id = g.game_id
            AND gs.x IS NOT NULL
            AND gs.shot_result IS NOT NULL
        )
        ORDER BY g.game_date DESC
        LIMIT 12
    """, conn)
    conn.close()

    _featured_games = rows.to_dict(orient="records")
    return _featured_games

_models = None

def _load_models():
    global _models
    if _models is not None:
        return _models

    print("[replay] Loading models...")
    win_model = load_model()
    shot_model = load_shot_model()
    le_zone, le_area, le_action = load_encoders()
    player_stats, zone_stats, league_avg, league_3pt_avg, zone_league_avgs = load_player_stats()

    win_rates = compute_winrates()
    conn = get_connection()
    games_df = pd.read_sql_query("SELECT game_id, game_date, home_team, away_team FROM games", conn)
    conn.close()
    team_wr = get_team_winrates(win_rates, games_df)

    _models = {
        "win_model": win_model,
        "shot_model": shot_model,
        "le_zone": le_zone, "le_area": le_area, "le_action": le_action,
        "player_stats": player_stats, "zone_stats": zone_stats,
        "league_avg": league_avg, "league_3pt_avg": league_3pt_avg,
        "zone_league_avgs": zone_league_avgs,
        "team_wr": team_wr,
    }
    print("[replay] Models ready.")
    return _models

# load all shot events for a game, compute shot probabilities, and track win probability as game progresses
# results cached in app_state["replays"]
def build_replay(game_id, home_team, away_team):
    with _lock:
        if game_id in app_state["replays"]:
            return app_state["replays"][game_id]

    print(f"[replay] Building replay for {away_team} @ {home_team} ({game_id})...")
    m = _load_models()

    conn = get_connection()
    events = pd.read_sql_query("""
        SELECT quarter, time_remaining_secs, home_score, away_score, person_id, player_name, team_tricode, shot_result, x, y, shot_distance
        FROM game_states
        WHERE game_id = ?
        AND shot_result IS NOT NULL
        AND x IS NOT NULL
        AND y IS NOT NULL
        AND person_id IS NOT NULL
        AND person_id != 0
        ORDER BY quarter ASC, time_remaining_secs DESC
    """, conn, params=(game_id,))

    conn.close()

    home_wr = m["team_wr"].get(home_team, 0.5)
    away_wr = m["team_wr"].get(away_team, 0.5)

    player_state = {}

    timeline = []
    for _, row in events.iterrows():
        pid = int(row["person_id"])
        ps = player_state.setdefault(pid, {"count": 0, "made": 0, "last3": []})

        shots_taken = ps["count"]
        fg_pct_tonight = ps["made"] / ps["count"] if ps["count"] > 0 else 0.45
        hot_hand = sum(ps["last3"])

        shot_prob = predict_shot_probability(
            m["shot_model"], m["le_zone"], m["le_area"], m["le_action"],
            m["player_stats"], m["zone_stats"],
            m["league_avg"], m["league_3pt_avg"], m["zone_league_avgs"],
            player_id=pid,
            x=float(row["x"]), y=float(row["y"]),
            shot_distance=float(row["shot_distance"]),
            action_type="Jump Shot", 
            shots_taken=shots_taken,
            fg_pct_tonight=fg_pct_tonight,
            hot_hand=hot_hand,
        )

        state = {
            "quarter": int(row["quarter"]),
            "time_remaining_secs": float(row["time_remaining_secs"]),
            "home_score": int(row["home_score"]),
            "away_score": int(row["away_score"]),
            "score_diff": int(row["home_score"]) - int(row["away_score"]),
        }
        feats = build_features(state, home_wr, away_wr)
        win_prob = float(predict(m["win_model"], feats))

        made_int = 1 if row["shot_result"] == "Made" else 0
        ps["count"] += 1
        ps["made"] += made_int
        ps["last3"].append(made_int)
        if len(ps["last3"]) > 3:
            ps["last3"].pop(0)

        timeline.append({
            "quarter": state["quarter"],
            "time_remaining_secs": state["time_remaining_secs"],
            "home_score": state["home_score"],
            "away_score": state["away_score"],
            "home_win_prob": win_prob,
            "away_win_prob": round(1 - win_prob, 4),
            "player_name": row["player_name"],
            "team_tricode": row.get("team_tricode"),
            "person_id": pid,
            "x": float(row["x"]),
            "y": float(row["y"]),
            "shot_distance": float(row["shot_distance"]),
            "shot_result": row["shot_result"],
            "shot_prob": round(shot_prob, 4),
        })

    result = {
        "game_id": game_id,
        "home_team": home_team,
        "away_team": away_team,
        "events": timeline,
    }

    with _lock:
        app_state["replays"][game_id] = result

    print(f"[replay] Done — {len(timeline)} events.")
    return result
