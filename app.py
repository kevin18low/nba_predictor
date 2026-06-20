import os
import copy
from flask import Flask, jsonify, render_template, abort
from state import app_state, _lock
from live.poller import start_poller
from live.replay import build_replay, get_featured_games

app = Flask(__name__)

# NBA API tricodes that don't match ESPN's CDN team identifiers
_ESPN_CODE = {
    "UTA": "utah",
    "NOP": "no",
    "GSW": "gs",
    "SAS": "sa",
}

@app.template_filter("espn_logo")
def espn_logo(tricode):
    return _ESPN_CODE.get(tricode, tricode)

# guard against double-start under Flask's debug reloader.
if not os.environ.get("WERKZEUG_RUN_MAIN"):
    start_poller()

# -- Web Routes --

@app.route("/")
def index():
    with _lock:
        games = copy.deepcopy(app_state["games"])
    return render_template("index.html", games=games, featured=get_featured_games())


@app.route("/game/<game_id>/scoreboard")
def scoreboard(game_id):
    with _lock:
        games = copy.deepcopy(app_state["games"])
        data = copy.deepcopy(app_state["game_data"].get(game_id))
    if data is None:
        abort(404)
    return render_template("scoreboard.html", game_id=game_id, games=games, data=data)


@app.route("/game/<game_id>/court")
def court(game_id):
    with _lock:
        games = copy.deepcopy(app_state["games"])
        data = copy.deepcopy(app_state["game_data"].get(game_id))
    if data is None:
        abort(404)
    return render_template("court.html", game_id=game_id, games=games,
                           mode="live",
                           home_team=data["home_team"],
                           away_team=data["away_team"],
                           game_label="Live")


@app.route("/game/<game_id>/replay")
def replay(game_id):
    game = next((g for g in get_featured_games() if g["game_id"] == game_id), None)
    if game is None:
        abort(404)
    with _lock:
        games = copy.deepcopy(app_state["games"])
    return render_template("court.html", game_id=game_id, games=games,
                           mode="replay",
                           home_team=game["home_team"],
                           away_team=game["away_team"],
                           game_label=game["game_date"])


# -- API routes --

@app.route("/api/games")
def api_games():
    with _lock:
        games = copy.deepcopy(app_state["games"])
    return jsonify(games)


@app.route("/api/game/<game_id>/state")
def api_game_state(game_id):
    with _lock:
        data = copy.deepcopy(app_state["game_data"].get(game_id))
    if data is None:
        abort(404)

    state = data["game_state"] or {}
    return jsonify({
        "game_id": game_id,
        "home_team": data["home_team"],
        "away_team": data["away_team"],
        "quarter": state.get("quarter"),
        "time_remaining_secs": state.get("time_remaining_secs"),
        "home_score": state.get("home_score"),
        "away_score": state.get("away_score"),
        "home_win_prob": data["home_win_prob"],
        "away_win_prob": 1 - data["home_win_prob"] if data["home_win_prob"] is not None else None,
        "score_prediction": data["score_prediction"],
        "last_updated": data["last_updated"],
    })


@app.route("/api/game/<game_id>/shots")
def api_game_shots(game_id):
    with _lock:
        data = copy.deepcopy(app_state["game_data"].get(game_id))
    if data is None:
        abort(404)
    return jsonify({
        "game_id": game_id,
        "shots": data["shots"],
    })


@app.route("/api/game/<game_id>/replay")
def api_replay(game_id):
    game = next((g for g in get_featured_games() if g["game_id"] == game_id), None)
    if game is None:
        abort(404)
    data = build_replay(game_id, game["home_team"], game["away_team"])
    return jsonify(data)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
