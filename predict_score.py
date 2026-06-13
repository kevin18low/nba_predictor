import pandas as pd
import numpy as np
from db import get_connection

# seconds in a full regulation game
GAME_SECS = 2880
# seconds in a quarter
QUARTER_SECS = 720
# seconds in an OT period
OT_SECS = 300

# compute each team's average points scored and allowed per game from historical data
def get_team_scoring_averages():
    conn = get_connection()
    games = pd.read_sql_query("""
        SELECT home_team, away_team, home_score, away_score
        FROM games
        WHERE home_score IS NOT NULL AND away_score IS NOT NULL
    """, conn)
    conn.close()

    records = []
    for _, row in games.iterrows():
        records.append({"team": row["home_team"], "scored": row["home_score"], "allowed": row["away_score"]})
        records.append({"team": row["away_team"], "scored": row["away_score"], "allowed": row["home_score"]})

    df = pd.DataFrame(records)
    averages = df.groupby("team").agg(
        avg_scored=("scored", "mean"),
        avg_allowed=("allowed", "mean")
    ).reset_index()

    return averages

# total time elapsed in the game so far in seconds
def get_secs_elapsed(quarter, time_remaining_secs):
    if quarter <= 4:
        secs_elapsed = (quarter - 1) * QUARTER_SECS + (QUARTER_SECS - time_remaining_secs)
    else:
        ot_period = quarter - 4
        secs_elapsed = GAME_SECS + (ot_period - 1) * OT_SECS + (OT_SECS - time_remaining_secs)
    return max(secs_elapsed, 1)  # avoid division by zero

# total seconds remaining in regulation, capped at 0 for OT
def get_total_secs_remaining(quarter, time_remaining_secs):
    if quarter <= 4:
        return (4 - quarter) * QUARTER_SECS + time_remaining_secs
    else:
        return time_remaining_secs
    
# predict the final score given the current game state
# blend: how much to weight season averages vs in-game pace (0 = purely in-game, 1 = purely season average). Lower blend = trusts current game pace more
def predict_score(state, home_team, away_team, blend=0.3):
    quarter = state["quarter"]
    time_remaining_secs = state["time_remaining_secs"]
    home_score = state["home_score"]
    away_score = state["away_score"]

    secs_elapsed = get_secs_elapsed(quarter, time_remaining_secs)
    secs_remaining = get_total_secs_remaining(quarter, time_remaining_secs)

    # in-game scoring rate in points per second
    home_rate_live = home_score / secs_elapsed
    away_rate_live = away_score / secs_elapsed

    # season average scoring rate
    averages = get_team_scoring_averages()
    home_avg = averages[averages["team"] == home_team]["avg_scored"].values
    away_avg = averages[averages["team"] == away_team]["avg_scored"].values

    # fall back to league average if team not found
    league_avg = averages["avg_scored"].mean()
    home_avg = home_avg[0] if len(home_avg) > 0 else league_avg
    away_avg = away_avg[0] if len(away_avg) > 0 else league_avg

    # season average rate (points per second over a full game)
    home_rate_avg = home_avg / GAME_SECS
    away_rate_avg = away_avg / GAME_SECS

    # blend in-game rate with season average
    # early in game -> trust season avg more; late in game -> trust live rate more
    game_progress = 1 - (secs_remaining / GAME_SECS)
    dynamic_blend = blend * (1 - game_progress)  # blend shrinks as game progresses

    home_rate = (1 - dynamic_blend) * home_rate_live + dynamic_blend * home_rate_avg
    away_rate = (1 - dynamic_blend) * away_rate_live + dynamic_blend * away_rate_avg

    # project remaining points
    home_projected = home_score + home_rate * secs_remaining
    away_projected = away_score + away_rate * secs_remaining

    return {
        "home_projected": round(home_projected),
        "away_projected": round(away_projected),
        "home_current": home_score,
        "away_current": away_score,
        "secs_remaining": secs_remaining,
        "game_progress": round(game_progress * 100, 1)
    }

if __name__ == "__main__":
    # test with same scenarios as live_predictor
    scenarios = [
        ("GSW", "LAL", {"quarter": 4, "time_remaining_secs": 180, "home_score": 98, "away_score": 90}),
        ("OKC", "BKN", {"quarter": 4, "time_remaining_secs": 120, "home_score": 102, "away_score": 106}),
        ("NYK", "SAS", {"quarter": 3, "time_remaining_secs": 600, "home_score": 49, "away_score": 76}),
    ]

    for home, away, state in scenarios:
        result = predict_score(state, home, away)
        print(
            f"{away} {result['away_current']} @ {home} {result['home_current']} | "
            f"{result['game_progress']}% complete\n"
            f"Projected final: {away} {result['away_projected']} - {home} {result['home_projected']}\n"
        )