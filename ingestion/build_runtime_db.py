import os
import sqlite3

# Build a slim data/runtime.db for deployment.
# The full nba.db is ~300 MB of training data; at runtime the app only needs:
# - games (scoring averages, win rates, replay listing)
# - team_stats (pregame model features)
# - elo_ratings (pregame model features)
# - game_states for the 12 featured replay games only (the rest of this table is training data and is the bulk of the size)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
SRC = os.path.join(DATA_DIR, "nba.db")
DST = os.path.join(DATA_DIR, "runtime.db")

# same criteria replay.py uses to pick featured games
FEATURED_SQL = """
    SELECT g.game_id
    FROM src.games g
    WHERE g.home_score IS NOT NULL
    AND EXISTS (
        SELECT 1 FROM src.game_states gs
        WHERE gs.game_id = g.game_id
        AND gs.x IS NOT NULL
        AND gs.shot_result IS NOT NULL
    )
    ORDER BY g.game_date DESC
    LIMIT 12
"""

if __name__ == "__main__":
    if os.path.exists(DST):
        os.remove(DST)

    conn = sqlite3.connect(DST)
    conn.execute("ATTACH DATABASE ? AS src", (SRC,))

    featured = [row[0] for row in conn.execute(FEATURED_SQL)]
    print(f"Featured replay games: {len(featured)}")

    conn.execute("CREATE TABLE games AS SELECT * FROM src.games")
    conn.execute("CREATE TABLE team_stats AS SELECT * FROM src.team_stats")
    conn.execute("CREATE TABLE elo_ratings AS SELECT * FROM src.elo_ratings")

    placeholders = ",".join("?" * len(featured))
    conn.execute(
        f"CREATE TABLE game_states AS SELECT * FROM src.game_states WHERE game_id IN ({placeholders})",
        featured,
    )

    conn.execute("CREATE INDEX idx_game_states_game_id ON game_states(game_id)")
    conn.execute("CREATE INDEX idx_team_stats_season_team ON team_stats(season, team)")

    conn.commit()
    conn.execute("DETACH DATABASE src")
    conn.execute("VACUUM")

    for table in ["games", "team_stats", "elo_ratings", "game_states"]:
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table:<14} {n:>10,} rows")
    conn.close()

    print(f"\nruntime.db written: {os.path.getsize(DST) / 1e6:.1f} MB")
