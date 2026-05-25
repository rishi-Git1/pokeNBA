/* =====================================================================
 * pokeNBA — vanilla JS SPA
 *
 * Single entry point. Hash-based routing. All views render into #view.
 * Sprites come straight from PokeAPI's CDN (urls baked in by the backend).
 * ===================================================================== */

import { api, getGmMode, getUserTeamId, setGmContext } from "/static/api.js?v=20260528";

// ---------------------------------------------------------------- DOM helpers
const $  = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k === "onClick") node.addEventListener("click", v);
    else if (k === "dataset") for (const [dk, dv] of Object.entries(v)) node.dataset[dk] = dv;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2).toLowerCase(), v);
    else node.setAttribute(k, v);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    node.appendChild(typeof child === "string" || typeof child === "number" ? document.createTextNode(String(child)) : child);
  }
  return node;
}

// ----------------------------------------------------------------- toast
function toast(msg, kind = "info") {
  const node = el("div", { class: `toast toast-${kind}` }, msg);
  $("#toast-container").appendChild(node);
  setTimeout(() => {
    node.style.opacity = "0";
    node.style.transition = "opacity 0.3s";
    setTimeout(() => node.remove(), 320);
  }, 2400);
}

function canManageTeam(teamId) {
  if (getGmMode() !== "team_gm") return true;
  return Number(teamId) === Number(getUserTeamId());
}

function isTeamGmMode() {
  return getGmMode() === "team_gm" && getUserTeamId() != null;
}

async function refreshModeUI() {
  const select = $("#game-mode-select");
  const teamPill = $("#user-team-pill");
  if (!select) return;

  select.value = getGmMode();
  if (getGmMode() === "team_gm" && getUserTeamId() != null) {
    await loadTeams();
    const teamId = getUserTeamId();
    teamPill.textContent = teamAbbr(teamId);
    teamPill.title = `Open ${teamLabel(teamId)}`;
    teamPill.classList.remove("hidden");
    teamPill.onclick = () => { location.hash = `#/teams/${teamId}`; };
  } else {
    teamPill.classList.add("hidden");
    teamPill.textContent = "";
    teamPill.title = "";
    teamPill.onclick = null;
  }
}

function showCpuMovesModal(moves) {
  if (!moves?.length) return;

  const overlay = el("div", { class: "modal-overlay" });
  const closing = () => overlay.remove();

  const rows = moves.map(move => el("div", { class: "cpu-move-row" },
    move.sim_date ? el("div", { class: "cpu-move-date" }, formatDate(move.sim_date)) : null,
    el("div", { class: "cpu-move-team" }, `${move.team_abbr} · ${move.team_name}`),
    el("div", { class: "cpu-move-detail" },
      `Cut ${move.released.name} (BST ${move.released.bst}) → signed ${move.signed.name} (BST ${move.signed.bst})`,
    ),
  ));

  const modal = el("div", { class: "card modal-dialog", style: "max-width: 560px;" },
    el("div", { class: "modal-head" },
      el("div", {},
        el("div", { class: "modal-eyebrow" }, "League activity"),
        el("h3", { class: "modal-title" }, `${moves.length} roster move${moves.length === 1 ? "" : "s"}`),
      ),
    ),
    el("p", { class: "muted", style: "margin: 0;" },
      "AI teams shuffled their rosters after the sim (worst teams acted first)."),
    el("div", { class: "cpu-moves-list" }, ...rows),
    el("div", { class: "modal-actions" },
      el("button", { class: "btn btn-primary", type: "button", onClick: closing }, "Got it"),
    ),
  );

  overlay.addEventListener("click", (e) => { if (e.target === overlay) closing(); });
  overlay.appendChild(modal);
  document.body.appendChild(overlay);
}

function handleRegularSeasonSimResult(r, { showMovesModal = true } = {}) {
  if (r?.transition?.transition === "regular_season -> playoffs") {
    toast("Regular season complete — playoffs are set!", "success");
  } else if (r?.games_played) {
    toast(`Played ${r.games_played} games on ${formatDate(r.sim_date)}`, "success");
  }
  if (r?.injury_report) {
    notifyPlayoffInjuries(
      r.injury_report,
      r?.games_played ? `${r.games_played} games · injuries` : null,
    );
  }
  if (showMovesModal && r?.cpu_moves?.length) {
    showCpuMovesModal(r.cpu_moves);
  }
  return r?.cpu_moves || [];
}

async function onGameModeChange(nextMode) {
  if (nextMode === getGmMode() && (nextMode === "league_gm" || getUserTeamId() != null)) {
    await refreshModeUI();
    return;
  }

  if (nextMode === "team_gm") {
    const teams = await loadTeams();
    const teamId = await pickTeam(teams, "Which team do you want to run?");
    if (teamId == null) {
      $("#game-mode-select").value = getGmMode();
      return;
    }
    setGmContext("team_gm", teamId);
    toast(`Team GM · ${teamAbbr(teamId)}`, "success");
  } else {
    setGmContext("league_gm", null);
    toast("League GM mode", "success");
  }
  await refreshModeUI();
  router();
}

// ----------------------------------------------------------------- caches
const teamCache = new Map(); // team_id -> Team summary
async function loadTeams() {
  if (teamCache.size) return Array.from(teamCache.values());
  const teams = await api.teams();
  teams.forEach(t => teamCache.set(t.id, t));
  return teams;
}

let _capConfigCache = null;
async function loadCapConfig(force = false) {
  if (_capConfigCache && !force) return _capConfigCache;
  _capConfigCache = await api.capConfig();
  return _capConfigCache;
}

// Singleton league state — cached across views, invalidated on every phase change.
let _leagueState = null;
async function loadLeagueState(force = false) {
  if (_leagueState && !force) return _leagueState;
  _leagueState = await api.leagueState();
  return _leagueState;
}
function invalidateState() {
  _leagueState = null;
  _capConfigCache = null;
}

/** Latest playoff injury report from the most recent sim (shown on #/playoffs). */
let _lastPlayoffInjuryReport = null;
function fmtNum(n) { return Number(n).toLocaleString(); }
function teamLabel(id) {
  if (id == null) return "FA";
  const t = teamCache.get(id);
  return t ? `${t.city} ${t.name}` : `Team ${id}`;
}
function teamAbbr(id) {
  if (id == null) return "FA";
  return teamCache.get(id)?.abbreviation ?? `T${id}`;
}

// ----------------------------------------------------------------- render helpers
function clearView() { const v = $("#view"); v.innerHTML = ""; return v; }
function loading(view) { view.appendChild(el("div", { class: "empty" }, el("span", { class: "spinner" }), "Loading…")); }
function fmt(v) { return v == null ? "—" : v; }
function pct(num, den, digits = 1) { if (!den) return "—"; return `${(num / den * 100).toFixed(digits)}%`; }
function safeImg(url, alt = "", cls = "") {
  return el("img", {
    src: url,
    alt,
    class: cls,
    loading: "lazy",
    onError: (e) => { e.currentTarget.style.opacity = "0.2"; e.currentTarget.alt = "?"; },
  });
}
function spriteImg(url, alt = "") { return safeImg(url, alt); }

function playerTile(p, opts = {}) {
  const injuryBadge = p.injury?.is_injured
    ? el("button", {
        class: "injury-badge",
        type: "button",
        title: "View injury history",
        onClick: (e) => {
          e.preventDefault();
          e.stopPropagation();
          showInjuryHistoryModal(p.id, p.name);
        },
      }, `OUT ${p.injury.games_remaining}G`)
    : null;

  const tile = el("a",
    {
      class: "player-tile" + (p.injury?.is_injured ? " player-tile-injured" : ""),
      href: `#/players/${p.id}`,
      title: `${p.name} · ${p.position} · BST ${p.bst} · ${p.badge}`,
    },
    el("div", { class: "sprite" }, spriteImg(p.sprite_url, p.name)),
    el("div", { class: "meta" },
      el("div", { class: "name" },
        p.name,
        injuryBadge,
      ),
      el("div", { class: "sub" },
        el("span", { class: "pos-tag" }, p.position),
        el("span", { class: "bst" }, `BST ${p.bst}`),
        el("span", { class: "muted" }, p.badge),
      ),
    ),
    opts.right ? opts.right : null,
  );
  return tile;
}

async function showInjuryHistoryModal(playerId, playerName = "") {
  let profile;
  try {
    profile = await api.playerInjuries(playerId);
  } catch (err) {
    toast(err.message, "error");
    return;
  }

  const overlay = el("div", { class: "modal-overlay" });
  const closing = () => overlay.remove();

  const current = profile.current || {};
  const events = profile.events || [];
  const name = playerName || `Player ${playerId}`;

  const currentBlock = current.is_injured
    ? el("div", { class: "card", style: "padding: 0.75rem 1rem; margin-bottom: 0.75rem;" },
        el("div", { class: "muted", style: "font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em;" }, "Current injury"),
        el("div", { style: "font-weight: 700; margin-top: 0.25rem;" },
          `${current.games_remaining} game${current.games_remaining === 1 ? "" : "s"} remaining`,
          current.stint_games_total
            ? el("span", { class: "muted" }, ` · ${current.stint_games_total}-game stint`)
            : null,
        ),
        el("div", { class: "muted", style: "font-size: 0.85rem; margin-top: 0.2rem;" },
          `${current.season_injury_count} injury event${current.season_injury_count === 1 ? "" : "s"} this season`,
        ),
      )
    : el("div", { class: "muted", style: "margin-bottom: 0.75rem;" },
        events.length
          ? `Healthy now · ${current.season_injury_count || 0} injury event${current.season_injury_count === 1 ? "" : "s"} this season`
          : "No injuries recorded this season.",
      );

  const eventRows = events.length
    ? el("div", { class: "cpu-moves-list" },
        ...events.map(ev => el("div", { class: "cpu-move-row" },
          el("div", { class: "cpu-move-date" }, `${formatDate(ev.event_date)} · ${ev.phase.replace("_", " ")}`),
          el("div", { class: "cpu-move-team" }, ev.event_type === "injured" ? "Injured" : ev.event_type === "recovered" ? "Recovered" : "Cleared"),
          ev.event_type === "injured"
            ? el("div", { class: "cpu-move-detail muted" }, `Expected out ${ev.games_out} game${ev.games_out === 1 ? "" : "s"}`)
            : null,
        )),
      )
    : el("div", { class: "muted" }, "No logged injury events.");

  const modal = el("div", { class: "card modal-dialog", style: "max-width: 520px;" },
    el("div", { class: "modal-head" },
      el("div", {},
        el("div", { class: "modal-eyebrow" }, `Season ${profile.season}`),
        el("h3", { class: "modal-title" }, `${name} · Injuries`),
      ),
    ),
    currentBlock,
    el("div", { class: "injury-section-title" }, "Season log"),
    eventRows,
    el("div", { class: "modal-actions" },
      el("button", { class: "btn btn-primary", type: "button", onClick: closing }, "Close"),
    ),
  );

  overlay.addEventListener("click", (e) => { if (e.target === overlay) closing(); });
  overlay.appendChild(modal);
  document.body.appendChild(overlay);
}

// =====================================================================
// Router
// =====================================================================
const routes = [
  { pattern: /^\/?$/,                           name: "dashboard",   view: viewDashboard },
  { pattern: /^\/standings$/,                   name: "standings",   view: viewStandings },
  { pattern: /^\/schedule$/,                    name: "schedule",    view: viewSchedule  },
  { pattern: /^\/leaders$/,                     name: "leaders",     view: viewLeaders   },
  { pattern: /^\/free-agents$/,                 name: "free-agents", view: viewFreeAgents},
  { pattern: /^\/badges$/,                      name: "badges",      view: viewBadges    },
  { pattern: /^\/playoffs$/,                    name: "playoffs",    view: viewPlayoffs  },
  { pattern: /^\/draft$/,                       name: "draft",       view: viewDraft     },
  { pattern: /^\/teams\/(\d+)$/,                name: null,          view: viewTeam      },
  { pattern: /^\/players\/(\d+)$/,              name: null,          view: viewPlayer    },
  { pattern: /^\/games\/(\d+)$/,                name: null,          view: viewGame      },
];

async function router() {
  const fullHash = location.hash.replace(/^#/, "") || "/";
  const path = fullHash.split("?")[0]; // strip query string before matching
  const view = clearView();
  loading(view);

  // Refresh team cache so labels are always fresh after a sim/trade.
  await loadTeams();
  // Refresh phase-aware topbar before rendering the view (cheap; cached).
  await refreshPhaseUI();
  await refreshModeUI();

  // highlight nav
  $$(".nav a").forEach(a => a.classList.remove("active"));

  for (const route of routes) {
    const m = path.match(route.pattern);
    if (m) {
      if (route.name) {
        const navEl = $(`.nav a[data-route="${route.name}"]`);
        if (navEl) navEl.classList.add("active");
      }
      try {
        view.innerHTML = "";
        await route.view(view, ...m.slice(1));
      } catch (err) {
        console.error(err);
        view.innerHTML = "";
        view.appendChild(el("div", { class: "empty" }, "Error: " + err.message));
        toast(err.message, "error");
      }
      return;
    }
  }

  view.innerHTML = "";
  view.appendChild(el("div", { class: "empty" }, "Not found: ", fullHash));
}

window.addEventListener("hashchange", router);
window.addEventListener("DOMContentLoaded", router);

// =====================================================================
// Dashboard
// =====================================================================
async function viewDashboard(view) {
  const [standings, leaders, recent, upcoming] = await Promise.all([
    api.standings(),
    api.leaders("points", 8),
    api.recentResults(8),
    api.upcomingGames(8),
  ]);

  view.appendChild(el("h1", { class: "page-title" },
    "Dashboard ",
    el("span", { class: "page-subtitle" }, `· ${standings.reduce((s,t) => s + t.wins + t.losses, 0) / 2} games played`),
  ));

  const grid = el("div", { class: "grid grid-2" });

  // -- standings card --
  const east = standings.filter(t => t.conference === "East").slice(0, 8);
  const west = standings.filter(t => t.conference === "West").slice(0, 8);
  const standingsCard = el("div", { class: "card" },
    el("div", { class: "card-header" },
      el("div", { class: "card-title" }, "Standings"),
      el("a", { href: "#/standings" }, "View all"),
    ),
    el("div", { class: "grid grid-2" },
      standingsTable(east, "Eastern"),
      standingsTable(west, "Western"),
    ),
  );
  grid.appendChild(standingsCard);

  // -- leaders card --
  const leadersCard = el("div", { class: "card" },
    el("div", { class: "card-header" },
      el("div", { class: "card-title" }, "Scoring Leaders"),
      el("a", { href: "#/leaders" }, "View all"),
    ),
    el("table", { class: "tbl" },
      el("thead", {},
        el("tr", {},
          el("th", {}, "#"),
          el("th", {}, "Player"),
          el("th", {}, "Team"),
          el("th", { class: "num" }, "PPG"),
          el("th", { class: "num" }, "GP"),
        ),
      ),
      el("tbody", {},
        ...leaders.map((l, i) => el("tr", {
            onClick: () => location.hash = `#/players/${l.player_id}`,
          },
          el("td", { class: "num muted" }, String(i + 1)),
          el("td", {},
            el("div", { class: "row" },
              spriteImg(l.sprite_url, l.name).then ? "" : (() => { const img = spriteImg(l.sprite_url, l.name); img.style.width = "32px"; img.style.height = "32px"; return img; })(),
              el("span", {}, l.name),
            ),
          ),
          el("td", { class: "muted" }, teamAbbr(l.team_id)),
          el("td", { class: "num" }, l.per_game.toFixed(1)),
          el("td", { class: "num muted" }, String(l.games)),
        )),
      ),
    ),
  );
  grid.appendChild(leadersCard);

  view.appendChild(grid);

  // -- recent + upcoming --
  const grid2 = el("div", { class: "grid grid-2", style: "margin-top: 1rem;" });
  grid2.appendChild(gameListCard("Recent Results", recent, true));
  grid2.appendChild(gameListCard("Upcoming Games", upcoming, false));
  view.appendChild(grid2);
}

function standingsTable(rows, label) {
  return el("div", {},
    el("div", { class: "muted", style: "font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 0.4rem;" }, label),
    el("table", { class: "tbl" },
      el("thead", {},
        el("tr", {},
          el("th", {}, "Team"),
          el("th", { class: "num" }, "W"),
          el("th", { class: "num" }, "L"),
          el("th", { class: "num" }, "Pct"),
        ),
      ),
      el("tbody", {},
        ...rows.map(t => el("tr", {
            class: "standings-row",
            onClick: () => location.hash = `#/teams/${t.id}`,
          },
          el("td", { class: "team-cell" },
            el("span", { class: "abbr" }, t.abbreviation),
            ` ${t.city} ${t.name}`,
          ),
          el("td", { class: "num" }, String(t.wins)),
          el("td", { class: "num" }, String(t.losses)),
          el("td", { class: "num muted" }, t.win_pct.toFixed(3)),
        )),
      ),
    ),
  );
}

function gameListCard(title, games, completed) {
  return el("div", { class: "card" },
    el("div", { class: "card-header" }, el("div", { class: "card-title" }, title)),
    games.length === 0
      ? el("div", { class: "empty" }, completed ? "No games played yet." : "Season complete!")
      : el("table", { class: "tbl" },
        el("thead", {},
          el("tr", {},
            el("th", {}, "Date"),
            el("th", {}, "Matchup"),
            el("th", { class: "num" }, completed ? "Score" : "Tip-off"),
          ),
        ),
        el("tbody", {},
          ...games.map(g => el("tr", {
              onClick: () => completed ? (location.hash = `#/games/${g.id}`) : null,
            },
            el("td", { class: "muted mono" }, formatDate(g.game_date)),
            el("td", {},
              el("span", {}, `${teamAbbr(g.away_team_id)} @ ${teamAbbr(g.home_team_id)}`),
              g.overtime_periods > 0 ? el("span", { class: "pill pill-warn", style: "margin-left:0.4rem" }, g.overtime_periods === 1 ? "OT" : `${g.overtime_periods}OT`) : null,
            ),
            el("td", { class: "num" }, completed ? `${g.away_score} - ${g.home_score}` : "—"),
          )),
        ),
      ),
  );
}

// =====================================================================
// Standings (full)
// =====================================================================
async function viewStandings(view) {
  const standings = await api.standings();
  view.appendChild(el("h1", { class: "page-title" }, "Standings"));

  const east = standings.filter(t => t.conference === "East");
  const west = standings.filter(t => t.conference === "West");

  const grid = el("div", { class: "grid grid-2" },
    fullStandingsCard("Eastern Conference", east),
    fullStandingsCard("Western Conference", west),
  );
  view.appendChild(grid);
}

function fullStandingsCard(title, rows) {
  return el("div", { class: "card" },
    el("div", { class: "card-header" }, el("div", { class: "card-title" }, title)),
    el("table", { class: "tbl" },
      el("thead", {},
        el("tr", {},
          el("th", {}, "#"),
          el("th", {}, "Team"),
          el("th", { class: "num" }, "W"),
          el("th", { class: "num" }, "L"),
          el("th", { class: "num" }, "PCT"),
          el("th", {}, "Div"),
        ),
      ),
      el("tbody", {},
        ...rows.map((t, i) => el("tr", {
            class: "standings-row",
            onClick: () => location.hash = `#/teams/${t.id}`,
          },
          el("td", { class: "num muted" }, String(i + 1)),
          el("td", { class: "team-cell" },
            el("span", { class: "abbr" }, t.abbreviation),
            ` ${t.city} ${t.name}`,
          ),
          el("td", { class: "num" }, String(t.wins)),
          el("td", { class: "num" }, String(t.losses)),
          el("td", { class: "num muted" }, t.win_pct.toFixed(3)),
          el("td", { class: "muted" }, t.division),
        )),
      ),
    ),
  );
}

// =====================================================================
// Schedule
// =====================================================================
async function viewSchedule(view) {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const filter = params.get("filter") || "all";

  const upcoming = await api.schedule({
    completed: filter === "completed" ? true : (filter === "upcoming" ? false : undefined),
    limit: 200,
  });

  const filterBar = el("div", { class: "row", style: "margin-bottom: 1rem;" },
    filterBtn("All", filter === "all", () => setFilter("all")),
    filterBtn("Upcoming", filter === "upcoming", () => setFilter("upcoming")),
    filterBtn("Completed", filter === "completed", () => setFilter("completed")),
  );

  view.appendChild(el("h1", { class: "page-title" }, "Schedule",
    el("span", { class: "page-subtitle" }, ` · ${upcoming.length} games`)));
  view.appendChild(filterBar);

  // group by date
  const byDate = new Map();
  upcoming.forEach(g => {
    const k = g.game_date;
    if (!byDate.has(k)) byDate.set(k, []);
    byDate.get(k).push(g);
  });

  const card = el("div", { class: "card" });
  if (byDate.size === 0) {
    card.appendChild(el("div", { class: "empty" }, "No games match this filter."));
  } else {
    for (const [date, games] of byDate) {
      card.appendChild(el("div", { class: "section-title", style: "color: var(--text-mute); text-transform: uppercase; letter-spacing: 0.06em; font-size: 0.75rem; margin-top: 0.85rem;" }, formatDate(date)));
      const list = el("table", { class: "tbl" },
        el("tbody", {},
          ...games.map(g => el("tr", {
              onClick: () => g.is_completed ? (location.hash = `#/games/${g.id}`) : null,
              class: g.is_completed ? "" : "no-hover",
            },
            el("td", {}, `${teamAbbr(g.away_team_id)} @ ${teamAbbr(g.home_team_id)}`),
            el("td", { class: "muted" }, g.is_completed ? "Final" : "Scheduled"),
            el("td", { class: "num" },
              g.is_completed
                ? `${g.away_score} - ${g.home_score}${g.overtime_periods > 0 ? (g.overtime_periods === 1 ? " OT" : ` ${g.overtime_periods}OT`) : ""}`
                : "",
            ),
          )),
        ),
      );
      card.appendChild(list);
    }
  }
  view.appendChild(card);
}
function filterBtn(label, active, onClick) {
  return el("button", { class: `btn btn-sm ${active ? "btn-primary" : ""}`, onClick }, label);
}
function setFilter(filter) {
  if (filter === "all") location.hash = "#/schedule";
  else location.hash = `#/schedule?filter=${filter}`;
}

// =====================================================================
// Leaders
// =====================================================================
async function viewLeaders(view) {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const stat = params.get("stat") || "points";

  const choices = [
    ["points", "Points"], ["rebounds", "Rebounds"], ["assists", "Assists"],
    ["steals", "Steals"], ["blocks", "Blocks"],
    ["three_made", "3PM"], ["fg_made", "FGM"], ["minutes", "Minutes"],
  ];

  view.appendChild(el("h1", { class: "page-title" }, "League Leaders"));

  const tabs = el("div", { class: "row", style: "margin-bottom: 1rem; flex-wrap: wrap;" },
    ...choices.map(([k, l]) => el("a", {
        href: `#/leaders?stat=${k}`,
        class: `btn btn-sm ${stat === k ? "btn-primary" : ""}`,
      }, l),
    ),
  );
  view.appendChild(tabs);

  const data = await api.leaders(stat, 25);
  if (data.length === 0) {
    view.appendChild(el("div", { class: "empty" }, "No games played yet — sim some games to populate stats!"));
    return;
  }

  const card = el("div", { class: "card" });
  const table = el("table", { class: "tbl" },
    el("thead", {},
      el("tr", {},
        el("th", {}, "#"),
        el("th", {}, "Player"),
        el("th", {}, "Team"),
        el("th", {}, "Pos"),
        el("th", { class: "num" }, "Per Game"),
        el("th", { class: "num" }, "Total"),
        el("th", { class: "num" }, "GP"),
        el("th", { class: "num" }, "MPG"),
      ),
    ),
    el("tbody", {},
      ...data.map((l, i) => el("tr", { onClick: () => location.hash = `#/players/${l.player_id}` },
        el("td", { class: "num muted" }, String(i + 1)),
        el("td", {}, el("div", { class: "row" },
          (() => { const img = spriteImg(l.sprite_url, l.name); img.style.width = "36px"; img.style.height = "36px"; return img; })(),
          el("span", {}, l.name),
          el("span", { class: "muted", style: "font-size: 0.8rem;" }, l.badge),
        )),
        el("td", { class: "muted" }, teamAbbr(l.team_id)),
        el("td", {}, el("span", { class: "tag-pos" }, l.position)),
        el("td", { class: "num" }, l.per_game.toFixed(1)),
        el("td", { class: "num muted" }, String(l.total)),
        el("td", { class: "num muted" }, String(l.games)),
        el("td", { class: "num muted" }, l.minutes_per_game.toFixed(1)),
      )),
    ),
  );
  card.appendChild(table);
  view.appendChild(card);
}

// =====================================================================
// Free Agents
// =====================================================================
async function viewFreeAgents(view) {
  const [fas, capCfg, teams] = await Promise.all([
    api.freeAgents(200),
    loadCapConfig(),
    loadTeams(),
  ]);
  view.appendChild(el("h1", { class: "page-title" }, "Free Agents",
    el("span", { class: "page-subtitle" }, ` · ${fas.length} available`)));

  view.appendChild(capBannerCard(capCfg));

  if (isTeamGmMode()) {
    view.appendChild(el("div", { class: "card", style: "padding: 0.75rem 1rem; margin-bottom: 1rem;" },
      el("span", { class: "muted" }, `Team GM · signing to `),
      el("strong", {}, teamLabel(getUserTeamId())),
    ));
  }

  if (fas.length === 0) {
    view.appendChild(el("div", { class: "empty" }, "No free agents available."));
    return;
  }

  fas.sort((a, b) => b.bst - a.bst);

  const grid = el("div", { class: "grid grid-3" });
  fas.forEach(p => {
    const sign = el("button", { class: "btn btn-sm btn-primary", onClick: async (e) => {
      e.preventDefault();
      e.stopPropagation();
      let teamId = getUserTeamId();
      if (!isTeamGmMode()) {
        teamId = await pickTeam(teams, "Sign to which team?");
        if (teamId == null) return;
      }
      try {
        await api.sign(teamId, p.id);
        toast(`Signed ${p.name} to ${teamAbbr(teamId)}`, "success");
        router();
      } catch (err) { toast(err.message, "error"); }
    } }, isTeamGmMode() ? `Sign to ${teamAbbr(getUserTeamId())}` : "Sign");
    const tile = playerTile(p, { right: sign });
    grid.appendChild(tile);
  });
  view.appendChild(grid);
}

function capBannerCard(capCfg) {
  return el("div", { class: "card cap-banner" },
    el("div", { class: "cap-banner-cell" },
      el("div", { class: "cap-banner-label" }, "Salary cap"),
      el("div", { class: "cap-banner-value" }, fmtNum(capCfg.bst_cap), el("span", { class: "muted mono" }, " BST")),
    ),
    el("div", { class: "cap-banner-sep" }),
    el("div", { class: "cap-banner-cell" },
      el("div", { class: "cap-banner-label" }, "Trade leeway"),
      el("div", { class: "cap-banner-value" },
        el("span", { class: "tone-warn" }, `+${fmtNum(capCfg.trade_cap_leeway)}`),
        el("span", { class: "muted mono" }, " BST"),
      ),
      el("div", { class: "cap-banner-hint muted" }, "How far over you can go via trades"),
    ),
    el("div", { class: "cap-banner-sep" }),
    el("div", { class: "cap-banner-cell" },
      el("div", { class: "cap-banner-label" }, "Hard ceiling"),
      el("div", { class: "cap-banner-value" }, fmtNum(capCfg.max_total_with_leeway), el("span", { class: "muted mono" }, " BST")),
      el("div", { class: "cap-banner-hint muted" }, `Roster ${capCfg.roster_min_after_trade}–${capCfg.roster_max_after_trade}`),
    ),
  );
}

async function pickTeam(teams, prompt = "Select a team") {
  return new Promise((resolve) => {
    const overlay = el("div", { style: "position: fixed; inset: 0; background: rgba(0,0,0,0.6); z-index: 200; display: flex; align-items: center; justify-content: center;" });
    const dialog = el("div", { class: "card", style: "max-width: 480px; width: 90%; max-height: 80vh; overflow-y: auto;" },
      el("h3", { style: "margin-top:0;" }, prompt),
    );
    const list = el("div", { class: "grid", style: "gap: 0.4rem;" });
    teams.forEach(t => {
      list.appendChild(el("button", {
        class: "btn",
        style: "justify-content: flex-start; text-align: left;",
        onClick: () => { document.body.removeChild(overlay); resolve(t.id); },
      }, `${t.abbreviation} · ${t.city} ${t.name} (${t.wins}-${t.losses})`));
    });
    dialog.appendChild(list);
    dialog.appendChild(el("div", { style: "margin-top: 0.5rem; text-align: right;" },
      el("button", { class: "btn btn-ghost btn-sm", onClick: () => { document.body.removeChild(overlay); resolve(null); } }, "Cancel"),
    ));
    overlay.addEventListener("click", (e) => { if (e.target === overlay) { document.body.removeChild(overlay); resolve(null); } });
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);
  });
}

// =====================================================================
// Badges
// =====================================================================
async function viewBadges(view) {
  const data = await api.badges();
  view.appendChild(el("h1", { class: "page-title" }, "Badge Catalog"));

  const grid = el("div", { class: "grid grid-3" });
  for (const [name, def] of Object.entries(data)) {
    const card = el("div", { class: "card" },
      el("div", { class: "row-spaced" },
        el("div", { class: "card-title" }, name),
        el("span", { class: "pill" }, def.trigger),
      ),
      el("p", { class: "muted", style: "margin: 0.5rem 0 0;" }, def.description),
    );
    grid.appendChild(card);
  }
  view.appendChild(grid);
}

// =====================================================================
// Team detail
// =====================================================================
async function viewTeam(view, teamId) {
  const [team, , capCfg] = await Promise.all([api.team(teamId), loadTeams(), loadCapConfig()]);
  team.roster.sort((a, b) => b.bst - a.bst);

  view.appendChild(buildTeamHeader(team, capCfg));

  if (isTeamGmMode() && !canManageTeam(team.id)) {
    view.appendChild(el("div", { class: "card", style: "padding: 0.75rem 1rem; margin-bottom: 1rem;" },
      el("span", { class: "muted" }, "View-only in Team GM mode. You control "),
      el("strong", {}, teamLabel(getUserTeamId())),
      el("span", { class: "muted" }, "."),
    ));
  }

  const rosterCard = el("div", { class: "card" },
    el("div", { class: "card-header" }, el("div", { class: "card-title" }, "Roster")),
    el("div", { class: "grid grid-3" },
      ...team.roster.map(p => playerTile(p, {
        right: canManageTeam(team.id) ? el("button", { class: "btn btn-sm", onClick: async (e) => {
          e.preventDefault(); e.stopPropagation();
          const confirmed = await confirmRelease(team, p);
          if (!confirmed) return;
          try {
            await api.release(team.id, p.id);
            toast(`Released ${p.name}`, "success");
            router();
          } catch (err) { toast(err.message, "error"); }
        } }, "Cut") : null,
      })),
    ),
  );
  view.appendChild(rosterCard);
}

function buildTeamHeader(team, capCfg) {
  const overCap = team.bst_used > team.bst_cap;
  const overLeeway = team.bst_used > capCfg.max_total_with_leeway;
  // The bar's full width represents 0 → max_total_with_leeway.
  const total = capCfg.max_total_with_leeway;
  const usagePct = Math.min(100, (team.bst_used / total) * 100);
  const capPct = Math.min(100, (team.bst_cap / total) * 100);

  let pill;
  if (overLeeway) pill = el("span", { class: "pill pill-accent" }, `+${team.bst_used - capCfg.max_total_with_leeway} OVER MAX`);
  else if (overCap) pill = el("span", { class: "pill pill-warn" }, `+${team.bst_used - team.bst_cap} OVER CAP`);
  else pill = el("span", { class: "pill pill-success" }, `${team.cap_room} ROOM`);

  return el("section", { class: "team-header" },
    el("div", { style: "min-width: 0; flex: 1;" },
      el("div", { class: "muted", style: "font-size: 0.85rem; letter-spacing: 0.04em; text-transform: uppercase;" }, `${team.conference} · ${team.division}`),
      el("h2", {}, `${team.city} ${team.name}`),
      el("div", { class: "team-meta" }, `${team.roster.length} players · cap ${fmtNum(team.bst_cap)} · trade ceiling ${fmtNum(capCfg.max_total_with_leeway)}`),
      el("div", {
          class: "cap-bar two-tone" + (overCap ? " over" : "") + (overLeeway ? " over-max" : ""),
          style: `--cap-pct:${capPct}%;`,
        },
        el("div", { class: "fill", style: `width:${usagePct}%` }),
        el("div", { class: "cap-line", style: `left:${capPct}%`, title: `Cap line: ${fmtNum(team.bst_cap)}` }),
      ),
      el("div", { class: "cap-meta" },
        el("span", {}, `${fmtNum(team.bst_used)} used`),
        pill,
        el("span", { class: "muted" }, `+${fmtNum(capCfg.trade_cap_leeway)} trade leeway → max ${fmtNum(capCfg.max_total_with_leeway)}`),
      ),
    ),
    el("div", { style: "text-align: right;" },
      el("div", { class: "muted", style: "font-size: 0.85rem;" }, "Record"),
      el("div", { class: "record" }, `${team.wins}-${team.losses}`),
    ),
  );
}

// =====================================================================
// Release confirmation with projected-win delta
// =====================================================================
async function confirmRelease(team, player) {
  // Try to fetch projection; fall back to a plain confirm if it fails.
  let projection = null;
  try { projection = await api.releaseProjection(team.id, player.id); }
  catch (err) { console.warn("projection failed:", err); }

  return new Promise((resolve) => {
    const overlay = el("div", { class: "modal-overlay" });
    const closing = (val) => () => { overlay.remove(); resolve(val); };

    const winsBefore = projection?.current?.projected_wins;
    const winsAfter = projection?.after?.projected_wins;
    const bstBefore = projection?.current?.bst_used ?? team.bst_used;
    const bstAfter = projection?.after?.bst_used ?? (bstBefore - player.bst);

    const modal = el("div", { class: "card modal-dialog" },
      el("div", { class: "modal-head" },
        el("div", {},
          el("div", { class: "modal-eyebrow" }, "Release player"),
          el("h3", { class: "modal-title" }, player.name),
        ),
        el("div", { class: "row" },
          el("span", { class: "tag-pos" }, player.position),
          el("span", { class: "pill pill-info" }, player.badge),
          el("span", { class: "pill" }, `BST ${player.bst}`),
        ),
      ),

      projection
        ? el("div", { class: "projection-grid" },
            projectionRow("Predicted Wins", `${winsBefore} → ${winsAfter}`),
            projectionRow("Roster Size",
              `${projection.current.roster_size} → ${projection.after.roster_size}`),
            projectionRow("BST Used",
              `${fmtNum(bstBefore)} → ${fmtNum(bstAfter)}`),
          )
        : el("div", { class: "muted", style: "padding: 0.5rem 0;" }, "Couldn't load a projection — proceed if you really want to cut."),

      el("div", { class: "modal-actions" },
        el("button", { class: "btn btn-ghost", onClick: closing(false) }, "Cancel"),
        el("button", { class: "btn btn-danger", onClick: closing(true) }, `Release ${player.name}`),
      ),
    );

    overlay.addEventListener("click", (e) => { if (e.target === overlay) closing(false)(); });
    document.addEventListener("keydown", function escListener(e) {
      if (e.key === "Escape") { document.removeEventListener("keydown", escListener); closing(false)(); }
    });
    overlay.appendChild(modal);
    document.body.appendChild(overlay);
  });
}

function projectionRow(label, value) {
  return el("div", { class: "projection-row" },
    el("div", { class: "projection-label" }, label),
    el("div", { class: "projection-value" }, value),
  );
}

// =====================================================================
// Player detail
// =====================================================================
async function viewPlayer(view, playerId) {
  const [p, injuryProfile] = await Promise.all([
    api.player(playerId),
    api.playerInjuries(playerId).catch(() => null),
  ]);
  const teamLink = p.team_id != null ? el("a", { href: `#/teams/${p.team_id}` }, teamLabel(p.team_id)) : el("span", { class: "muted" }, "Free Agent");

  view.appendChild(el("h1", { class: "page-title" }, p.name,
    el("span", { class: "page-subtitle" }, ` · ${p.species} #${p.pokedex_id}`),
  ));

  if (injuryProfile?.current?.is_injured) {
    view.appendChild(el("div", { class: "card injury-report", style: "padding: 0.75rem 1rem; margin-bottom: 1rem;" },
      el("div", { class: "row-spaced" },
        el("div", {},
          el("div", { class: "muted", style: "font-size: 0.78rem; text-transform: uppercase;" }, "Injured"),
          el("div", { style: "font-weight: 700;" },
            `Out ${injuryProfile.current.games_remaining} more game${injuryProfile.current.games_remaining === 1 ? "" : "s"}`,
          ),
        ),
        el("button", {
          class: "btn btn-sm btn-ghost",
          type: "button",
          onClick: () => showInjuryHistoryModal(playerId, p.name),
        }, "Injury history"),
      ),
    ));
  } else if (injuryProfile?.events?.length) {
    view.appendChild(el("div", { style: "margin-bottom: 1rem;" },
      el("button", {
        class: "btn btn-sm btn-ghost",
        type: "button",
        onClick: () => showInjuryHistoryModal(playerId, p.name),
      }, "View injury history"),
    ));
  }

  const detail = el("section", { class: "player-detail" },
    el("div", { class: "artwork" },
      safeImg(p.artwork_url, p.species),
      el("div", { style: "margin-top: 0.5rem;" },
        el("span", { class: "tag-pos" }, p.position),
        " ",
        el("span", { class: "pill pill-info" }, p.badge),
        " ",
        p.is_regen ? el("span", { class: "pill pill-warn" }, `Gen ${p.generation}`) : null,
      ),
      el("div", { class: "muted", style: "margin-top: 0.6rem;" },
        `Age ${p.age} · ${p.seasons_played}/${p.career_length} seasons`,
      ),
      el("div", { class: "muted", style: "margin-top: 0.4rem;" }, "Team: ", teamLink),
    ),
    el("div", {},
      el("div", { class: "card" },
        el("div", { class: "card-header" },
          el("div", { class: "card-title" }, "Stats"),
          el("div", { class: "muted mono" }, `BST ${p.bst}`),
        ),
        statBar("HP (Stamina)", p.cur_hp, 200),
        statBar("Attack (Inside)", p.cur_attack, 180),
        statBar("Defense (Interior)", p.cur_defense, 200),
        statBar("Sp. Attack (Outside)", p.cur_sp_attack, 180),
        statBar("Sp. Defense (Perimeter)", p.cur_sp_defense, 180),
        statBar("Speed (Pace)", p.cur_speed, 180),
      ),
      el("div", { class: "card", style: "margin-top: 1rem;" },
        el("div", { class: "card-title" }, "Ability"),
        el("p", { class: "muted" }, `${p.ability_name} → ${p.badge}`),
      ),
    ),
  );
  view.appendChild(detail);
}
function statBar(label, val, max) {
  const w = Math.min(100, (val / max) * 100);
  return el("div", { class: "stat-bar" },
    el("div", { class: "label" }, label),
    el("div", { class: "track" }, el("div", { class: "fill", style: `width:${w}%` })),
    el("div", { class: "val" }, String(val)),
  );
}

// =====================================================================
// Game (box score)
// =====================================================================
async function viewGame(view, gameId) {
  const [box, games] = await Promise.all([
    api.boxScore(gameId),
    api.schedule({ limit: 2000 }),
  ]);
  const game = games.find(g => g.id === Number(gameId));
  if (!game) {
    view.appendChild(el("div", { class: "empty" }, "Game not found."));
    return;
  }
  const homeTeam = teamCache.get(game.home_team_id);
  const awayTeam = teamCache.get(game.away_team_id);
  const homeWin = game.home_score > game.away_score;

  // Need player details for sprites + names
  const playerDetails = await Promise.all(box.map(b => api.player(b.player_id)));
  const playerById = new Map(playerDetails.map(p => [p.id, p]));

  view.appendChild(el("section", { class: "score-banner" },
    el("div", { class: `team-side ${homeWin ? "" : "winner"}` },
      el("div", { class: "team-name" }, `${awayTeam.city} ${awayTeam.name}`),
      el("div", { class: "score" }, String(game.away_score)),
    ),
    el("div", { class: "vs" },
      el("div", {}, "FINAL"),
      game.overtime_periods > 0 ? el("div", { class: "muted" }, game.overtime_periods === 1 ? "OT" : `${game.overtime_periods}OT`) : null,
      el("div", { class: "muted", style: "font-size: 0.8rem;" }, formatDate(game.game_date)),
    ),
    el("div", { class: `team-side ${homeWin ? "winner" : ""}` },
      el("div", { class: "team-name" }, `${homeTeam.city} ${homeTeam.name}`),
      el("div", { class: "score" }, String(game.home_score)),
    ),
  ));

  const grid = el("div", { class: "grid grid-2" },
    boxTeamCard(awayTeam, box.filter(b => b.team_id === game.away_team_id), playerById),
    boxTeamCard(homeTeam, box.filter(b => b.team_id === game.home_team_id), playerById),
  );
  view.appendChild(grid);
}

function boxTeamCard(team, rows, playerById) {
  rows.sort((a, b) => (b.is_starter - a.is_starter) || (b.minutes - a.minutes));
  return el("div", { class: "card" },
    el("div", { class: "card-header" }, el("div", { class: "card-title" }, `${team.city} ${team.name}`)),
    el("table", { class: "box-table" },
      el("thead", {},
        el("tr", {},
          el("th", {}, "Player"),
          el("th", { class: "num" }, "MIN"),
          el("th", { class: "num" }, "PTS"),
          el("th", { class: "num" }, "REB"),
          el("th", { class: "num" }, "AST"),
          el("th", { class: "num" }, "STL"),
          el("th", { class: "num" }, "BLK"),
          el("th", { class: "num" }, "TO"),
          el("th", { class: "num" }, "FG"),
          el("th", { class: "num" }, "3PT"),
        ),
      ),
      el("tbody", {},
        ...rows.map(r => {
          const p = playerById.get(r.player_id);
          return el("tr", {
              class: r.is_starter ? "starter" : "",
              onClick: () => location.hash = `#/players/${r.player_id}`,
            },
            el("td", { class: "player-cell" },
              p ? (() => { const img = spriteImg(p.sprite_url, p.name); img.className = "mini-sprite"; return img; })() : null,
              el("span", {}, p ? p.name : `pid ${r.player_id}`),
              p ? el("span", { class: "tag-pos", style: "margin-left:auto;" }, p.position) : null,
            ),
            el("td", { class: "num" }, r.minutes.toFixed(1)),
            el("td", { class: "num" }, String(r.points)),
            el("td", { class: "num" }, String(r.rebounds)),
            el("td", { class: "num" }, String(r.assists)),
            el("td", { class: "num" }, String(r.steals)),
            el("td", { class: "num" }, String(r.blocks)),
            el("td", { class: "num" }, String(r.turnovers)),
            el("td", { class: "num" }, `${r.fg_made}/${r.fg_attempted}`),
            el("td", { class: "num" }, `${r.three_made}/${r.three_attempted}`),
          );
        }),
      ),
    ),
  );
}

// =====================================================================
// Playoffs view
// =====================================================================
async function viewPlayoffs(view) {
  const [bracket, state] = await Promise.all([api.bracket(), loadLeagueState()]);
  view.appendChild(el("h1", { class: "page-title" }, `${state.current_season} Playoffs`,
    el("span", { class: "page-subtitle" }, ` · ${state.phase === "playoffs" ? "live" : "complete"}`),
  ));

  const banner = champBannerIfDone(state);
  if (banner) view.appendChild(banner);

  if (_lastPlayoffInjuryReport) {
    view.appendChild(injuryReportCard(_lastPlayoffInjuryReport));
  }

  if (state.phase === "playoffs") {
    const slateNum = bracket.slate?.slate_game ?? await fetchPlayoffSlateNum();
    view.appendChild(playoffSimToolbar(slateNum));
  }

  const byRound = new Map([[1, []], [2, []], [3, []], [4, []]]);
  bracket.series.forEach(s => byRound.get(s.round).push(s));

  const roundLabels = {
    1: "First Round",
    2: "Conference Semis",
    3: "Conference Finals",
    4: "NBA Finals",
  };

  const grid = el("div", { class: "bracket-grid" });
  for (const r of [1, 2, 3, 4]) {
    const seriesList = byRound.get(r);
    if (!seriesList || seriesList.length === 0) {
      grid.appendChild(el("div", { class: "bracket-col" },
        el("div", { class: "bracket-col-title" }, roundLabels[r]),
        el("div", { class: "muted bracket-pending" }, "Pending"),
      ));
      continue;
    }
    seriesList.sort((a, b) => (a.bracket > b.bracket ? 1 : a.bracket < b.bracket ? -1 : a.slot_index - b.slot_index));
    const col = el("div", { class: "bracket-col" },
      el("div", { class: "bracket-col-title" }, roundLabels[r]),
      ...seriesList.map(s => seriesCard(s)),
    );
    grid.appendChild(col);
  }
  view.appendChild(grid);
}

function seriesCard(s) {
  const high = teamCache.get(s.high_seed_team_id);
  const low  = teamCache.get(s.low_seed_team_id);
  const highWon = s.is_completed && s.winner_team_id === s.high_seed_team_id;
  const lowWon  = s.is_completed && s.winner_team_id === s.low_seed_team_id;

  return el("div", { class: `series-card ${s.is_completed ? "complete" : "live"}` },
    el("div", { class: "series-meta muted" }, s.bracket === "Finals" ? "FINALS" : `${s.bracket} · slot ${s.slot_index + 1}`),
    seriesRow(s.high_seed, high, s.high_seed_wins, highWon),
    seriesRow(s.low_seed,  low,  s.low_seed_wins,  lowWon),
  );
}

function seriesRow(seed, team, wins, won) {
  return el("div", { class: `series-row${won ? " winner" : ""}` },
    el("span", { class: "series-seed" }, seed ? String(seed) : "—"),
    el("a", {
        class: "series-team",
        href: team ? `#/teams/${team.id}` : "#",
      },
      team ? `${team.abbreviation} ${team.city} ${team.name}` : "TBD",
    ),
    el("span", { class: "series-wins" }, String(wins)),
  );
}

function champBannerIfDone(state) {
  if (state.last_champion_season !== state.current_season || !state.champion_team_id) return null;
  const champ = teamCache.get(state.champion_team_id);
  if (!champ) return null;
  const finals = state.last_finals;
  return el("div", { class: "champ-banner" },
    el("div", { class: "champ-emoji", "aria-hidden": "true" }, "★"),
    el("div", {},
      el("div", { class: "champ-eyebrow" }, `Season ${state.last_champion_season} Champion`),
      el("div", { class: "champ-name" }, `${champ.city} ${champ.name}`),
      finals ? el("div", { class: "champ-meta muted" },
        `Defeated ${finals.runner_up_abbr} ${finals.high_seed_wins}-${finals.low_seed_wins}`,
      ) : null,
    ),
  );
}

function injuryReportCard(report) {
  const card = el("div", { class: "card injury-report" },
    el("div", { class: "card-header" },
      el("div", { class: "card-title" }, "Latest Game — Injury Report"),
      el("span", { class: "pill pill-warn" }, `${report.new_injuries?.length ?? 0} new`),
    ),
  );

  const newInj = report.new_injuries || [];
  const out = report.unavailable || [];

  if (newInj.length === 0 && out.length === 0) {
    card.appendChild(el("div", { class: "muted", style: "padding: 0.25rem 0;" }, "No injuries this game."));
    return card;
  }

  if (newInj.length > 0) {
    card.appendChild(el("div", { class: "injury-section-title" }, "New injuries"));
    const list = el("div", { class: "injury-list" });
    newInj.forEach((inj) => {
      list.appendChild(el("div", { class: "injury-row injury-row-new" },
        el("div", { class: "injury-sprite" }, spriteImg(inj.sprite_url, inj.player_name)),
        el("div", { class: "injury-body" },
          el("div", { class: "injury-name" }, inj.player_name),
          el("div", { class: "injury-meta muted" },
            `${teamAbbr(inj.team_id)} · out ${inj.games_out} game${inj.games_out === 1 ? "" : "s"}`,
          ),
        ),
      ));
    });
    card.appendChild(list);
  }

  const sitting = out.filter(u => u.reason === "existing");
  if (sitting.length > 0) {
    card.appendChild(el("div", { class: "injury-section-title" }, "Still sidelined"));
    const list = el("div", { class: "injury-list" });
    sitting.forEach((u) => {
      list.appendChild(el("div", { class: "injury-row" },
        el("div", { class: "injury-sprite" }, spriteImg(u.sprite_url, u.player_name)),
        el("div", { class: "injury-body" },
          el("div", { class: "injury-name" }, u.player_name),
          el("div", { class: "injury-meta muted" },
            `${teamAbbr(u.team_id)} · ${u.games_remaining} game${u.games_remaining === 1 ? "" : "s"} left`,
          ),
        ),
      ));
    });
    card.appendChild(list);
  }

  return card;
}

function notifyPlayoffInjuries(report, scoreText) {
  if (!report) {
    toast(scoreText || "Game simmed", "success");
    return;
  }
  _lastPlayoffInjuryReport = report;
  const n = report.new_injuries?.length ?? 0;
  if (n === 0) {
    toast(scoreText ? `${scoreText} · no injuries` : "Game simmed · no injuries", "success");
    return;
  }
  const names = report.new_injuries.slice(0, 3).map(i => `${i.player_name} (${i.games_out}G)`).join(", ");
  const extra = n > 3 ? ` +${n - 3} more` : "";
  toast(`${scoreText ? scoreText + " · " : ""}Injured: ${names}${extra}`, "warn");
}

async function fetchPlayoffSlateNum() {
  try {
    const bracket = await api.bracket();
    return bracket.slate?.slate_game ?? 1;
  } catch (err) {
    console.warn("bracket load failed:", err);
    return 1;
  }
}

function wirePlayoffSimButtons(primary, secondary, tertiary, slateNum) {
  primary.textContent = `Sim Game ${slateNum}`;
  primary.title = `Sim Game ${slateNum} in every active series this round`;
  primary.onclick = () => simAction(primary, async () => {
    const r = await api.simPlayoffSlate();
    if (r?.transition?.transition === "playoffs -> draft") {
      toast("Champion crowned! Time to draft.", "success");
    } else {
      const s = r?.summary;
      notifyPlayoffInjuries(
        s?.injury_report,
        s ? `Game ${s.slate_game} · ${s.games_played} games` : null,
      );
    }
  });

  secondary.textContent = "Sim 1 Game";
  secondary.title = "Sim the next game in one series";
  secondary.onclick = () => simAction(secondary, async () => {
    const r = await api.simPlayoffGame();
    if (r?.transition?.transition === "playoffs -> draft") {
      toast("Champion crowned! Time to draft.", "success");
    } else {
      notifyPlayoffInjuries(r?.result?.injury_report, r?.result?.latest_score);
    }
  });

  if (tertiary) {
    tertiary.classList.remove("hidden");
    tertiary.textContent = "Sim 1 Round";
    tertiary.title = "Sim the rest of the current round";
    tertiary.onclick = () => simAction(tertiary, async () => {
      const r = await api.simPlayoffRound();
      if (r?.transition?.transition === "playoffs -> draft") {
        toast("Champion crowned! Time to draft.", "success");
      } else {
        const reports = r?.summary?.injury_reports || [];
        const totalInj = reports.reduce((n, rep) => n + (rep.new_injuries?.length ?? 0), 0);
        _lastPlayoffInjuryReport = reports.length ? reports[reports.length - 1] : null;
        toast(
          `Round simmed · ${r?.summary?.games_played ?? 0} games` +
          (totalInj ? ` · ${totalInj} injuries` : ""),
          totalInj ? "warn" : "success",
        );
      }
    });
  }
}

function playoffSimToolbar(slateNum) {
  const primary = el("button", { class: "btn btn-primary", type: "button" });
  const secondary = el("button", { class: "btn btn-ghost", type: "button" });
  const tertiary = el("button", { class: "btn btn-ghost", type: "button" });
  wirePlayoffSimButtons(primary, secondary, tertiary, slateNum);
  return el("div", { class: "playoffs-toolbar card" },
    el("div", { class: "playoffs-toolbar-label muted" }, "Simulate"),
    primary,
    secondary,
    tertiary,
  );
}

// =====================================================================
// Draft room
// =====================================================================
async function viewDraft(view) {
  const draft = await api.draftState();
  view.appendChild(el("h1", { class: "page-title" }, `${draft.season} Draft`,
    el("span", { class: "page-subtitle" }, ` · pick ${Math.min(draft.current_pick + 1, draft.total_picks)} of ${draft.total_picks}`),
  ));

  if (draft.is_complete) {
    view.appendChild(el("div", { class: "card", style: "padding:1rem;" },
      el("h3", { style: "margin: 0 0 0.5rem;" }, "Draft complete!"),
      el("p", { class: "muted", style: "margin: 0 0 0.75rem;" }, "Click \"Start Next Season\" up top to spin up the new schedule."),
    ));
  } else if (draft.on_clock) {
    const onClock = draft.on_clock;
    view.appendChild(el("div", { class: "draft-onclock card" },
      el("div", {},
        el("div", { class: "muted", style: "font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em;" }, `Pick ${onClock.pick_number} · On the Clock`),
        el("div", { class: "draft-onclock-team" }, onClock.owning_team_name || `Team ${onClock.owning_team_id}`),
        onClock.via ? el("div", { class: "muted" }, onClock.via) : null,
      ),
      el("div", { class: "draft-onclock-actions" },
        el("button", { class: "btn btn-primary", onClick: () => doDraft(api.draftAutoPick) }, "Auto-pick best"),
        el("button", { class: "btn btn-ghost", onClick: () => doDraft(api.draftSimRest) }, "Sim rest of draft"),
      ),
    ));
  }

  // Side-by-side: pick log on the left, available rookies on the right.
  const grid = el("div", { class: "grid grid-2", style: "gap: 1rem;" });

  // Pick log
  const log = el("div", { class: "card" },
    el("div", { class: "card-header" }, el("div", { class: "card-title" }, "Pick Log")),
    el("table", { class: "tbl" },
      el("thead", {},
        el("tr", {},
          el("th", { class: "num" }, "#"),
          el("th", {}, "Team"),
          el("th", {}, "Selection"),
        ),
      ),
      el("tbody", {},
        ...draft.picks.map(pk => el("tr", {
            class: pk.is_used ? "" : "no-hover",
            onClick: pk.drafted_player_id ? () => location.hash = `#/players/${pk.drafted_player_id}` : null,
          },
          el("td", { class: "num muted" }, String(pk.pick_number)),
          el("td", { class: "muted" }, pk.owning_abbr || `T${pk.owning_team_id}`),
          el("td", {},
            pk.is_used && pk.drafted_player_name
              ? el("div", { class: "row" },
                  pk.drafted_player_sprite ? (() => { const i = spriteImg(pk.drafted_player_sprite, pk.drafted_player_name); i.style.width = "28px"; i.style.height = "28px"; return i; })() : null,
                  el("span", {}, pk.drafted_player_name),
                  pk.drafted_player_position ? el("span", { class: "tag-pos" }, pk.drafted_player_position) : null,
                  pk.drafted_player_bst ? el("span", { class: "muted mono", style: "font-size: 0.78rem;" }, `BST ${pk.drafted_player_bst}`) : null,
                )
              : el("span", { class: "muted" }, draft.is_complete ? "—" : "—"),
          ),
        )),
      ),
    ),
  );
  grid.appendChild(log);

  // Available rookies
  const board = el("div", { class: "card" },
    el("div", { class: "card-header" }, el("div", { class: "card-title" }, `Available rookies (${draft.available.length})`)),
    el("div", { class: "muted", style: "font-size: 0.85rem; padding: 0 0.6rem 0.5rem;" },
      "Picks count for half BST during the first 3 seasons (rookie deal)."),
    el("div", { class: "draft-board" }, ...draft.available.map(p => draftCard(p, draft))),
  );
  grid.appendChild(board);

  view.appendChild(grid);
}

function draftCard(p, draft) {
  return el("div", { class: "card draft-card" },
    el("div", { class: "draft-card-sprite" }, spriteImg(p.sprite_url, p.name)),
    el("div", { class: "draft-card-body" },
      el("div", { class: "draft-card-name" }, p.name),
      el("div", { class: "draft-card-meta" },
        el("span", { class: "tag-pos" }, p.position),
        el("span", { class: "muted", style: "font-size: 0.78rem;" }, p.badge),
      ),
      el("div", { class: "draft-card-stats" },
        el("span", {}, `BST ${p.bst}`),
        el("span", { class: "muted" }, `· rookie ${p.effective_bst}`),
      ),
    ),
    !draft.is_complete
      ? el("button", {
          class: "btn btn-primary btn-sm",
          onClick: () => doDraft(() => api.draftPick(p.id)),
        }, `Draft ${draft.on_clock?.owning_team_abbr || ""}`)
      : null,
  );
}

async function doDraft(callable) {
  const phaseBtn = $("#phase-action-btn");
  if (phaseBtn) phaseBtn.disabled = true;
  try {
    const result = await callable();
    invalidateState();
    if (result?.transition?.transition === "draft -> pre_season") {
      toast("Draft complete! Start the next season up top.", "success");
    } else if (result?.pick) {
      toast(`Pick ${result.pick.pick_number}: ${result.pick.player.name} → ${teamAbbr(result.pick.team_id)}`, "success");
    }
    router();
  } catch (err) {
    toast(err.message, "error");
  } finally {
    if (phaseBtn) phaseBtn.disabled = false;
  }
}

// =====================================================================
// Phase-aware topbar (sim buttons, top-left action button, nav tabs)
// =====================================================================
const PHASE_LABEL = {
  regular_season: "Regular Season",
  playoffs: "Playoffs",
  draft: "Draft",
  pre_season: "Pre-Season",
};

async function refreshPhaseUI() {
  let state;
  try {
    state = await loadLeagueState();
  } catch (err) {
    // Silently degrade — UI won't crash if /api/league/state is unavailable.
    console.warn("league state load failed:", err);
    return;
  }

  $("#season-pill").textContent = `Season ${state.current_season}`;
  $("#phase-pill").textContent = PHASE_LABEL[state.phase] || state.phase;
  $("#phase-pill").className = `pill pill-phase pill-phase-${state.phase}`;

  // Show/hide nav tabs that only make sense in certain phases.
  const playoffsTab = $("#playoffs-tab");
  const draftTab = $("#draft-tab");
  const playoffsVisible = state.phase === "playoffs"
    || (state.phase !== "regular_season" && state.last_champion_season === state.current_season);
  playoffsTab.classList.toggle("hidden", !playoffsVisible);
  draftTab.classList.toggle("hidden", state.phase !== "draft");

  // Configure sim buttons based on phase.
  const primary = $("#sim-primary-btn");
  const secondary = $("#sim-secondary-btn");
  const tertiary = $("#sim-tertiary-btn");
  primary.classList.remove("hidden");
  secondary.classList.remove("hidden");
  tertiary.classList.add("hidden");
  primary.onclick = null;
  secondary.onclick = null;
  tertiary.onclick = null;

  if (state.phase === "regular_season") {
    primary.textContent = "Sim 1 Day";
    primary.title = "Sim one game day";
    primary.onclick = () => simAction(primary, async () => {
      const r = await api.simDay();
      handleRegularSeasonSimResult(r);
    });
    secondary.textContent = "Sim Week";
    secondary.title = "Sim 7 game days (or until the regular season ends)";
    secondary.onclick = () => simAction(secondary, async () => {
      let total = 0;
      let lastTransition = null;
      const weekMoves = [];
      const weekInjuries = { new_injuries: [], unavailable: [] };
      for (let i = 0; i < 7; i++) {
        let r;
        try { r = await api.simDay(); } catch (e) { break; }
        total += r.games_played || 0;
        if (r?.cpu_moves?.length) weekMoves.push(...r.cpu_moves);
        if (r?.injury_report) {
          weekInjuries.new_injuries.push(...(r.injury_report.new_injuries || []));
          weekInjuries.unavailable.push(...(r.injury_report.unavailable || []));
        }
        invalidateState();
        if (r?.transition) { lastTransition = r.transition; break; }
      }
      if (lastTransition?.transition === "regular_season -> playoffs") {
        toast(`Week simmed (${total} games) — playoffs are set!`, "success");
      } else {
        toast(`Simmed week — ${total} games`, "success");
      }
      if (weekInjuries.new_injuries.length || weekInjuries.unavailable.length) {
        notifyPlayoffInjuries(weekInjuries, `Week sim · ${total} games`);
      }
      if (weekMoves.length) showCpuMovesModal(weekMoves);
    });
  } else if (state.phase === "playoffs") {
    const slateNum = await fetchPlayoffSlateNum();
    wirePlayoffSimButtons(primary, secondary, tertiary, slateNum);
  } else if (state.phase === "draft") {
    primary.textContent = "Auto-pick";
    primary.title = "Make the best-available pick for the team on the clock";
    primary.onclick = () => simAction(primary, async () => {
      const r = await api.draftAutoPick();
      if (r?.transition?.transition === "draft -> pre_season") {
        toast("Draft complete! Start the next season up top.", "success");
      } else if (r?.pick) {
        toast(`Pick ${r.pick.pick_number}: ${r.pick.player.name}`, "success");
      }
    });
    secondary.textContent = "Sim Draft";
    secondary.title = "Auto-pick the rest of the draft in one shot";
    secondary.onclick = () => simAction(secondary, async () => {
      const r = await api.draftSimRest();
      toast(`Draft complete · ${r?.summary?.picks_made ?? 0} picks made`, "success");
    });
  } else { // pre_season
    primary.classList.add("hidden");
    secondary.classList.add("hidden");
    tertiary.classList.add("hidden");
  }

  // Top-left pulsing action button.
  const phaseBtn = $("#phase-action-btn");
  phaseBtn.onclick = null;
  if (state.phase === "draft") {
    phaseBtn.classList.remove("hidden");
    const remaining = Math.max(0, state.draft_total_picks - state.draft_current_pick);
    phaseBtn.textContent = `Draft (${remaining})`;
    phaseBtn.title = "Open the draft room";
    phaseBtn.onclick = () => { location.hash = "#/draft"; };
  } else if (state.phase === "pre_season") {
    phaseBtn.classList.remove("hidden");
    phaseBtn.textContent = "Start Next Season";
    phaseBtn.title = "Generate next season's schedule and tip off";
    phaseBtn.onclick = () => simAction(phaseBtn, async () => {
      const r = await api.startNextSeason();
      toast(`Season ${r.season} ready · cap now ${fmtNum(r.bst_cap)}`, "success");
      invalidateState();
      teamCache.clear();
      // Always pop back to dashboard so the user sees the fresh schedule.
      if (location.hash !== "#/" && location.hash !== "") {
        location.hash = "#/";
      }
    });
  } else {
    phaseBtn.classList.add("hidden");
  }
}

async function simAction(btn, fn) {
  const original = btn.textContent;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Working…';
  try {
    await fn();
  } catch (err) {
    toast(err.message, "error");
  } finally {
    invalidateState();
    teamCache.clear();
    btn.disabled = false;
    btn.textContent = original;
    router();
  }
}

// Static reset button — visible in every phase.
$("#reset-btn").addEventListener("click", async () => {
  const confirmed = await confirmReset();
  if (!confirmed) return;
  const btn = $("#reset-btn");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Resetting…';
  try {
    const result = await api.resetLeague();
    toast(`League reset · ${result.teams} teams, ${result.players} players, ${result.games_generated} games scheduled`, "success");
    teamCache.clear();
    invalidateState();
    _lastPlayoffInjuryReport = null;
    if (location.hash !== "#/" && location.hash !== "") {
      location.hash = "#/";
    } else {
      router();
    }
  } catch (err) {
    toast(err.message, "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = "Reset";
  }
});

const modeSelect = $("#game-mode-select");
if (modeSelect) {
  modeSelect.addEventListener("change", async (e) => {
    await onGameModeChange(e.target.value);
  });
}

async function confirmReset() {
  return new Promise((resolve) => {
    const overlay = el("div", { class: "modal-overlay" });
    const closing = (val) => () => {
      document.removeEventListener("keydown", escListener);
      overlay.remove();
      resolve(val);
    };
    function escListener(e) { if (e.key === "Escape") closing(false)(); }

    const modal = el("div", { class: "card modal-dialog" },
      el("div", { class: "modal-head" },
        el("div", {},
          el("div", { class: "modal-eyebrow tone-negative" }, "Danger zone"),
          el("h3", { class: "modal-title" }, "Reset the entire league?"),
        ),
      ),
      el("p", { class: "muted", style: "margin: 0.25rem 0 0.5rem;" },
        "This deletes every team, player, schedule, box score, and trade. A brand-new league is seeded from scratch."),
      el("p", { class: "muted", style: "margin: 0; font-size: 0.85rem;" },
        "This cannot be undone."),
      el("div", { class: "modal-actions" },
        el("button", { class: "btn btn-ghost", onClick: closing(false) }, "Cancel"),
        el("button", { class: "btn btn-danger", onClick: closing(true) }, "Yes, reset everything"),
      ),
    );

    overlay.addEventListener("click", (e) => { if (e.target === overlay) closing(false)(); });
    document.addEventListener("keydown", escListener);
    overlay.appendChild(modal);
    document.body.appendChild(overlay);
  });
}

// ----------------------------------------------------------------- utils
function formatDate(iso) {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  const date = new Date(Number(y), Number(m) - 1, Number(d));
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
