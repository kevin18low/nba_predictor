import time
import pandas as pd
from nba_api.stats.endpoints import playbyplayv3
from db import get_connection

# convert ISO 8601 clock format 'PT05M42.00S' to seconds
def parse_time(clock_str):
    try:
        clock_str = clock_str.replace("PT", "") # remove PT prefix
        mins, secs = clock_str.split("M")
        secs = secs.replace("S", "")
        return int(mins) * 60 + float(secs)
    except:
        return None
    
# fetch play-by-play stats for one game and store individual game moments
def get_play_by_play(game_id, home_win):
    try:
        play_by_play = playbyplayv3.PlayByPlayV3(game_id=game_id)
        df = play_by_play.get_data_frames()[0]
    except Exception as e:
        print(f"Failed to fetch game {game_id}: {e}")
        return 0
    
    df = df[df["scoreHome"].notna() & df["scoreAway"].notna()].copy()
    df = df[df["scoreHome"] != ""].copy()

    if df.empty:
        return 0
    
    conn = get_connection()
    cursor = conn.cursor()
    inserted = 0

    for _, row in df.iterrows():
        try:
            home_score = int(row["scoreHome"])
            away_score = int(row["scoreAway"])
            score_diff = home_score - away_score
            quarter = int(row["period"])
            time_remaining_secs = parse_time(row["clock"])

            if time_remaining_secs is None:
                continue

            # columns may be empty for non-shot events
            player_name  = row.get("playerName") or None
            action_type  = row.get("actionType") or None
            shot_result  = row.get("shotResult") or None
            x = float(row["xLegacy"]) if row.get("xLegacy") not in (None, "") else None
            y = float(row["yLegacy"]) if row.get("yLegacy") not in (None, "") else None
            shot_distance = float(row["shotDistance"]) if row.get("shotDistance") not in (None, "") else None

            cursor.execute("""
                INSERT INTO game_states 
                (game_id, quarter, time_remaining_secs, home_score, away_score, score_diff, home_win, player_name, action_type, shot_result, x, y, shot_distance)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                game_id,
                quarter,
                time_remaining_secs,
                home_score,
                away_score,
                score_diff,
                home_win,
                player_name,
                action_type,
                shot_result,
                x,
                y,
                shot_distance
            ))
            inserted += 1
        except Exception as e:
            continue

    conn.commit()
    conn.close()
    return inserted

# process play-by-play for all games in the games table
def process_games(limit=None):
    conn = get_connection()
    cursor = conn.cursor()

    games = cursor.execute("""
        SELECT g.game_id, g.home_win
        FROM games g
        WHERE NOT EXISTS (
            SELECT 1 
            FROM game_states gs
            WHERE gs.game_id = g.game_id
        )     
    """).fetchall()
    conn.close()

    if limit:
        games = games[:limit]

    print(f"Processing {len(games)} games' play-by-play stats.")

    for i, game in enumerate(games):
        game_id = game["game_id"]
        home_win = game["home_win"]

        rows = get_play_by_play(game_id, home_win)
        print(f"  [{i+1}/{len(games)}] {game_id}: {rows} states stored")
        time.sleep(0.2)

if __name__ == "__main__":
    process_games()