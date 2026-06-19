import threading
import copy

_lock = threading.Lock()

app_state = {
    "games": [],      # list of {game_id, home_team, away_team, status}
    "game_data": {},  # keyed by game_id - scores, win prob, shots, etc.
    "shot_state": {}, # keyed by game_id - tracks seen shots + per-player rolling stats
    "replays": {},    # keyed by game_id - pre-computed historical replay timelines
}

def read_state():
    with _lock:
        return copy.deepcopy(app_state)

def write_state(fn):
    with _lock:
        fn(app_state)
