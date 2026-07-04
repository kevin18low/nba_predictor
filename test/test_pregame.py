import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from prediction.predict_pregame import predict_pregame, load_pregame_model

def show(home, away, model):
    r = predict_pregame(home, away, model=model)
    print(f"{r['away_team']} (Elo {r['away_elo']}) @ {r['home_team']} (Elo {r['home_elo']})"
          f"-> {r['home_team']} {r['home_win_prob']:.1%} | {r['away_team']} {r['away_win_prob']:.1%}")

if __name__ == "__main__":
    model = load_pregame_model()

    print("Lopsided matchups (favorite at home)")
    show("OKC", "WAS", model)
    show("SAS", "CHA", model)
    show("CLE", "UTA", model)

    print("\nMirror check: same pairing, home court flipped")
    show("DEN", "LAL", model)
    show("LAL", "DEN", model)

    print("\nEvenly matched (expect near 50/50 with home edge)")
    show("PHI", "TOR", model)
    show("TOR", "PHI", model)

    print("\nUnderdog at home")
    show("WAS", "OKC", model)
    show("CHA", "SAS", model)
