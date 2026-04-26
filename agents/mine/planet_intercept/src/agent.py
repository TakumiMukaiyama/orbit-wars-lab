"""Phase 1b エージェント: 中立 value 修正 + 母星 reserve + 迎撃 + 4P 基盤。

nearest-sniper (baselines/v0_nearest.py) を置き換える新ベースライン。
"""

from .targeting import (
    enumerate_candidates,
    enumerate_intercept_candidates,
    estimate_reserve,
    select_move,
)
from .utils import parse_obs


def agent(obs):
    player, planets, fleets, angular_velocity = parse_obs(obs)

    my_planets = [p for p in planets if p.owner == player]
    if not my_planets:
        return []

    n = len(my_planets)
    moves = []
    for mine in my_planets:
        reserve = estimate_reserve(mine, fleets, player, my_planet_count=n)
        attack_cands = enumerate_candidates(
            mine,
            planets,
            fleets,
            player,
            angular_velocity=angular_velocity,
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
        moves.append([mine.id, angle, ships])

    return moves
