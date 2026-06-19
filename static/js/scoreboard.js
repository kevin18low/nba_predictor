const GAME_ID = document.body.dataset.gameId;
const POLL_MS = 5000;

async function poll() {
    try {
        const res = await fetch(`/api/game/${GAME_ID}/state`);
        if (!res.ok) return;
        const d = await res.json();

        // scores
        document.getElementById("home-score").textContent = d.home_score;
        document.getElementById("away-score").textContent = d.away_score;

        // clock
        const mins = Math.floor(d.time_remaining_secs / 60);
        const secs = String(Math.floor(d.time_remaining_secs % 60)).padStart(2, "0");
        document.getElementById("clock").textContent = `Q${d.quarter}  ${mins}:${secs}`;

        // win probability bar
        const homeProb = (d.home_win_prob * 100).toFixed(1);
        const awayProb = (d.away_win_prob * 100).toFixed(1);
        document.getElementById("win-prob-home").style.width = homeProb + "%";
        document.getElementById("win-prob-away").style.width = awayProb + "%";
        document.getElementById("home-win-prob-label").textContent = homeProb + "%";
        document.getElementById("away-win-prob-label").textContent = awayProb + "%";

        // projected scores
        if (d.score_prediction) {
            document.getElementById("home-projected").textContent = d.score_prediction.home_projected;
            document.getElementById("away-projected").textContent = d.score_prediction.away_projected;
        }

    } catch (e) {
        // silently ignore transient network errors
    }
}

poll();
setInterval(poll, POLL_MS);
