import time
from nba_api.stats.endpoints import leaguegamefinder
from db import get_connection


# fetch and store all games for a given season in the games table
def fetch_and_store_games(season="2025-26", season_type="Regular Season"):
    print(f"Fetching games from the {season} {season_type}.")

    gamefinder = leaguegamefinder.LeagueGameFinder(
        season_nullable=season,
        season_type_nullable=season_type,
        league_id_nullable="00" # 00 = NBA
    )

    df = gamefinder.get_data_frames()[0]

    # format: Home vs. Away, Away @ Home. Keep only home games to avoid duplicates
    df = df[df["MATCHUP"].str.contains(r"vs\.")].copy() 

    df = df[[
        "GAME_ID", "GAME_DATE", "TEAM_ABBREVIATION", "MATCHUP", "WL", "PTS", "PLUS_MINUS"
    ]].copy()

    conn = get_connection()
    cursor = conn.cursor()
    inserted = 0

    for _, row in df.iterrows():
        away_team = row["MATCHUP"].split("vs. ")[-1].strip() # get away team name from matchup string. Ex. "LAL vs. GSW"
        home_team = row["TEAM_ABBREVIATION"]
        home_win = 1 if row["WL"] == "W" else 0

        try:
            cursor.execute("""
                INSERT OR IGNORE INTO games 
                (game_id, game_date, home_team, away_team, home_score, away_score, home_win)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                row["GAME_ID"],
                row["GAME_DATE"],
                home_team,
                away_team,
                int(row["PTS"]),
                int(row["PTS"]) - int(row["PLUS_MINUS"]),
                home_win
            ))
            inserted += 1
        except Exception as e:
            print(f"Skipping game {row['GAME_ID']}: {e}")

    conn.commit()
    conn.close()
    print(f"Stored {inserted} games from the {season} {season_type}.")

if __name__ == "__main__":
    fetch_and_store_games(season="2024-25")
    time.sleep(1)
    fetch_and_store_games(season="2025-26")