import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", os.environ.get("NBA_DB_FILE", "nba.db"))

# Connect to SQLite
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# Initialize tables for game data and play-by-play data
def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS games (
            game_id     TEXT PRIMARY KEY,
            game_date   TEXT,
            home_team   TEXT,
            away_team   TEXT,
            home_score  INTEGER,
            away_score  INTEGER,
            home_win    INTEGER
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS game_states (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id             TEXT,
            quarter             INTEGER,
            time_remaining_secs FLOAT,
            home_score          INTEGER,
            away_score          INTEGER,
            score_diff          INTEGER,
            home_win            INTEGER,
            player_name         TEXT,
            person_id           INTEGER,
            team_tricode        TEXT,
            action_type         TEXT,
            shot_result         TEXT,
            x                   REAL,
            y                   REAL,
            shot_distance       REAL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS shot_attempts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id       INTEGER,
            player_name     TEXT,
            game_id         TEXT,
            game_date       TEXT,
            season          TEXT,
            team            TEXT,
            x               REAL,
            y               REAL,
            shot_distance   REAL,
            shot_zone       TEXT,
            shot_zone_area  TEXT,
            shot_type       TEXT,
            action_type     TEXT,
            made            INTEGER
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS team_stats (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            season      TEXT,
            team        TEXT,
            off_rating  REAL,
            def_rating  REAL,
            pace        REAL,
            UNIQUE(season, team)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS elo_ratings (
            team    TEXT PRIMARY KEY,
            elo     REAL
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_team_stats_season_team
        ON team_stats(season, team)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_game_states_game_id
        ON game_states(game_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_game_states_player
        ON game_states(person_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_game_states_shot
        ON game_states(shot_result)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_game_states_shot_player
        ON game_states(person_id, shot_result)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_shot_attempts_player
        ON shot_attempts(player_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_shot_attempts_game
        ON shot_attempts(game_id)
    """)

    conn.commit()
    conn.close()
    print(f"Database initialized at: {DB_PATH}")

if __name__ == "__main__":
    init_db()