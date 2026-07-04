import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from prediction.predict_shot import (
    load_shot_model, load_encoders, load_player_stats,
    coord_to_zone, predict_shot_probability,
)

CURRY = 201939
GOBERT = 203497

if __name__ == "__main__":
    model = load_shot_model()
    le_zone, le_area, le_action = load_encoders()
    player_stats, zone_stats, league_avg, league_3pt_avg, zone_league_avgs = load_player_stats()

    def predict(player_id, x, y, dist, action="Jump Shot", **ctx):
        return predict_shot_probability(
            model, le_zone, le_area, le_action, player_stats, zone_stats,
            league_avg, league_3pt_avg, zone_league_avgs,
            player_id=player_id, x=x, y=y, shot_distance=dist, action_type=action, **ctx)

    print("Zone mapping sanity check")
    spots = [
        (0, 5, 2), (30, 70, 7), (0, 150, 15), (120, 100, 16),
        (230, 50, 23), (-230, 50, 23), (0, 260, 26), (150, 220, 27),
    ]
    for x, y, dist in spots:
        zone, area = coord_to_zone(x, y, dist)
        print(f"({x:>4}, {y:>3}) {dist:>2}ft -> {zone}, {area}")

    print("\nCurry: distance sweep straight up the middle")
    for dist in [2, 6, 10, 15, 20, 24, 28, 32]:
        y = dist * 10  # straight-on shots: y roughly tracks distance
        p = predict(CURRY, x=0, y=y, dist=dist)
        bar = "#" * round(p * 40)
        print(f"{dist:>2}ft: {p:6.1%}  {bar}")

    print("\nSame 3-pointer, different context (Curry, top of key 26ft)")
    print(f"Cold start (first shot): {predict(CURRY, 0, 260, 26):.1%}")
    print(f"Hot hand (3 straight): {predict(CURRY, 0, 260, 26, shots_taken=12, fg_pct_tonight=0.60, hot_hand=3):.1%}")
    print(f"Cold night (3/14): {predict(CURRY, 0, 260, 26, shots_taken=14, fg_pct_tonight=0.21, hot_hand=0):.1%}")

    print("\nShooter vs big man at the same spots")
    for label, x, y, dist, action in [
        ("Restricted area dunk", 0, 8, 1, "Dunk Shot"),
        ("Mid-range 18ft", 0, 180, 18, "Jump Shot"),
        ("Above the break 3", 0, 260, 26, "Jump Shot"),
    ]:
        pc = predict(CURRY, x, y, dist, action)
        pg = predict(GOBERT, x, y, dist, action)
        print(f"{label:<22} Curry {pc:6.1%} | Gobert {pg:6.1%}")
