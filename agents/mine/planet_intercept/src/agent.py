"""planet_intercept エージェント: 領土拡張主軸の意思決定 (9 ルール準拠)。

build_game_state でターンごとの状態を集約し、act でヒューリスティック発射手を決める。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .targeting import (
    CAP_DUMP_MARGIN_TURNS,
    NEUTRAL_OWNER,
    _estimate_max_capacity,
    classify_defense,
    enumerate_candidates,
    enumerate_intercept_candidates,
    enumerate_post_launch_snipe_candidates,
    enumerate_rear_push_candidates,
    enumerate_reinforce_candidates,
    enumerate_support_candidates,
    enumerate_swarm_candidates,
    select_move,
)
from .utils import Fleet, Planet, parse_obs
from .world import (
    Arrival,
    PlanetState,
    apply_planned_arrival,
    build_arrival_ledger,
    build_timelines,
)

# Phase 判定: 中立惑星比率で early/mid/late を切り替える。
# 戦略は「拡張競争で先んじて生産量を引き上げる」ため、neutral が
# 半分以上残っているうちは expand 優先 (early)。
EARLY_NEUTRAL_RATIO = 0.5


@dataclass
class GameState:
    player: int
    planets: list[Planet]
    fleets: list[Fleet]
    angular_velocity: float
    remaining_turns: int
    step: int
    my_planets: list[Planet]
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

    horizon = max(1, min(80, remaining_turns))
    ledger = build_arrival_ledger(planets, fleets, horizon=horizon)
    timelines = build_timelines(planets, ledger, horizon=horizon)

    neutral_count = sum(1 for p in planets if p.owner == NEUTRAL_OWNER)
    neutral_ratio = neutral_count / max(1, len(planets))
    is_opening = neutral_ratio >= EARLY_NEUTRAL_RATIO

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
        timelines=timelines,
        ledger=ledger,
        defense_status=defense_status,
        horizon=horizon,
        is_opening=is_opening,
    )


def _pick_dump_target(
    mine: Planet,
    all_planets: list,
    attack_cands: list,
    player: int,
) -> tuple[float, int] | None:
    """容量ダンプ先を選ぶ。(angle, ships) を返す。なければ None。"""
    positive_cands = [c for c in attack_cands if c[3] > 0]
    if positive_cands:
        best = max(positive_cands, key=lambda c: c[3])
        angle = best[2]
        return angle, best[1]

    enemy_planets = [p for p in all_planets if p.owner not in (player, NEUTRAL_OWNER)]
    my_allies = [p for p in all_planets if p.owner == player and p.id != mine.id]
    if enemy_planets and my_allies:
        def frontier_score(p):
            return min(math.hypot(p.x - e.x, p.y - e.y) for e in enemy_planets)
        frontier = min(my_allies, key=frontier_score)
        angle = math.atan2(frontier.y - mine.y, frontier.x - mine.x)
        return angle, mine.ships

    if enemy_planets:
        nearest = min(enemy_planets, key=lambda p: math.hypot(p.x - mine.x, p.y - mine.y))
        angle = math.atan2(nearest.y - mine.y, nearest.x - mine.x)
        return angle, mine.ships
    return None


def act(gs: GameState) -> list[list[int | float]]:
    """1 ターンの発射手 [[planet_id, angle, ships], ...] を返す。"""
    if not gs.my_planets:
        return []

    n = len(gs.my_planets)
    planned: dict[int, int] = {}
    intercepted_ids: set[int] = set()
    fired_sources: set[int] = set()
    concurrent_etas: set[int] = set()

    # 事前パス: 全自惑星の attack 候補を収集 (容量ダンプと reinforce パスで使用)
    attack_cands_by_planet: dict[int, list] = {}
    for mine in gs.my_planets:
        attack_cands_by_planet[mine.id] = enumerate_candidates(
            mine,
            gs.planets,
            gs.fleets,
            gs.player,
            angular_velocity=gs.angular_velocity,
            planned=planned,
            remaining_turns=gs.remaining_turns,
            timelines=gs.timelines,
            is_opening=gs.is_opening,
        )

    moves: list[list[int | float]] = []
    for mine in gs.my_planets:
        _, reserve, fall_turn = gs.defense_status[mine.id]

        # 容量ダンプ: 生産停止を防ぐため上限手前で強制射出
        max_cap = _estimate_max_capacity(mine)
        if max_cap > 0 and mine.ships >= max_cap - mine.production * CAP_DUMP_MARGIN_TURNS:
            attack_cands = attack_cands_by_planet.get(mine.id, [])
            dump_result = _pick_dump_target(mine, gs.planets, attack_cands, gs.player)
            if dump_result is not None:
                dump_angle, _ = dump_result
                dump_ships = max(1, mine.ships - reserve)
                moves.append([mine.id, dump_angle, dump_ships])
                fired_sources.add(mine.id)
                continue

        attack_cands = enumerate_candidates(
            mine,
            gs.planets,
            gs.fleets,
            gs.player,
            angular_velocity=gs.angular_velocity,
            planned=planned,
            remaining_turns=gs.remaining_turns,
            timelines=gs.timelines,
            is_opening=gs.is_opening,
            concurrent_etas=concurrent_etas,
        )
        intercept_cands = enumerate_intercept_candidates(
            mine,
            gs.planets,
            gs.fleets,
            gs.player,
            angular_velocity=gs.angular_velocity,
            timelines=gs.timelines,
        )
        intercept_cands = [c for c in intercept_cands if c[0].id not in intercepted_ids]
        support_cands = enumerate_support_candidates(
            mine,
            gs.planets,
            gs.player,
            timelines=gs.timelines,
            planned=planned,
            remaining_turns=gs.remaining_turns,
            current_turn=gs.step,
        )
        support_cands = [c for c in support_cands if c[0].id not in intercepted_ids]
        snipe_cands = enumerate_post_launch_snipe_candidates(
            mine,
            gs.planets,
            gs.fleets,
            gs.player,
            angular_velocity=gs.angular_velocity,
            planned=planned,
            remaining_turns=gs.remaining_turns,
            timelines=gs.timelines,
        )

        all_cands = attack_cands + intercept_cands + support_cands + snipe_cands
        picked = select_move(
            mine, all_cands, reserve=reserve, my_planet_count=n, fall_turn=fall_turn
        )
        if picked is None:
            continue

        target_id, angle, ships, my_eta = picked

        planned[target_id] = planned.get(target_id, 0) + ships
        arrival_eta = max(1, int(math.ceil(my_eta)))
        apply_planned_arrival(
            gs.ledger,
            gs.timelines,
            gs.planets,
            target_id=target_id,
            owner=gs.player,
            ships=ships,
            eta=arrival_eta,
            horizon=gs.horizon,
        )
        if target_id in gs.defense_status:
            intercepted_ids.add(target_id)
            target_planet = next(
                (p for p in gs.my_planets if p.id == target_id), None
            )
            if target_planet is not None:
                gs.defense_status[target_id] = classify_defense(
                    target_planet,
                    gs.fleets,
                    gs.player,
                    timeline=gs.timelines.get(target_id),
                )
        fired_sources.add(mine.id)
        concurrent_etas.add(int(math.ceil(my_eta)))

        moves.append([mine.id, angle, ships])

    # swarm パス: 単独で届かないターゲットへの 2-3 惑星協調攻撃
    swarm_missions = enumerate_swarm_candidates(
        my_planets=gs.my_planets,
        all_planets=gs.planets,
        fleets=gs.fleets,
        player=gs.player,
        angular_velocity=gs.angular_velocity,
        planned=planned,
        fired_sources=fired_sources,
        defense_status=gs.defense_status,
        remaining_turns=gs.remaining_turns,
        timelines=gs.timelines,
    )
    swarm_fired_sources: set[int] = set()
    for sm in sorted(swarm_missions, key=lambda m: -m.value):
        if sm.src_a.id in fired_sources or sm.src_a.id in swarm_fired_sources:
            continue
        if sm.src_b.id in fired_sources or sm.src_b.id in swarm_fired_sources:
            continue
        if sm.src_c is not None and (
            sm.src_c.id in fired_sources or sm.src_c.id in swarm_fired_sources
        ):
            continue
        moves.append([sm.src_a.id, sm.angle_a, sm.ships_a])
        moves.append([sm.src_b.id, sm.angle_b, sm.ships_b])
        if sm.src_c is not None and sm.ships_c > 0:
            moves.append([sm.src_c.id, sm.angle_c, sm.ships_c])
        eta_int = max(1, int(math.ceil(max(sm.eta_a, sm.eta_b, sm.eta_c if sm.src_c else 0))))
        total_ships = sm.ships_a + sm.ships_b + (sm.ships_c if sm.src_c else 0)
        apply_planned_arrival(
            gs.ledger,
            gs.timelines,
            gs.planets,
            target_id=sm.target.id,
            owner=gs.player,
            ships=total_ships,
            eta=eta_int,
            horizon=gs.horizon,
        )
        planned[sm.target.id] = planned.get(sm.target.id, 0) + total_ships
        swarm_fired_sources.add(sm.src_a.id)
        swarm_fired_sources.add(sm.src_b.id)
        if sm.src_c is not None:
            swarm_fired_sources.add(sm.src_c.id)

    # reinforce + rear_push パス: 後方から前線への補給
    reinforce_missions = enumerate_reinforce_candidates(
        my_planets=gs.my_planets,
        target_candidates_by_planet=attack_cands_by_planet,
        timelines=gs.timelines,
        reserve_of=lambda p: gs.defense_status[p.id][1],
    )
    rear_push_missions = list(
        enumerate_rear_push_candidates(
            my_planets=gs.my_planets,
            all_planets=gs.planets,
            player=gs.player,
            attack_cands_by_planet=attack_cands_by_planet,
            reserve_of=lambda p: gs.defense_status[p.id][1],
        )
    )
    reinforce_missions = sorted(
        reinforce_missions + rear_push_missions, key=lambda m: -m.value
    )
    all_fired = fired_sources | swarm_fired_sources
    reinforce_fired_sources: set[int] = set()
    for r in reinforce_missions:
        if r.source_id in all_fired or r.source_id in reinforce_fired_sources:
            continue
        moves.append([r.source_id, r.angle, r.ships])
        apply_planned_arrival(
            gs.ledger,
            gs.timelines,
            gs.planets,
            target_id=r.target_id,
            owner=gs.player,
            ships=r.ships,
            eta=r.my_eta,
            horizon=gs.horizon,
        )
        reinforce_fired_sources.add(r.source_id)

    return moves


def agent(obs):
    gs = build_game_state(obs)
    return act(gs)
