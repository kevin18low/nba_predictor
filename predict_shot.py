import pickle
import pandas as pd

def load_shot_model():
    with open("models/shot_model.pkl", "rb") as f:
        model = pickle.load(f)
    return model

def load_encoders():
    with open("models/shot_encoders.pkl", "rb") as f:
        enc = pickle.load(f)
    return enc["le_zone"], enc["le_area"], enc["le_action"]

def load_player_stats():
    with open("models/player_stats.pkl", "rb") as f:
        data = pickle.load(f)
    return data["player_stats"], data["zone_stats"], data["league_avg"], data["league_3pt_avg"], data["zone_league_avgs"]

# map raw (x, y) distance to specified zone names and court regions
def coord_to_zone(x, y, shot_distance):
    def get_area(x):
        if x <= -150:
            return "Left Side(L)"
        elif x < -50:
            return "Left Side Center(LC)"
        elif x <= 50:
            return "Center(C)"
        elif x < 150:
            return "Right Side Center(RC)"
        else:
            return "Right Side(R)"

    if shot_distance <= 4:
        return "Restricted Area", "Center(C)"

    if shot_distance <= 8:
        return "In The Paint (Non-RA)", get_area(x)

    if abs(x) >= 220 and y <= 90:
        if x > 0:
            return "Right Corner 3", "Right Side(R)"
        else:
            return "Left Corner 3", "Left Side(L)"

    if shot_distance >= 22:
        return "Above the Break 3", get_area(x)

    if shot_distance < 22:
        return "Mid-Range", get_area(x)

    # half-court heave
    return "Backcourt", "Back Court(BC)"

# predict probability of a shot going in based on player information, shot location, and in-game context
def predict_shot_probability(model, le_zone, le_area, le_action, player_stats, zone_stats, league_avg, league_3pt_avg, zone_league_avgs,
                             player_id, x, y, shot_distance, action_type,
                             shots_taken=0, fg_pct_tonight=0.45, hot_hand=0, is_three=None):
    zone, area = coord_to_zone(x, y, shot_distance)

    zone_enc = le_zone.transform([zone])[0] if zone in le_zone.classes_ else 0
    area_enc = le_area.transform([area])[0] if area in le_area.classes_ else 0

    fallback_action = "Jump Shot" if "Jump Shot" in le_action.classes_ else le_action.classes_[0]
    action_enc = le_action.transform([action_type])[0] if action_type in le_action.classes_ else le_action.transform([fallback_action])[0]

    if is_three is None:
        is_three = 1 if shot_distance >= 22 else 0

    pstats = player_stats.get(player_id, {})
    player_overall_fg_pct = pstats.get("overall_fg_pct", league_avg)
    player_3pt_pct = pstats.get("three_pt_pct", league_3pt_avg)
    if (player_id, zone) in zone_stats:
        player_zone_fg_pct = zone_stats[(player_id, zone)]
    elif is_three:
        player_zone_fg_pct = player_3pt_pct
    else:
        player_zone_fg_pct = zone_league_avgs.get(zone, league_avg)

    features = pd.DataFrame([{
        "x": x,
        "y": y,
        "abs_x": abs(x),
        "shot_distance": shot_distance,
        "distance_sq": shot_distance ** 2,
        "zone_enc": zone_enc,
        "area_enc": area_enc,
        "action_enc": action_enc,
        "is_three": is_three,
        "player_overall_fg_pct": player_overall_fg_pct,
        "player_3pt_pct": player_3pt_pct,
        "player_zone_fg_pct": player_zone_fg_pct,
        "shots_taken": shots_taken,
        "fg_pct_tonight": fg_pct_tonight,
        "hot_hand": hot_hand
    }])

    prob = model.predict_proba(features)[0]
    return prob[1]  # probability of make

if __name__ == "__main__":
    print("Loading shot model...")
    model = load_shot_model()

    print("Loading encoders and player stats...")
    le_zone, le_area, le_action = load_encoders()
    player_stats, zone_stats, league_avg, league_3pt_avg, zone_league_avgs = load_player_stats()

    def predict(player_id, x, y, shot_distance, action_type, shots_taken=0, fg_pct_tonight=0.45, hot_hand=0):
        return predict_shot_probability(
            model, le_zone, le_area, le_action, player_stats, zone_stats, league_avg, league_3pt_avg, zone_league_avgs,
            player_id=player_id, x=x, y=y, shot_distance=shot_distance, action_type=action_type,
            shots_taken=shots_taken, fg_pct_tonight=fg_pct_tonight, hot_hand=hot_hand
        )

    print("\n- Curry: Standard 26ft 3-pointer (top of key) -")
    print(f"Probability: {predict(201939, x=0, y=260, shot_distance=26, action_type='Jump Shot'):.1%}")

    print("\n- Curry: Corner 3 -")
    print(f"Probability: {predict(201939, x=225, y=50, shot_distance=23, action_type='Jump Shot'):.1%}")

    print("\n- Gobert: Restricted area dunk -")
    print(f"Probability: {predict(203497, x=0, y=8, shot_distance=0, action_type='Dunk Shot'):.1%}")

    print("\n- Gobert: Paint shot (non-restricted area) -")
    print(f"Probability: {predict(203497, x=30, y=70, shot_distance=7, action_type='Jump Shot'):.1%}")

    print("\n- Gobert: Same 26ft 3-pointer as Curry's -")
    print(f"Probability: {predict(203497, x=0, y=260, shot_distance=26, action_type='Jump Shot'):.1%}")

    print("\n- SGA: Restricted area layup -")
    print(f"Probability: {predict(1628983, x=10, y=30, shot_distance=3, action_type='Layup Shot'):.1%}")

    print("\n- SGA: Mid-range pull-up (top of key, 18ft) -")
    print(f"Probability: {predict(1628983, x=0, y=180, shot_distance=18, action_type='Pull Up Jump shot'):.1%}")

    print("\n- SGA: Above the break 3 (wing, 26ft) -")
    print(f"Probability: {predict(1628983, x=200, y=160, shot_distance=26, action_type='Pull Up Jump shot'):.1%}")

    print("\n- SGA: Corner 3 -")
    print(f"Probability: {predict(1628983, x=220, y=50, shot_distance=23, action_type='Jump Shot'):.1%}")

    print("\n- Giannis: Restricted area dunk -")
    print(f"Probability: {predict(203507, x=0, y=8, shot_distance=0, action_type='Dunk Shot'):.1%}")

    print("\n- Giannis: Paint shot (non-RA, driving hook) -")
    print(f"Probability: {predict(203507, x=40, y=80, shot_distance=8, action_type='Hook Shot'):.1%}")

    print("\n- Giannis: Mid-range (elbow, 16ft) -")
    print(f"Probability: {predict(203507, x=120, y=100, shot_distance=16, action_type='Jump Shot'):.1%}")

    print("\n- Giannis: Above the break 3 -")
    print(f"Probability: {predict(203507, x=0, y=260, shot_distance=26, action_type='Jump Shot'):.1%}")

    print("\n- Robinson: Restricted area dunk -")
    print(f"Probability: {predict(1629011, x=0, y=8, shot_distance=0, action_type='Dunk Shot'):.1%}")

    print("\n- Robinson: Paint putback (non-RA) -")
    print(f"Probability: {predict(1629011, x=20, y=70, shot_distance=7, action_type='Layup Shot'):.1%}")

    print("\n- Robinson: Above the break 3 (for reference) -")
    print(f"Probability: {predict(1629011, x=0, y=260, shot_distance=26, action_type='Jump Shot'):.1%}")

    print("\n- Shamet: Above the break 3 (catch and shoot) -")
    print(f"Probability: {predict(1629013, x=0, y=260, shot_distance=26, action_type='Jump Shot'):.1%}")

    print("\n- Shamet: Corner 3 (catch and shoot) -")
    print(f"Probability: {predict(1629013, x=220, y=50, shot_distance=23, action_type='Jump Shot'):.1%}")

    print("\n- Shamet: Mid-range pull-up -")
    print(f"Probability: {predict(1629013, x=0, y=180, shot_distance=18, action_type='Pull Up Jump shot'):.1%}")