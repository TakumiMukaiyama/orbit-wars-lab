"""Phase 1c エージェント: In-flight tracking + Doomed evacuation + State machine."""

import math

from .targeting import (
    AHEAD_THRESHOLD,
    BEHIND_THRESHOLD,
    classify_defense,
    compute_domination,
    enumerate_candidates,
    enumerate_intercept_candidates,
    select_move,
)
from .utils import parse_obs
from .world import build_arrival_ledger, build_timelines


def agent(obs):
    player, planets, fleets, angular_velocity, remaining_turns = parse_obs(obs)

    my_planets = [p for p in planets if p.owner == player]
    if not my_planets:
        return []

    n = len(my_planets)

    # domination mode
    my_total = (
        sum(p.ships for p in my_planets)
        + sum(f.ships for f in fleets if f.owner == player)
    )
    enemy_total = (
        sum(p.ships for p in planets if p.owner not in (player, -1))
        + sum(f.ships for f in fleets if f.owner not in (player, -1))
    )
    dom = compute_domination(my_total, enemy_total)
    if dom < BEHIND_THRESHOLD:
        mode = "behind"
    elif dom > AHEAD_THRESHOLD:
        mode = "ahead"
    else:
        mode = "neutral"

    # 全自惑星の防衛ステータスを事前計算
    defense_status: dict[int, tuple[str, int]] = {
        p.id: classify_defense(p, fleets, player) for p in my_planets
    }

    horizon = max(1, min(80, remaining_turns))
    ledger = build_arrival_ledger(planets, fleets, horizon=horizon)
    timelines = build_timelines(planets, ledger, horizon=horizon)

    # planned[planet_id] = このターンに既に送った ships 合計
    planned: dict[int, int] = {}

    moves = []
    for mine in my_planets:
        status, reserve = defense_status[mine.id]

        if status == "doomed" and n > 1:
            # safe または threatened の自惑星にだけ退避する
            safe_allies = [
                p for p in my_planets
                if p.id != mine.id and defense_status[p.id][0] != "doomed"
            ]
            if safe_allies:
                nearest_ally = min(
                    safe_allies,
                    key=lambda p: (p.x - mine.x) ** 2 + (p.y - mine.y) ** 2,
                )
                evac_angle = math.atan2(nearest_ally.y - mine.y, nearest_ally.x - mine.x)
                if mine.ships > 0:
                    moves.append([mine.id, evac_angle, mine.ships])
            continue

        attack_cands = enumerate_candidates(
            mine,
            planets,
            fleets,
            player,
            angular_velocity=angular_velocity,
            planned=planned,
            mode=mode,
            remaining_turns=remaining_turns,
            timelines=timelines,
        )
        intercept_cands = enumerate_intercept_candidates(
            mine,
            planets,
            fleets,
            player,
            angular_velocity=angular_velocity,
            timelines=timelines,
        )
        all_cands = attack_cands + intercept_cands
        picked = select_move(mine, all_cands, reserve=reserve, my_planet_count=n)
        if picked is None:
            continue
        target_id, angle, ships = picked
        # planned に直接記録 (逆引き不要)
        planned[target_id] = planned.get(target_id, 0) + ships
        moves.append([mine.id, angle, ships])

    return moves
