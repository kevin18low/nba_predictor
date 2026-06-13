import time
import pandas as pd
from nba_api.stats.endpoints import shotchartdetail
from db import get_connection

# fetch all shots taken per player
def fetch_player_shots(player_id, player_name, season):
    try:
        shot_chart = shotchartdetail.ShotChartDetail(
            player_id=player_id,
            team_id=0,
            season_nullable=season,
            season_type_all_star="Regular Season",
            context_measure_simple="FGA"
        )
        df = shot_chart.get_data_frames()[0]
    except Exception as e:
        print(f"Failed to fetch {player_name} ({player_id}) {season}: {e}")
        return 0

    if df.empty:
        return 0

    conn = get_connection()
    cursor = conn.cursor()

    rows_to_insert = []
    for _, row in df.iterrows():
        try:
            rows_to_insert.append((
                player_id,
                player_name,
                row["GAME_ID"],
                row["GAME_DATE"],
                season,
                row["TEAM_NAME"],
                row["LOC_X"],
                row["LOC_Y"],
                row["SHOT_DISTANCE"],
                row["SHOT_ZONE_BASIC"],
                row["SHOT_ZONE_AREA"],
                row["SHOT_TYPE"],
                row["ACTION_TYPE"],
                1 if row["SHOT_MADE_FLAG"] == 1 else 0
            ))
        except Exception as e:
            continue

    if not rows_to_insert:
        return 0

    conn = get_connection()
    cursor = conn.cursor()
    cursor.executemany("""
        INSERT INTO shot_attempts 
        (player_id, player_name, game_id, game_date, season, team, x, y, shot_distance, shot_zone, shot_zone_area, shot_type, action_type, made)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows_to_insert)
    conn.commit()
    conn.close()
    return len(rows_to_insert)

# find all unique players
def get_players():
    conn = get_connection()
    players = pd.read_sql_query("""
        SELECT DISTINCT person_id, player_name
        FROM game_states
        WHERE person_id IS NOT NULL
        AND person_id != 0
        AND player_name IS NOT NULL
        AND shot_result IS NOT NULL
        GROUP BY person_id
    """, conn)
    conn.close()
    return players

# fetch shot data across all players
def process_all_players(seasons=["2022-23", "2023-24", "2024-25", "2025-26"]):
    players = get_players()
    print(f"Processing {len(players)} players")

    conn = get_connection()
    already_fetched = pd.read_sql_query("""
        SELECT DISTINCT player_id, season 
        FROM shot_attempts
    """, conn)
    conn.close()

    fetched_set = set(zip(already_fetched["player_id"], already_fetched["season"]))

    total = len(players) * len(seasons)
    done = 0

    for season in seasons:
        for _, player in players.iterrows():
            player_id = player["person_id"]
            player_name = player["player_name"]
            done += 1

            if (player_id, season) in fetched_set:
                continue

            shots = fetch_player_shots(player_id, player_name, season)
            print(f"[{done}/{total}] {player_name} {season}: {shots} shots")
            time.sleep(0.2)

if __name__ == "__main__":
    process_all_players()