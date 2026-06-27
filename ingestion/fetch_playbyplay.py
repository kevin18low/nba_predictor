import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import time
from nba_api.stats.endpoints import playbyplayv3
from ingestion.db import get_connection

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
def get_play_by_play(game_id, home_win, conn):
    try:
        play_by_play = playbyplayv3.PlayByPlayV3(game_id=game_id)
        df = play_by_play.get_data_frames()[0]
    except Exception as e:
        print(f"Failed to fetch game {game_id}: {e}")
        return 0
    
    # keep rows that either update the score or are shot attempts
    df = df[
        (df["scoreHome"].notna() & (df["scoreHome"] != "")) |
        (df["shotResult"].notna() & (df["shotResult"] != ""))
    ].copy()

    # forward fill scores so every row has the current score
    df["scoreHome"] = df["scoreHome"].replace("", None)
    df["scoreAway"] = df["scoreAway"].replace("", None)
    df[["scoreHome", "scoreAway"]] = df[["scoreHome", "scoreAway"]].ffill()

    # drop rows still missing scores (before first score of the game)
    df = df[df["scoreHome"].notna()].copy()

    if df.empty:
        return 0
    
    cursor = conn.cursor()
    rows_to_insert = []

    for _, row in df.iterrows():
        try:
            home_score = int(row["scoreHome"])
            away_score = int(row["scoreAway"])
            score_diff = home_score - away_score
            quarter = int(row["period"])
            time_remaining_secs = parse_time(row["clock"])

            if time_remaining_secs is None:
                continue

            player_name = row.get("playerName") or None
            person_id = int(row["personId"]) if row.get("personId") not in (None, "") else None
            team_tricode = row.get("teamTricode") or None
            action_type = row.get("actionType") or None
            shot_result = row.get("shotResult") or None
            x = float(row["xLegacy"]) if row.get("xLegacy") not in (None, "") else None
            y = float(row["yLegacy"]) if row.get("yLegacy") not in (None, "") else None
            shot_distance = float(row["shotDistance"]) if row.get("shotDistance") not in (None, "") else None

            rows_to_insert.append((
                game_id, quarter, time_remaining_secs,
                home_score, away_score, score_diff, home_win,
                player_name, person_id, team_tricode, action_type, shot_result,
                x, y, shot_distance
            ))
        except Exception as e:
            continue

    if not rows_to_insert:
        return 0

    cursor = conn.cursor()
    cursor.executemany("""
        INSERT INTO game_states
        (game_id, quarter, time_remaining_secs, home_score, away_score, score_diff, home_win, player_name, person_id, team_tricode, action_type, shot_result, x, y, shot_distance)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows_to_insert)
    conn.commit()
    
    return len(rows_to_insert)

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

    if limit:
        games = games[:limit]

    print(f"Processing {len(games)} games' play-by-play stats.")

    for i, game in enumerate(games):
        game_id = game["game_id"]
        home_win = game["home_win"]

        rows = get_play_by_play(game_id, home_win, conn)
        print(f"[{i+1}/{len(games)}] {game_id}: {rows} states stored")
        time.sleep(0.2)

    conn.close()

if __name__ == "__main__":
    process_games()