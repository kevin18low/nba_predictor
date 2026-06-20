import time
import threading
import pandas as pd
from ingestion.db import get_connection
from live.live_predictor import load_model, build_features, predict, get_team_winrates, get_todays_games, fetch_actions
from live.live_data import get_live_game_states, get_new_shot_events
from prediction.predict_shot import load_shot_model, load_encoders, load_player_stats, predict_shot_probability
from prediction.predict_score import predict_score
from prediction.train_win_probability import compute_winrates
from state import app_state, _lock

# live state checking interval in seconds
POLL_INTERVAL = 10

def poll_loop():
    print("[poller] Loading models...")
    win_model = load_model()
    shot_model = load_shot_model()
    le_zone, le_area, le_action = load_encoders()
    player_stats, zone_stats, league_avg, league_3pt_avg, zone_league_avgs = load_player_stats()

    print("[poller] Computing team win rates...")
    win_rates = compute_winrates()
    conn = get_connection()
    games_df = pd.read_sql_query("SELECT game_id, game_date, home_team, away_team FROM games", conn)
    conn.close()
    team_wr = get_team_winrates(win_rates, games_df)

    print("[poller] Ready. Starting poll loop.")

    while True:
        try:
            games = get_todays_games()

            with _lock:
                app_state["games"] = games

            for game in games:
                game_id = game["game_id"]
                home_team = game["home_team"]
                away_team = game["away_team"]

                actions = fetch_actions(game_id)
                if actions is None:
                    continue

                state = get_live_game_states(actions)
                if state is None:
                    continue

                # initialise per-game shot tracking on first sight
                with _lock:
                    if game_id not in app_state["shot_state"]:
                        app_state["shot_state"][game_id] = {"seen": set(), "players": {}}
                    if game_id not in app_state["game_data"]:
                        app_state["game_data"][game_id] = {
                            "home_team": home_team,
                            "away_team": away_team,
                            "game_state": None,
                            "home_win_prob": None,
                            "score_prediction": None,
                            "shots": [],
                            "last_updated": None,
                        }
                    gs = app_state["shot_state"][game_id]

                new_shots = get_new_shot_events(actions, gs["seen"])

                enriched_shots = []
                for shot in new_shots:
                    gs["seen"].add(shot["action_number"])

                    pid = shot["person_id"]
                    ps = gs["players"].setdefault(pid, {"count": 0, "made": 0, "last3": []})

                    shots_taken = ps["count"]
                    fg_pct_tonight = ps["made"] / ps["count"] if ps["count"] > 0 else 0.45
                    hot_hand = sum(ps["last3"])

                    prob = None
                    if shot["x"] is not None and shot["y"] is not None and shot["shot_distance"] is not None:
                        prob = predict_shot_probability(
                            shot_model, le_zone, le_area, le_action,
                            player_stats, zone_stats, league_avg, league_3pt_avg, zone_league_avgs,
                            player_id=pid,
                            x=shot["x"], y=shot["y"],
                            shot_distance=shot["shot_distance"],
                            action_type=shot["action_type"] or "Jump Shot",
                            shots_taken=shots_taken,
                            fg_pct_tonight=fg_pct_tonight,
                            hot_hand=hot_hand,
                        )

                    made_int = 1 if shot["shot_result"] == "Made" else 0
                    ps["count"] += 1
                    ps["made"] += made_int
                    ps["last3"].append(made_int)
                    if len(ps["last3"]) > 3:
                        ps["last3"].pop(0)

                    enriched_shots.append({**shot, "probability": prob})

                home_wr = team_wr.get(home_team, 0.5)
                away_wr = team_wr.get(away_team, 0.5)
                feats = build_features(state, home_wr, away_wr)
                win_prob = predict(win_model, feats)
                score_pred = predict_score(state, home_team, away_team)

                with _lock:
                    app_state["game_data"][game_id]["game_state"] = state
                    app_state["game_data"][game_id]["home_win_prob"] = win_prob
                    app_state["game_data"][game_id]["score_prediction"] = score_pred
                    app_state["game_data"][game_id]["shots"].extend(enriched_shots)
                    app_state["game_data"][game_id]["last_updated"] = time.time()

        except Exception as e:
            print(f"[poller] Error: {e}")

        time.sleep(POLL_INTERVAL)


def start_poller():
    t = threading.Thread(target=poll_loop, daemon=True)
    t.start()
