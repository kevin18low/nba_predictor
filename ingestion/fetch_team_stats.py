import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import argparse
import time
from nba_api.stats.endpoints import leaguedashteamstats
from nba_api.stats.static import teams as nba_teams
from ingestion.db import get_connection

DEFAULT_SEASONS = ["2023-24", "2024-25", "2025-26"]

# build a lookup from team_id -> abbreviation using the static teams list
def id_to_abbrev():
    return {t["id"]: t["abbreviation"] for t in nba_teams.get_teams()}

# fetch advanced team stats for a season and store in team_stats table
def fetch_and_store_team_stats(season="2025-26"):
    print(f"Fetching team stats for {season}...")

    id_map = id_to_abbrev()

    df = leaguedashteamstats.LeagueDashTeamStats(
        season=season,
        measure_type_detailed_defense="Advanced",
        per_mode_detailed="PerGame",
    ).get_data_frames()[0]

    conn = get_connection()
    cursor = conn.cursor()
    inserted = 0

    for _, row in df.iterrows():
        abbrev = id_map.get(row["TEAM_ID"])
        if abbrev is None:
            print(f"Unknown team_id {row['TEAM_ID']}, skipping")
            continue

        cursor.execute("""
            INSERT INTO team_stats (season, team, off_rating, def_rating, pace)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(season, team) DO UPDATE SET
                off_rating = excluded.off_rating,
                def_rating = excluded.def_rating,
                pace       = excluded.pace
        """, (
            season,
            abbrev,
            float(row["OFF_RATING"]),
            float(row["DEF_RATING"]),
            float(row["PACE"]),
        ))
        inserted += 1

    conn.commit()
    conn.close()
    print(f"Stored stats for {inserted} teams ({season}).")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch and store advanced team stats for one or more seasons.")
    parser.add_argument(
        "seasons",
        nargs="*",
        default=DEFAULT_SEASONS,
        help='Seasons like "2025-26" (default: %(default)s)',
    )
    args = parser.parse_args()

    for i, season in enumerate(args.seasons):
        if i > 0:
            time.sleep(1)
        fetch_and_store_team_stats(season=season)
