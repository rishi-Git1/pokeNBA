# Pokémon NBA GM Simulator

A web-based front-office and basketball simulation game where you manage a team of Pokémon. Their **Base Stat Total (BST)** is their salary, their primary ability is mapped to a basketball **Badge**, and their 6 base stats drive an entirely RNG/math-based simulation engine.

## Stack
- **Backend:** Python 3.11+ / FastAPI
- **Frontend:** Vanilla JS / HTML / CSS (no frameworks, ES modules)
- **DB:** SQLite via SQLAlchemy 2.x
- **Sprites:** Live from the [PokeAPI sprite CDN](https://github.com/PokeAPI/sprites) — no local image storage
- **Badge System:** Localized JSON (`data/abilities_db.json`) mapping ~300 abilities to ~13 basketball badges

## Core Mechanics
| Pokémon Stat | Basketball Role |
|---|---|
| **HP** | Stamina pool (minutes endurance) |
| **Attack** | Inside scoring efficiency |
| **Sp. Attack** | Outside scoring efficiency |
| **Defense** | Interior defense (rebounds/blocks) |
| **Sp. Defense** | Perimeter defense (steals/contests) |
| **Speed** | Pace, fast breaks, transition D |
| **BST (sum)** | **Salary** — counts against the team cap |

- **BST cap:** 7,500 per team (15-man roster). Inflates by **5–12%** every off-season.
- **Aging:** Speed and HP decay first after age 28; other stats follow more gently.
- **Regens:** When a vet retires, a same-species rookie is generated with ±10% stat variance and lands in the free-agent pool / draft.
- **Badges:** Abilities map to flat math modifiers applied during possession RNG resolution.
- **Rookie deals:** A drafted rookie counts for **half BST** against the cap during their first 3 seasons.

## Project Structure
```
pokeNBA/
├── backend/
│   ├── main.py                   # FastAPI app + static frontend mount
│   ├── database.py               # SQLAlchemy session/engine
│   ├── seed.py                   # DB seeding script
│   ├── core/
│   │   ├── config.py             # Pydantic settings (cap, roster size, paths)
│   │   ├── badges.py             # Ability → badge → modifier lookup
│   │   ├── positions.py          # Stat-line → PG/SG/SF/PF/C heuristic
│   │   ├── sprites.py            # PokeAPI sprite URL helpers
│   │   └── player_factory.py     # Shared rookie/regen builder
│   ├── models/                   # SQLAlchemy ORM (Team, Player, Game, BoxScore, DraftPick)
│   ├── schemas/                  # Pydantic API responses
│   ├── routers/                  # FastAPI routes (teams, players, league, sim, transactions)
│   ├── league/
│   │   ├── aging.py              # End-of-season state machine
│   │   ├── lifecycle.py          # Phase transitions (regular ↔ playoffs ↔ draft ↔ pre-season)
│   │   ├── playoffs.py           # Best-of-7 bracket, sim 1 game / 1 round, advancement
│   │   ├── draft.py              # Worst→best order, rookie deals, manual + auto picks
│   │   ├── projections.py        # Team-rating + projected-wins (used by release modal)
│   │   ├── state.py              # LeagueState singleton accessor
│   │   └── transactions.py       # Trade engine + free-agent moves
│   └── sim/
│       ├── tuning.py             # Every magic number
│       ├── state.py              # Slim in-memory dataclasses (decoupled from ORM)
│       ├── modifiers.py          # Aggregates badge effects per possession
│       ├── possession.py         # Micro engine: 5v5 possession resolver
│       ├── rotation.py           # Mid engine: substitution on dead balls
│       ├── game.py               # Game runner (orchestrates a single game + OT)
│       ├── schedule.py           # Balanced 82-game schedule generator
│       ├── league_day.py         # Macro engine: simulate a day across the league
│       ├── parallel.py           # Optional ProcessPoolExecutor wrapper
│       └── cli.py                # python -m backend.sim.cli ...
├── frontend/                     # Vanilla-JS SPA, served by FastAPI at /
│   ├── index.html
│   ├── styles.css
│   ├── api.js                    # tiny fetch wrapper
│   └── app.js                    # router + all views
├── data/
│   ├── pokemon_minidex.json
│   └── abilities_db.json
└── requirements.txt
```

## Quickstart

```bash
python -m venv .venv
.venv\Scripts\activate            # (Windows PowerShell)
pip install -r requirements.txt

# 1. Seed the league (30 teams, full draft pool, 1230-game schedule)
python -m backend.seed

# 2. Run the server (FastAPI + bundled vanilla JS frontend)
uvicorn backend.main:app --reload
# UI:   http://127.0.0.1:8000/
# API:  http://127.0.0.1:8000/docs
```

## Deploy on Render

Render was defaulting to **Python 3.14**, which has no pre-built wheels for `pydantic-core` yet — the build tries to compile Rust and fails. This repo pins **Python 3.12.8** via `.python-version` (Render does **not** read `runtime.txt`).

**Dashboard settings:**

| Setting | Value |
|---|---|
| **Build Command** | `pip install --upgrade pip && pip install -r requirements.txt` |
| **Start Command** | `uvicorn backend.main:app --host 0.0.0.0 --port $PORT` |
| **Environment** | `PYTHON_VERSION=3.12.8` (recommended even with `.python-version`) |

Or connect the repo and use the included `render.yaml` blueprint.

**Notes:**
- The start command must be `backend.main:app` (not `app.main:app`).
- On first boot the app auto-seeds if the database is empty.
- SQLite on Render is **ephemeral** unless you add a [persistent disk](https://render.com/docs/disks) and set `POKENBA_DATABASE_URL=sqlite:////var/data/pokenba.db`.

Or sim from the CLI without bringing up the UI:

```bash
python -m backend.sim.cli day                       # next game day
python -m backend.sim.cli days --count 14           # next 14 days
python -m backend.sim.cli season                    # rest of the season (~45s sequential)
python -m backend.sim.cli season --parallel         # ~30s on an 8-core box
python -m backend.sim.cli game --id 5 --pbp         # replay one game with play-by-play
```

## Simulation Engine

Three nested layers, all decoupled from SQLAlchemy:

| Layer | File | Responsibility |
|---|---|---|
| **Micro** | `backend/sim/possession.py` | Resolves a single 5v5 possession (USG%, shot type, FG% with badges, stamina drain) |
| **Mid**   | `backend/sim/rotation.py`   | Substitution engine on dead balls (stamina + foul thresholds + position-aware bench) |
| **Macro** | `backend/sim/league_day.py` | Loads daily rosters into RAM, runs games, batch-flushes box scores via `executemany` |

Overtime is handled inside `game.py`: 5-minute OT periods loop until the score is decided (capped at 4 OTs as a safety stop). Calibrated for ~95–110 PPG and ~46% FG.

`--parallel` farms game work across CPU cores using a single persistent `ProcessPoolExecutor`. On Windows the per-pool `spawn` startup is ~5 seconds, so the parallel path only wins for full-season runs (~30% faster). Short batches stay sequential.

## League Cycle

The whole league is driven by a phase machine (`backend/league/lifecycle.py`). Each phase exposes its own sim controls and the front-end swaps the topbar buttons / pulsing top-left action button accordingly:

```
REGULAR_SEASON  ──► PLAYOFFS  ──► DRAFT  ──► PRE_SEASON  ──► REGULAR_SEASON (next year)
   sim 1 day        sim 1 game     auto-pick    "Start Next
   sim week         sim 1 round    sim draft    Season" button
```

1. **Regular season** — 82-game schedule. When the last regular-season game is played, the league auto-transitions to **playoffs**.
2. **Playoffs** — 1-8 East/West seeding, no play-in, **best-of-7** every round. Home court goes to the higher seed (games 1, 2, 5, 7).
3. **Off-season pipeline (auto)** — the moment the Finals end, the engine ages all players, retires vets, generates same-species **regens**, mints next-year draft picks, and **inflates the cap by a random 5–12%**.
4. **Draft** — worst record → best, ties decided by coin flip. **First round only** (30 picks). Pulsing **Draft** button appears in the top-left. Each pick lands a rookie on a **half-BST rookie deal** for 3 seasons.
5. **Pre-season** — pulsing **Start Next Season** button appears. Click it to generate a fresh schedule and tip off year N+1.

## API

**League / rosters**
- `GET  /api/teams` — list all 30 teams
- `GET  /api/teams/{id}` — full detail (roster, BST used, cap room)
- `GET  /api/players` — paginated player list (filters: badge, team_id, free_agents_only)
- `GET  /api/players/{id}` — single player (includes `sprite_url` + `artwork_url`)
- `GET  /api/league/standings` — current standings
- `GET  /api/league/free-agents` — unsigned players
- `GET  /api/league/leaders?stat=points` — season leaders (points/rebounds/assists/etc.)
- `GET  /api/league/badges` — badge catalog with effect modifiers

**Simulation**
- `POST /api/sim/schedule?season=1` — (re)generate the schedule
- `POST /api/sim/day?season=1` — advance one game day
- `POST /api/sim/season?season=1` — sim the rest of the season
- `GET  /api/sim/schedule?season=1&completed=false` — schedule view
- `GET  /api/sim/recent-results?limit=10` — most recent finals
- `GET  /api/sim/upcoming-games?limit=10` — next slate
- `GET  /api/sim/games/{id}/box` — full box score for any played game

**Transactions**
- `POST /api/transactions/trade` — atomic swap of players + picks (validates cap)
- `POST /api/transactions/sign?team_id=&player_id=` — sign a free agent
- `POST /api/transactions/release?team_id=&player_id=` — cut a player

**League management**
- `GET  /api/league/state` — phase, current season, dynamic cap, last champion, draft progress
- `GET  /api/league/cap-config` — cap, leeway, hard ceiling, roster bounds (frontend uses this for meters)
- `POST /api/league/reset` — wipe and re-seed everything (used by the topbar Reset button)
- `POST /api/league/start-next-season` — only valid in `pre_season`; generates schedule and increments season
- `POST /api/league/end-season?season=1` — age, retire, generate regens, mint next-year picks (manual)
- `POST /api/league/advance-season?season=1` — reset records and generate next season's schedule (manual)

**Playoffs**
- `GET  /api/playoffs/bracket` — full bracket dump (all rounds, all series)
- `POST /api/playoffs/game` — sim the next undecided game in the active series
- `POST /api/playoffs/round` — sim the current round to completion

**Draft**
- `GET  /api/draft/state` — on-the-clock team, available rookies, full pick log
- `POST /api/draft/pick` — `{"player_id": int}` body; manual pick by current team
- `POST /api/draft/auto-pick` — best-available pick for current team
- `POST /api/draft/sim-rest` — auto-pick everyone remaining

## Frontend

Single-page vanilla JS app served from `/` (no build step, no frameworks). Hash-based routing:

| Route | View |
|---|---|
| `#/` | Dashboard — standings + scoring leaders + recent/upcoming games |
| `#/standings` | Full conference standings |
| `#/teams/{id}` | Team detail with cap meter and roster grid (sprites!) |
| `#/players/{id}` | Player detail — full-size artwork + stat bars + badge |
| `#/schedule` | Filterable schedule by date |
| `#/leaders` | League leaders by stat (points/rebounds/assists/steals/blocks/3PM/FGM/MIN) |
| `#/free-agents` | Browse + sign FA pool |
| `#/playoffs` | Full bracket — auto-shown when playoffs are live or just finished |
| `#/draft` | Draft room — on-the-clock team, available rookies, pick log |
| `#/games/{id}` | Final score + per-team box scores |
| `#/badges` | Badge catalog with trigger contexts and modifier values |

The top-bar sim buttons swap based on phase:

- **Regular season:** `Sim 1 Day` / `Sim Week`
- **Playoffs:** `Sim 1 Game` / `Sim 1 Round`
- **Draft:** `Auto-pick` / `Sim Draft` (plus picking from the board)
- **Pre-season:** sim buttons hide; the pulsing **Start Next Season** action takes over the top-left.

## Calibration knobs

- `POKENBA_BST_CAP=8000` — env override for the **starting** cap (default 7,500). The cap inflates from there year over year.
- `backend/sim/tuning.py` — pace, FG%, stamina drain, foul rate, OT length.
- `backend/core/positions.py` — position-derivation weights.
- `backend/core/config.py` — roster size, season length, rookie age range, regen variance.
- `backend/league/aging.py` — peak age and decay rate constants.
- `backend/league/lifecycle.py` — `CAP_INFLATION_MIN` / `CAP_INFLATION_MAX` (5–12% off-season bump).
- `backend/league/playoffs.py` — `GAMES_TO_WIN_SERIES` (best-of-7 → 4).
- `backend/league/draft.py` — `ROOKIE_DEAL_SEASONS` (default 3).
- `backend/league/transactions.py` — `TRADE_CAP_LEEWAY` (how far over cap a trade can push a team) and roster size bounds.
