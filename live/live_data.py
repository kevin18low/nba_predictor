from nba_api.live.nba.endpoints import scoreboard, playbyplay
from nba_api.live.nba.library.http import NBALiveHTTP
from ingestion.fetch_playbyplay import parse_time
import requests
import os

NBALiveHTTP.headers = {
    "Accept": "application/json",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
}

# cdn.nba.com blocks cloud-provider IPs (e.g. Render). Route through a proxy
LIVE_PROXY = os.environ.get("NBA_LIVE_PROXY")
if LIVE_PROXY:
    NBALiveHTTP.base_url = LIVE_PROXY.rstrip("/") + "/static/json/liveData/{endpoint}"

SCOREBOARD_URL = NBALiveHTTP.base_url.format(endpoint="scoreboard/todaysScoreboard_00.json")
SCHEDULE_URL = (LIVE_PROXY.rstrip("/") if LIVE_PROXY else "https://cdn.nba.com") + "/static/json/staticData/scheduleLeagueV2.json"

# game id prefixes: 002 regular season, 004 playoffs, 005 play-in, 006 NBA Cup final
# (exclude 001 preseason and 003 All-Star)
REAL_GAME_PREFIXES = ("002", "004", "005", "006")
FINAL_STATUS = 3

# get all live NBA games with current scores and teams
def get_live_scoreboard():
    try:
        board = scoreboard.ScoreBoard()
    except ValueError:
        # response wasn't JSON: log what the CDN actually sent
        r = requests.get(SCOREBOARD_URL, headers=NBALiveHTTP.headers, timeout=10)
        print(f"[live] scoreboard returned {r.status_code}: {r.text[:200]!r}")
        raise
    return board.games.get_dict()

# get full play-by-play actions for a live game
def get_live_playbyplay(game_id):
    pbp = playbyplay.PlayByPlay(game_id=game_id)
    return pbp.actions.get_dict()

# get the most recently finished games of the current season, newest first
def get_recent_final_games(limit):
    r = requests.get(SCHEDULE_URL, headers=NBALiveHTTP.headers, timeout=10)
    r.raise_for_status()

    finals = [
        g
        for day in r.json()["leagueSchedule"]["gameDates"]
        for g in day["games"]
        if g["gameStatus"] == FINAL_STATUS and g["gameId"].startswith(REAL_GAME_PREFIXES)
    ]
    finals.sort(key=lambda g: g["gameDateTimeUTC"], reverse=True)

    return [{
        "game_id": g["gameId"],
        "game_date": g["gameDateEst"][:10], # US date
        "home_team": g["homeTeam"]["teamTricode"],
        "away_team": g["awayTeam"]["teamTricode"],
        "home_score": g["homeTeam"]["score"],
        "away_score": g["awayTeam"]["score"],
    } for g in finals[:limit]]

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
                "team_tricode": action.get("teamTricode"),
                "x": action.get("xLegacy"),
                "y": action.get("yLegacy"),
                "shot_distance": action.get("shotDistance"),
                "action_type": action.get("actionType"),
                "shot_result": action.get("shotResult"),
                "period": action["period"],
                "clock": action["clock"]
            })
    return new_shots