import time
import pickle
import pandas as pd
from train_win_probability import compute_winrates
from db import get_connection
from predict_score import predict_score
from live_data import get_live_scoreboard, get_live_playbyplay, get_live_game_states

# load saved model
def load_model():
    with open("models/win_prob_model.pkl", "rb") as f:
        model = pickle.load(f)
    return model

# get all games happening today
def get_todays_games():
    games_data = get_live_scoreboard()

    if not games_data:
        print("No games today.")
        return []

    games = []
    for g in games_data:
        games.append({
            "game_id": g["gameId"],
            "home_team": g["homeTeam"]["teamTricode"],
            "away_team": g["awayTeam"]["teamTricode"],
            "status": g["gameStatusText"]
        })

    return games

# get the current game state from live play by play
def get_live_game_state(game_id):
    try:
        actions = get_live_playbyplay(game_id)
        return get_live_game_states(actions)
    except Exception as e:
        print(f"Error fetching game {game_id}: {e}")
        return None

# build feature vector from live game state
def build_features(state, home_win_rate, away_win_rate):
    quarter = state["quarter"]
    time_remaining_secs = state["time_remaining_secs"]
    score_diff = state["score_diff"]
    home_score = state["home_score"]
    away_score = state["away_score"]

    # engineer same feats as used in training
    total_secs_remaining = max(0, (4 - quarter)) * 720 + time_remaining_secs
    if quarter > 4:
        total_secs_remaining = time_remaining_secs

    game_progress = 1 - min(max(total_secs_remaining / 2880, 0), 1)
    total_points = home_score + away_score
    diff_x_progress = score_diff * game_progress
    is_ot = int(quarter > 4)
    close_game = int(abs(score_diff) <= 5 and quarter >= 4)
    winrate_diff = home_win_rate - away_win_rate
    winrate_diff_x_progress = winrate_diff * game_progress

    return pd.DataFrame([{
        "quarter": quarter,
        "time_remaining_secs": time_remaining_secs,
        "score_diff": score_diff,
        "total_secs_remaining": total_secs_remaining,
        "game_progress": game_progress,
        "diff_x_progress": diff_x_progress,
        "total_points": total_points,
        "is_ot": is_ot,
        "close_game": close_game,
        "winrate_diff": winrate_diff,
        "winrate_diff_x_progress": winrate_diff_x_progress
    }])

# get teams' most recent win rates
def get_team_winrates(win_rates, games):
    games_sorted = games.sort_values("game_date", ascending=True)
    wr_merged = games_sorted.merge(win_rates, on="game_id", how="inner")
    
    team_wr = {}
    for _, row in wr_merged.iterrows():
        team_wr[row["home_team"]] = row["home_win_rate"]
        team_wr[row["away_team"]] = row["away_win_rate"]
    
    return team_wr

# predict win probability for home team for a single game state
def predict(model, features):
    prob = model.predict_proba(features)[0]
    return prob[1]

# poll live games every 30 seconds
def run(poll_interval=30):
    print("Loading model...")
    model = load_model()

    print("Loading team win rates...")
    win_rates = compute_winrates()

    conn = get_connection()
    games_df = pd.read_sql_query("SELECT game_id, game_date, home_team, away_team FROM games", conn)
    conn.close()

    team_wr = get_team_winrates(win_rates, games_df)

    print("Fetching today's games...")
    games = get_todays_games()

    if not games:
        return

    print(f"\nFound {len(games)} games today:")
    for game in games:
        print(f"{game['away_team']} @ {game['home_team']} — {game['status']}")

    print(f"\nPolling every {poll_interval}s. Press Ctrl+C to stop.\n")

    while True:
        for game in games:
            game_id = game["game_id"]
            home_team = game["home_team"]
            away_team = game["away_team"]

            state = get_live_game_state(game_id)
            if state is None:
                print(f"{away_team} @ {home_team}: no live data yet")
                continue

            home_wr = team_wr.get(home_team, 0.5)
            away_wr = team_wr.get(away_team, 0.5)

            feats = build_features(state, home_wr, away_wr)
            home_win_prob = predict(model, feats)
            score_prediction = predict_score(state, home_team, away_team)

            q = state["quarter"]
            t = state["time_remaining_secs"]
            mins = int(t // 60)
            secs = int(t % 60)

            print(
                f"{away_team} {state['away_score']} @ "
                f"{home_team} {state['home_score']} | "
                f"Q{q} {mins}:{secs:02d} | "
                f"Home win prob: {home_win_prob:.1%} | "
                f"Projected final score: {away_team} {score_prediction['away_projected']} - {home_team} {score_prediction['home_projected']}"
            )

        print()
        time.sleep(poll_interval)

# simulate a game for when there are no current games
def test_prediction(home_team, away_team, quarter, time_remaining_secs, home_score, away_score, model, team_wr):
    home_wr = team_wr.get(home_team, 0.5)
    away_wr = team_wr.get(away_team, 0.5)

    print(f"{home_team} win rate: {home_wr:.3f}")
    print(f"{away_team} win rate: {away_wr:.3f}")

    state = {
        "quarter": quarter,
        "time_remaining_secs": time_remaining_secs,
        "home_score": home_score,
        "away_score": away_score,
        "score_diff": home_score - away_score
    }

    features = build_features(state, home_wr, away_wr)
    home_win_prob = predict(model, features)
    score_prediction = predict_score(state, home_team, away_team)

    mins = int(time_remaining_secs // 60)
    secs = int(time_remaining_secs % 60)

    print(f"{away_team} {away_score} @ {home_team} {home_score} | Q{quarter} {mins}:{secs:02d}")
    print(f"Home win probability: {home_win_prob:.1%}")
    print(f"Away win probability: {1 - home_win_prob:.1%}")
    print(f"Projected final score: {away_team} {score_prediction['away_projected']} - {home_team} {score_prediction['home_projected']}\n")

if __name__ == "__main__":
    run()