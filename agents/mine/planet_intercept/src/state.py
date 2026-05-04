"""GameState: ターンごとの状態集約と特徴量ベクトル化。"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .targeting import (
    AHEAD_THRESHOLD,
    BEHIND_THRESHOLD,
    OPENING_TURNS,
    classify_defense,
    compute_domination,
)
from .utils import Fleet, Planet, parse_obs
from .world import Arrival, PlanetState, build_arrival_ledger, build_timelines

NEUTRAL_OWNER = -1


@dataclass
class GameState:
    player: int
    planets: list[Planet]
    fleets: list[Fleet]
    angular_velocity: float
    remaining_turns: int
    step: int
    my_planets: list[Planet]
    mode: str
    domination: float
    timelines: dict[int, list[PlanetState]]
    ledger: dict[int, list[Arrival]]
    defense_status: dict[int, tuple[str, int, int | None]]
    horizon: int
    is_opening: bool


def build_game_state(obs, comet_ids: frozenset[int] | None = None) -> GameState:
    player, planets, fleets, angular_velocity, remaining_turns, parsed_comet_ids, step = (
        parse_obs(obs)
    )
    if comet_ids is None:
        comet_ids = parsed_comet_ids
    if comet_ids:
        planets = [p for p in planets if p.id not in comet_ids]

    my_planets = [p for p in planets if p.owner == player]

    my_total = sum(p.ships for p in my_planets) + sum(
        f.ships for f in fleets if f.owner == player
    )
    enemy_total = sum(p.ships for p in planets if p.owner not in (player, NEUTRAL_OWNER)) + sum(
        f.ships for f in fleets if f.owner not in (player, NEUTRAL_OWNER)
    )
    dom = compute_domination(my_total, enemy_total)
    if dom < BEHIND_THRESHOLD:
        mode = "behind"
    elif dom > AHEAD_THRESHOLD:
        mode = "ahead"
    else:
        mode = "neutral"

    horizon = max(1, min(80, remaining_turns))
    ledger = build_arrival_ledger(planets, fleets, horizon=horizon)
    timelines = build_timelines(planets, ledger, horizon=horizon)

    elapsed_turns = 500 - remaining_turns
    is_opening = elapsed_turns < OPENING_TURNS

    defense_status: dict[int, tuple[str, int, int | None]] = {
        p.id: classify_defense(p, fleets, player, timeline=timelines.get(p.id))
        for p in my_planets
    }
    if is_opening:
        defense_status = {
            pid: (status, reserve // 2, fall_turn)
            for pid, (status, reserve, fall_turn) in defense_status.items()
        }

    return GameState(
        player=player,
        planets=planets,
        fleets=fleets,
        angular_velocity=angular_velocity,
        remaining_turns=remaining_turns,
        step=step,
        my_planets=my_planets,
        mode=mode,
        domination=dom,
        timelines=timelines,
        ledger=ledger,
        defense_status=defense_status,
        horizon=horizon,
        is_opening=is_opening,
    )


def planet_features(
    p: Planet,
    gs: GameState,
    source: Planet | None = None,
) -> np.ndarray:
    """惑星ごとの特徴量ベクトル (17次元)。"""
    if source is not None:
        rel_x = (p.x - source.x) / 100.0
        rel_y = (p.y - source.y) / 100.0
        dist = math.hypot(p.x - source.x, p.y - source.y) / 141.4
    else:
        rel_x, rel_y, dist = 0.0, 0.0, 0.0

    owner_vec = [0.0] * 5
    if p.owner == gs.player:
        owner_vec[0] = 1.0
    elif p.owner == NEUTRAL_OWNER:
        owner_vec[2] = 1.0
    else:
        owner_vec[1] = 1.0

    ships_norm = min(p.ships / 200.0, 1.0)
    prod_norm = p.production / 5.0

    from .utils import CENTER
    r = math.hypot(p.x - CENTER, p.y - CENTER)
    is_orbital = float(gs.angular_velocity != 0.0 and (r + p.radius < 50))

    timeline = gs.timelines.get(p.id, [])
    tl_feats = [0.0] * 3
    for i, eta_check in enumerate([10, 20, 40]):
        idx = min(eta_check - 1, len(timeline) - 1)
        if idx >= 0:
            s = timeline[idx]
            tl_feats[i] = 1.0 if s.owner == gs.player else (-1.0 if s.owner != NEUTRAL_OWNER else 0.0)

    ds = gs.defense_status.get(p.id)
    if ds is None:
        def_vec = [1.0, 0.0, 0.0]
    elif ds[0] == "safe":
        def_vec = [1.0, 0.0, 0.0]
    elif ds[0] == "threatened":
        def_vec = [0.0, 1.0, 0.0]
    else:
        def_vec = [0.0, 0.0, 1.0]

    return np.array(
        [rel_x, rel_y, dist] + owner_vec + [ships_norm, prod_norm, is_orbital] + tl_feats + def_vec,
        dtype=np.float32,
    )


def global_features(gs: GameState) -> np.ndarray:
    """盤面全体の特徴量ベクトル (7次元)。"""
    mode_vec = [
        float(gs.mode == "behind"),
        float(gs.mode == "neutral"),
        float(gs.mode == "ahead"),
    ]
    return np.array(
        [
            gs.domination,
            gs.remaining_turns / 500.0,
            len(gs.my_planets) / 20.0,
            float(gs.is_opening),
        ]
        + mode_vec,
        dtype=np.float32,
    )
