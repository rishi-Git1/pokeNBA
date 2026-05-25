// Tiny fetch wrapper so views don't deal with response/error plumbing.

const BASE = ""; // same-origin via FastAPI mount

const GM_STORAGE_KEY = "pokenba_gm";
let _gmMode = "league_gm";
let _userTeamId = null;

function _loadGmFromStorage() {
  try {
    const raw = localStorage.getItem(GM_STORAGE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    _gmMode = parsed.mode === "team_gm" ? "team_gm" : "league_gm";
    _userTeamId = parsed.teamId ?? null;
    if (_gmMode === "team_gm" && _userTeamId == null) {
      _gmMode = "league_gm";
    }
  } catch (_) { /* ignore */ }
}

_loadGmFromStorage();

export function getGmMode() {
  return _gmMode;
}

export function getUserTeamId() {
  return _userTeamId;
}

export function setGmContext(mode, teamId = null) {
  _gmMode = mode === "team_gm" ? "team_gm" : "league_gm";
  _userTeamId = teamId ?? null;
  localStorage.setItem(GM_STORAGE_KEY, JSON.stringify({
    mode: _gmMode,
    teamId: _userTeamId,
  }));
}

function gmQuery() {
  const params = { game_mode: _gmMode };
  if (_gmMode === "team_gm" && _userTeamId != null) {
    params.user_team_id = _userTeamId;
  }
  return qs(params);
}

async function request(path, opts = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || detail;
    } catch (_) { /* ignore */ }
    throw new Error(`${res.status} ${detail}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  // teams / players / standings
  teams:        () => request("/api/teams"),
  team:         (id) => request(`/api/teams/${id}`),
  player:       (id) => request(`/api/players/${id}`),
  playerInjuries: (id, season) =>
                  request(`/api/players/${id}/injuries${season != null ? `?season=${season}` : ""}`),
  players:      (params = {}) => request(`/api/players?${qs(params)}`),
  standings:    () => request("/api/league/standings"),
  freeAgents:   (limit = 100) => request(`/api/league/free-agents?limit=${limit}`),
  badges:       () => request("/api/league/badges"),
  leaders:      (stat = "points", limit = 10, season) =>
                  request(`/api/league/leaders?${qs({ stat, limit, season })}`),
  endSeason:    (season = 1) => request(`/api/league/end-season?season=${season}`, { method: "POST" }),
  advanceSeason:(season = 1) => request(`/api/league/advance-season?season=${season}`, { method: "POST" }),
  resetLeague:  (seed) => request(`/api/league/reset${seed != null ? `?seed=${seed}` : ""}`, { method: "POST" }),

  // sim — omit `season` to let the backend use LeagueState.current_season
  schedule:        (params = {}) => request(`/api/sim/schedule?${qs(params)}`),
  recentResults:   (limit = 10, season) =>
                    request(`/api/sim/recent-results?${qs({ limit, season })}`),
  upcomingGames:   (limit = 10, season) =>
                    request(`/api/sim/upcoming-games?${qs({ limit, season })}`),
  simDay:          (season) => request(`/api/sim/day?${qs({
                    ...(season != null ? { season } : {}),
                    game_mode: _gmMode,
                    ...(_gmMode === "team_gm" && _userTeamId != null ? { user_team_id: _userTeamId } : {}),
                  })}`, { method: "POST" }),
  simSeason:       (season) => request(`/api/sim/season${season != null ? `?season=${season}` : ""}`, { method: "POST" }),
  generateSchedule:(season) => request(`/api/sim/schedule${season != null ? `?season=${season}` : ""}`, { method: "POST" }),
  boxScore:        (gameId) => request(`/api/sim/games/${gameId}/box`),

  // transactions
  trade:        (payload) => request("/api/transactions/trade", { method: "POST", body: JSON.stringify(payload) }),
  sign:         (teamId, playerId) =>
                  request(`/api/transactions/sign?team_id=${teamId}&player_id=${playerId}&${gmQuery()}`, { method: "POST" }),
  release:      (teamId, playerId) =>
                  request(`/api/transactions/release?team_id=${teamId}&player_id=${playerId}&${gmQuery()}`, { method: "POST" }),

  // projections / config
  capConfig:    () => request("/api/league/cap-config"),
  releaseProjection: (teamId, playerId) =>
                  request(`/api/transactions/projection/release?team_id=${teamId}&player_id=${playerId}`),
  signProjection:    (teamId, playerId) =>
                  request(`/api/transactions/projection/sign?team_id=${teamId}&player_id=${playerId}`),

  // league state machine + post-season
  leagueState:    () => request("/api/league/state"),
  startNextSeason:() => request("/api/league/start-next-season", { method: "POST" }),

  // playoffs
  bracket:    (season) => request(`/api/playoffs/bracket${season != null ? `?season=${season}` : ""}`),
  simPlayoffGame:  () => request("/api/playoffs/game",  { method: "POST" }),
  simPlayoffSlate: () => request("/api/playoffs/slate", { method: "POST" }),
  simPlayoffRound: () => request("/api/playoffs/round", { method: "POST" }),

  // draft
  draftState:    () => request("/api/draft/state"),
  draftPick:     (playerId) => request("/api/draft/pick", {
                    method: "POST", body: JSON.stringify({ player_id: playerId }),
                  }),
  draftAutoPick: () => request("/api/draft/auto-pick", { method: "POST" }),
  draftSimRest:  () => request("/api/draft/sim-rest",  { method: "POST" }),
};

function qs(obj) {
  return Object.entries(obj)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join("&");
}
