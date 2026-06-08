import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "nba.db")

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
            action_type         TEXT,
            shot_result         TEXT,
            x                   REAL,
            y                   REAL,
            shot_distance       REAL
        )
    """)

    conn.commit()
    conn.close()
    print(f"Database initialized at: {DB_PATH}")

if __name__ == "__main__":
    init_db()