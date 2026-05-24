"""All simulation magic numbers live here. Tweak freely; nothing else has to change.

These constants are calibrated against league averages so a 100-possession game
produces ~110 PPG, ~46% FG, ~36% 3P, ~14% TOV — within a few points of the
real NBA. The engine itself never hard-codes any of these; everything reads
from this module.
"""
from __future__ import annotations

# --- Pace ---
# Possession length (seconds) is a linear function of the offense's average
# Speed stat. Calibrated so an avg-speed 85 lineup runs ~14.5s possessions
# (= ~100 possessions per team per game = NBA average).
POSSESSION_BASE_SECONDS: float = 17.0  # at avg speed = 60
POSSESSION_SECONDS_PER_SPEED_PT: float = -0.05  # +1 speed → -0.05s
POSSESSION_MIN_SECONDS: float = 6.0
POSSESSION_MAX_SECONDS: float = 24.0  # NBA shot clock

# --- Shot selection ---
# Probability the on-ball offensive player attempts an *outside* (3PT) shot.
# Anchored at 0.40, biased by Sp.Attack vs Attack ratio.
OUTSIDE_SHOT_BASE: float = 0.40
OUTSIDE_SHOT_RATIO_WEIGHT: float = 0.30  # how much the sp_atk/atk ratio shifts it
OUTSIDE_SHOT_FLOOR: float = 0.10
OUTSIDE_SHOT_CEIL: float = 0.80

# --- Shot resolution ---
# Each made shot starts at the base FG% and is shifted by (shooter - defender)
# rating differential, then by badge effects.
INSIDE_FG_BASE: float = 0.52
OUTSIDE_FG_BASE: float = 0.36
RATING_DIFF_WEIGHT: float = 0.0018  # 1 rating pt = ±0.18% FG%
RATING_BASELINE: int = 80           # treat 80 as average for stat-vs-stat math
FG_PCT_FLOOR: float = 0.05
FG_PCT_CEIL: float = 0.85

# --- Turnovers / fouls ---
TURNOVER_BASE_PROB: float = 0.13          # before badges
SHOOTING_FOUL_PROB: float = 0.07          # chance a shot draws a foul
NON_SHOOTING_FOUL_PROB: float = 0.04      # off-ball foul, sends to FT bonus eventually
AND_ONE_PROB: float = 0.04                # made shot + foul
FT_PCT_BASE: float = 0.78                 # generic free-throw rate

# --- Rebounding ---
DEF_REB_BASE: float = 0.74
INTERIOR_D_RATING_WEIGHT: float = 0.0008  # +1 def rating tilts rebound prob

# --- Assists ---
ASSIST_PROB_BASE: float = 0.55  # of made FGs
ASSIST_FLOOR_GENERAL_BONUS: float = 0.08  # additive when "Floor General" on floor

# --- Stamina ---
# Each on-court possession drains this much stamina from a player. Snorlax-tier
# HP (~160) handles ~160 possessions; light Pokémon (~50) tap out fast.
STAMINA_DRAIN_PER_POSSESSION: float = 1.0
STAMINA_REST_PER_POSSESSION: float = 1.8
STAMINA_FATIGUE_THRESHOLD: float = 0.50   # below this → performance penalty
STAMINA_FATIGUE_PENALTY: float = 0.06     # flat FG% reduction when fatigued
STAMINA_SUB_THRESHOLD: float = 0.40       # below this → flagged for sub
STAMINA_FORCE_SUB_THRESHOLD: float = 0.20 # below this → forced sub

# --- Fouls ---
FOULS_TO_FOUL_OUT: int = 6                # 6 personal fouls = ejection (NBA)

# --- Overtime ---
OVERTIME_LENGTH_SECONDS: int = 300        # 5-minute OT periods
MAX_OVERTIME_PERIODS: int = 4             # safety stop: never run more than 4 OTs

# --- Free throws on 3PT shooting fouls ---
THREE_PT_VALUE: int = 3
TWO_PT_VALUE: int = 2
