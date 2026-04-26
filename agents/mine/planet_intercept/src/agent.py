"""Phase 1c エージェント: In-flight tracking + Doomed evacuation + State machine."""

import math

from .targeting import (
    classify_defense,
    enumerate_candidates,
    enumerate_intercept_candidates,
    select_move,
)
from .utils import parse_obs


def agent(obs):
    player, planets, fleets, angular_velocity = parse_obs(obs)

    my_planets = [p for p in planets if p.owner == player]
    if not my_planets:
        return []

    n = len(my_planets)

    # 全自惑星の防衛ステータスを事前計算
    defense_status: dict[int, tuple[str, int]] = {
        p.id: classify_defense(p, fleets, player) for p in my_planets
    }

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
        )
        intercept_cands = enumerate_intercept_candidates(
            mine,
            planets,
            fleets,
            player,
            angular_velocity=angular_velocity,
        )
        all_cands = attack_cands + intercept_cands
        picked = select_move(mine, all_cands, reserve=reserve, my_planet_count=n)
        if picked is None:
            continue
        angle, ships = picked
        # 送出した ships を planned に記録
        for target, ships_needed, cand_angle, _ in all_cands:
            if abs(cand_angle - angle) < 1e-9 and ships_needed == ships:
                planned[target.id] = planned.get(target.id, 0) + ships
                break
        moves.append([mine.id, angle, ships])

    return moves
