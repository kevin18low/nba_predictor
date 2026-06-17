from nba_api.live.nba.endpoints import scoreboard, playbyplay
from nba_api.live.nba.library.http import NBALiveHTTP
from fetch_playbyplay import parse_time

NBALiveHTTP.headers = {
    "Accept": "application/json",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Host": "cdn.nba.com",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
}

# get all live NBA games with current scores and teams
def get_live_scoreboard():
    board = scoreboard.ScoreBoard()
    return board.games.get_dict()

# get full play-by-play actions for a live game
def get_live_playbyplay(game_id):
    pbp = playbyplay.PlayByPlay(game_id=game_id)
    return pbp.actions.get_dict()


# Extract current game state from the most recent action with a score
def get_live_game_states(actions):
    for action in reversed(actions):
        if action.get("scoreHome") not in (None, ""):
            return {
                "quarter": action["period"],
                "time_remaining_secs": parse_time(action["clock"]),
                "home_score": int(action["scoreHome"]),
                "away_score": int(action["scoreAway"]),
                "score_diff": int(action["scoreHome"]) - int(action["scoreAway"])
            }
    return None

# get shot attempts that have not been processed yet
def get_new_shot_events(actions, seen_action_numbers):
    new_shots = []
    for action in actions:
        if action["actionNumber"] in seen_action_numbers:
            continue
        if action.get("shotResult") in ("Made", "Missed"):
            new_shots.append({
                "action_number": action["actionNumber"],
                "person_id": action.get("personId"),
                "player_name": action.get("playerNameI") or action.get("playerName"),
                "x": action.get("xLegacy"),
                "y": action.get("yLegacy"),
                "shot_distance": action.get("shotDistance"),
                "action_type": action.get("actionType"),
                "shot_result": action.get("shotResult"),
                "period": action["period"],
                "clock": action["clock"]
            })
    return new_shots