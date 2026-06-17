from db import get_connection
from train_win_probability import compute_winrates
from live_predictor import load_model, build_features, predict, get_team_winrates
from predict_score import predict_score
import pandas as pd

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
    model = load_model()
    win_rates = compute_winrates()
    
    conn = get_connection()
    games = pd.read_sql_query("SELECT game_id, game_date, home_team, away_team FROM games", conn)
    conn.close()
    
    team_wr = get_team_winrates(win_rates, games)

    test_prediction(
        home_team="GSW",
        away_team="LAL",
        quarter=4,
        time_remaining_secs=180,
        home_score=98,
        away_score=90,
        model=model,
        team_wr=team_wr
    )
    test_prediction(
        home_team="OKC",
        away_team="BKN",
        quarter=4,
        time_remaining_secs=120,
        home_score=102,
        away_score=106,
        model=model,
        team_wr=team_wr
    )
    test_prediction(
        home_team="NYK",
        away_team="SAS",
        quarter=3,
        time_remaining_secs=600,
        home_score=49,
        away_score=76,
        model=model,
        team_wr=team_wr
    )