import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from prediction.predict_score import predict_score

def show(label, home, away, state):
    result = predict_score(state, home, away)
    mins = int(state["time_remaining_secs"] // 60)
    secs = int(state["time_remaining_secs"] % 60)
    print(f"{label}")
    print(f"{away} {state['away_score']} @ {home} {state['home_score']} | "
          f"Q{state['quarter']} {mins}:{secs:02d} ({result['game_progress']}% complete)")
    print(f"Projected final: {away} {result['away_projected']} - {home} {result['home_projected']}\n")

if __name__ == "__main__":
    show("Early game, even pace", "BOS", "MIA",
         {"quarter": 1, "time_remaining_secs": 360, "home_score": 15, "away_score": 14})
    show("Halftime, even pace", "BOS", "MIA",
         {"quarter": 2, "time_remaining_secs": 0, "home_score": 60, "away_score": 56})
    show("Late game, even pace", "BOS", "MIA",
         {"quarter": 4, "time_remaining_secs": 300, "home_score": 105, "away_score": 98})

    show("Hot start (unsustainable pace)", "IND", "WAS",
         {"quarter": 1, "time_remaining_secs": 600, "home_score": 18, "away_score": 4})

    show("Defensive game", "ORL", "DET",
         {"quarter": 3, "time_remaining_secs": 300, "home_score": 55, "away_score": 51})

    show("Fourth quarter blowout", "OKC", "CHA",
         {"quarter": 4, "time_remaining_secs": 480, "home_score": 112, "away_score": 78})

    show("Overtime, tied", "DEN", "MIN",
         {"quarter": 5, "time_remaining_secs": 180, "home_score": 118, "away_score": 118})

    show("Game over (0:00 in Q4)", "NYK", "PHI",
         {"quarter": 4, "time_remaining_secs": 0, "home_score": 101, "away_score": 97})
