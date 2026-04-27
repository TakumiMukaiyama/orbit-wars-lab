"""Phase 1c エージェント: In-flight tracking + Doomed evacuation + State machine."""

import math

from .targeting import (
    AHEAD_THRESHOLD,
    BEHIND_THRESHOLD,
    classify_defense,
    compute_domination,
    enumerate_candidates,
    enumerate_intercept_candidates,
    enumerate_swarm_candidates,
    select_move,
)
from .utils import parse_obs
from .world import apply_planned_arrival, build_arrival_ledger, build_timelines


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

    horizon = max(1, min(80, remaining_turns))
    ledger = build_arrival_ledger(planets, fleets, horizon=horizon)
    timelines = build_timelines(planets, ledger, horizon=horizon)

    # 全自惑星の防衛ステータスを timeline 付きで事前計算
    defense_status: dict[int, tuple[str, int]] = {
        p.id: classify_defense(p, fleets, player, timeline=timelines.get(p.id))
        for p in my_planets
    }

    # planned[planet_id] = このターンに既に送った ships 合計
    planned: dict[int, int] = {}
    # 同一 defended planet への迎撃は 1 turn 1 本まで (細切れ迎撃で攻撃手を潰さないため)
    intercepted_ids: set[int] = set()
    # シングルソースループで発射済みの自惑星 (スウォームパスで再利用しない)
    fired_sources: set[int] = set()

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
        intercept_cands = [c for c in intercept_cands if c[0].id not in intercepted_ids]
        all_cands = attack_cands + intercept_cands
        picked = select_move(mine, all_cands, reserve=reserve, my_planet_count=n)
        if picked is None:
            continue
        target_id, angle, ships, my_eta = picked
        # planned に直接記録 (逆引き不要)
        planned[target_id] = planned.get(target_id, 0) + ships
        # 採用した手を ledger/timelines に反映 (後続惑星が最新状態で判断できる)
        arrival_eta = max(1, int(math.ceil(my_eta)))
        apply_planned_arrival(
            ledger, timelines, planets,
            target_id=target_id, owner=player, ships=ships,
            eta=arrival_eta, horizon=horizon,
        )
        # 反映によって自惑星の timeline が変わった場合は defense_status を再計算
        if target_id in defense_status:
            intercepted_ids.add(target_id)
            target_planet = next((p for p in my_planets if p.id == target_id), None)
            if target_planet is not None:
                defense_status[target_id] = classify_defense(
                    target_planet, fleets, player,
                    timeline=timelines.get(target_id),
                )
        moves.append([mine.id, angle, ships])
        fired_sources.add(mine.id)

    # Swarm pass: 未発射ソースペアで単独不可ターゲットを協調攻略
    swarm_missions = enumerate_swarm_candidates(
        my_planets,
        planets,
        fleets,
        player,
        angular_velocity=angular_velocity,
        planned=planned,
        fired_sources=fired_sources,
        defense_status=defense_status,
        mode=mode,
        remaining_turns=remaining_turns,
        timelines=timelines,
    )
    swarm_missions.sort(key=lambda m: -m.value)
    for mission in swarm_missions:
        if mission.src_a.id in fired_sources or mission.src_b.id in fired_sources:
            continue
        if mission.target.id in planned:
            continue
        eta_a = max(1, int(math.ceil(mission.eta_a)))
        eta_b = max(1, int(math.ceil(mission.eta_b)))
        apply_planned_arrival(
            ledger, timelines, planets,
            target_id=mission.target.id, owner=player,
            ships=mission.ships_a, eta=eta_a, horizon=horizon,
        )
        apply_planned_arrival(
            ledger, timelines, planets,
            target_id=mission.target.id, owner=player,
            ships=mission.ships_b, eta=eta_b, horizon=horizon,
        )
        planned[mission.target.id] = mission.ships_a + mission.ships_b
        moves.append([mission.src_a.id, mission.angle_a, mission.ships_a])
        moves.append([mission.src_b.id, mission.angle_b, mission.ships_b])
        fired_sources.add(mission.src_a.id)
        fired_sources.add(mission.src_b.id)

    return moves
