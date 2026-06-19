const GAME_ID = document.body.dataset.gameId;
const POLL_MS = 8000;

let shots   = [];   // all normalized shot events
let current = -1;   // index of last rendered shot
let atLive  = true; // auto-advance when new live shots arrive

// Coordinate mapping
function toSvg(x, y) { return [x + 250, 450 - y]; }

// Map probabilities to colour
function probToColour(prob) {
    if (prob >= 0.5) {
        const t = (prob - 0.5) * 2;
        return `rgb(${Math.round(220 * (1 - t))},200,50)`;
    }
    return `rgb(220,${Math.round(200 * prob * 2)},50)`;
}

function formatClock(quarter, secs) {
    const m = Math.floor(secs / 60);
    const s = String(Math.floor(secs % 60)).padStart(2, "0");
    return `Q${quarter} ${m}:${s}`;
}

// Shot rendering
const layer   = document.getElementById("shots-layer");
const tooltip = document.getElementById("tooltip");

function drawDot(shot, highlight) {
    const [sx, sy] = toSvg(shot.x, shot.y);
    const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    c.setAttribute("cx", sx);
    c.setAttribute("cy", sy);
    c.setAttribute("r", highlight ? 9 : 6);
    c.setAttribute("fill", probToColour(shot.probability));
    c.setAttribute("stroke", shot.shot_result === "Made" ? "white" : "rgba(0,0,0,0.35)");
    c.setAttribute("stroke-width", shot.shot_result === "Made" ? 2 : 1);
    c.setAttribute("opacity", highlight ? 1.0 : 0.6);
    c.style.cursor = "pointer";

    c.addEventListener("mouseover", () => {
        tooltip.style.display = "block";
        tooltip.innerHTML = `
            <strong>${shot.player_name}</strong><br>
            ${shot.shot_distance}ft<br>
            Predicted: ${Math.round(shot.probability * 100)}%<br>
            <em>${shot.shot_result}</em>`;
    });
    c.addEventListener("mousemove", e => {
        tooltip.style.left = (e.pageX + 14) + "px";
        tooltip.style.top  = (e.pageY - 36) + "px";
    });
    c.addEventListener("mouseout", () => tooltip.style.display = "none");
    layer.appendChild(c);
}

function dimLast() {
    const last = layer.lastElementChild;
    if (last) { last.setAttribute("r", 6); last.setAttribute("opacity", 0.6); }
}

// Replay navigation
function stepForward() {
    if (current >= shots.length - 1) return;
    dimLast();
    current++;
    drawDot(shots[current], true);
    updateUI();
}

function stepBack() {
    if (current <= 0) return;
    layer.removeChild(layer.lastElementChild);
    current--;
    if (layer.lastElementChild) {
        layer.lastElementChild.setAttribute("r", 9);
        layer.lastElementChild.setAttribute("opacity", 1.0);
    }
    atLive = false;
    updateUI();
}

function updateScoreboard(homeScore, awayScore, quarter, secs, homeProb, awayProb) {
    document.getElementById("home-score").textContent = homeScore ?? "–";
    document.getElementById("away-score").textContent = awayScore ?? "–";
    if (quarter != null && secs != null)
        document.getElementById("clock").textContent = formatClock(quarter, secs);
    if (homeProb != null) {
        const hp = (homeProb * 100).toFixed(1);
        const ap = (awayProb * 100).toFixed(1);
        document.getElementById("win-prob-home").style.width = hp + "%";
        document.getElementById("win-prob-away").style.width = ap + "%";
        document.getElementById("home-prob-label").textContent = hp + "%";
        document.getElementById("away-prob-label").textContent = ap + "%";
    }
}

function updateUI() {
    const shot = shots[current];

    const counter = document.getElementById("counter");
    if (counter) counter.textContent = `${current + 1} / ${shots.length}`;

    const btnPrev = document.getElementById("btn-prev");
    const btnNext = document.getElementById("btn-next");
    if (btnPrev) btnPrev.disabled = current <= 0;
    if (btnNext) btnNext.disabled = current >= shots.length - 1;

    const shotInfo = document.getElementById("shot-info");
    if (shotInfo && shot) {
        const prob   = Math.round(shot.probability * 100);
        const result = shot.shot_result === "Made" ? "✓ Made" : "✗ Missed";
        shotInfo.innerHTML =
            `<strong>${shot.player_name}</strong> — ${shot.shot_distance}ft` +
            ` &nbsp;|&nbsp; Predicted: <strong>${prob}%</strong> &nbsp;|&nbsp; ${result}`;
    }

    if (PAGE_MODE === "replay" && shot)
        updateScoreboard(shot.home_score, shot.away_score, shot.quarter,
                         shot.time_remaining_secs, shot.home_win_prob, shot.away_win_prob);
}

// Data normalization
// Live endpoint uses `probability`, replay endpoint uses `shot_prob`
function normalize(s) {
    return { ...s, probability: s.probability ?? s.shot_prob };
}

// Replay mode
async function loadReplay() {
    const res  = await fetch(`/api/game/${GAME_ID}/replay`);
    const data = await res.json();
    shots = data.events.map(normalize);

    document.getElementById("loading").style.display   = "none";
    document.getElementById("replay-ui").style.display = "block";
    stepForward();
}

// Live mode
async function pollLive() {
    try {
        const res = await fetch(`/api/game/${GAME_ID}/shots`);
        if (!res.ok) return;
        const d = await res.json();

        const seen  = new Set(shots.map(s => s.action_number));
        const fresh = d.shots
            .filter(s => !seen.has(s.action_number) && s.x !== null && s.y !== null)
            .map(normalize);

        if (fresh.length === 0) return;
        shots.push(...fresh);
        if (atLive) fresh.forEach(() => stepForward());
        else updateUI();
    } catch (_) {}
}

// Stepping controls
document.getElementById("btn-next")?.addEventListener("click", () => {
    atLive = false;
    stepForward();
});
document.getElementById("btn-prev")?.addEventListener("click", stepBack);
document.addEventListener("keydown", e => {
    if (e.key === "ArrowRight") { atLive = false; stepForward(); }
    if (e.key === "ArrowLeft")  stepBack();
});

// Live state polling (scores, clock, win prob)
async function pollLiveState() {
    try {
        const res = await fetch(`/api/game/${GAME_ID}/state`);
        if (!res.ok) return;
        const d = await res.json();
        updateScoreboard(d.home_score, d.away_score, d.quarter,
                         d.time_remaining_secs, d.home_win_prob, d.away_win_prob);
    } catch (_) {}
}

if (PAGE_MODE === "replay") {
    loadReplay();
} else {
    pollLive();
    pollLiveState();
    setInterval(pollLive, POLL_MS);
    setInterval(pollLiveState, POLL_MS);
}
