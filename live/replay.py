import time
import threading
import pandas as pd
from ingestion.db import get_connection
from ingestion.fetch_playbyplay import parse_time
from prediction.predict_shot import load_shot_model, load_encoders, load_player_stats, predict_shot_probability
from live.live_data import get_recent_final_games
from live.live_predictor import load_model, build_features, predict, get_team_winrates, fetch_actions
from prediction.train_win_probability import compute_winrates
from state import app_state, _lock

FEATURED_LIMIT = 12
FEATURED_TTL = 300 # seconds before re-checking the NBA schedule for newly finished games

_featured_games = None
_featured_fetched_at = 0
_featured_lock = threading.Lock()

# most recent finished games from the NBA schedule, cached for FEATURED_TTL
# If the schedule can't be reached, keep the last good list, or use the database on a cold start
def get_featured_games():
    global _featured_games, _featured_fetched_at

    with _featured_lock:
        if _featured_games is not None and time.time() - _featured_fetched_at < FEATURED_TTL:
            return _featured_games

        try:
            games = get_recent_final_games(FEATURED_LIMIT)
        except Exception as e:
            print(f"[replay] Could not fetch recent games: {e}")
            games = []

        if games:
            _featured_games = games
        elif _featured_games is None:
            _featured_games = _featured_games_from_db()

        _featured_fetched_at = time.time()
        return _featured_games

def _featured_games_from_db():
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
        LIMIT ?
    """, conn, params=(FEATURED_LIMIT,))
    conn.close()

    return rows.to_dict(orient="records")

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

# shot events stored in the database (games that have been through ingestion)
def _shot_events_from_db(game_id):
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
    return events

# same shot events, built from the NBA's play-by-play feed for games not in the database
def _shot_events_from_live_feed(game_id):
    rows = []
    for action in fetch_actions(game_id) or []:
        if action.get("shotResult") not in ("Made", "Missed"):
            continue
        if not action.get("personId") or action.get("xLegacy") is None or action.get("yLegacy") is None:
            continue

        rows.append({
            "quarter": action["period"],
            "time_remaining_secs": parse_time(action["clock"]),
            "home_score": int(action["scoreHome"]),
            "away_score": int(action["scoreAway"]),
            "person_id": action["personId"],
            "player_name": action.get("playerNameI") or action.get("playerName"),
            "team_tricode": action.get("teamTricode"),
            "shot_result": action["shotResult"],
            "x": action["xLegacy"],
            "y": action["yLegacy"],
            "shot_distance": round(action.get("shotDistance") or 0), # whole feet, like the database
        })
    return pd.DataFrame(rows)

# load all shot events for a game, compute shot probabilities, and track win probability as game progresses
# results cached in app_state["replays"]
def build_replay(game_id, home_team, away_team):
    with _lock:
        if game_id in app_state["replays"]:
            return app_state["replays"][game_id]

    print(f"[replay] Building replay for {away_team} @ {home_team} ({game_id})...")
    m = _load_models()

    events = _shot_events_from_db(game_id)
    if events.empty:
        events = _shot_events_from_live_feed(game_id)

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

    # an empty timeline means the feed failed: don't cache it, so the next visit retries
    if timeline:
        with _lock:
            app_state["replays"][game_id] = result

    print(f"[replay] Done — {len(timeline)} events.")
    return result
