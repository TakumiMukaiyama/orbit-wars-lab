"""Phase 1c エージェント: In-flight tracking + Doomed evacuation + State machine."""

import math

from .cand_log import is_enabled as _cand_log_enabled
from .cand_log import log_turn as _cand_log
from .targeting import (
    AHEAD_THRESHOLD,
    BEHIND_THRESHOLD,
    MAX_EXPAND_PER_TURN,
    NEUTRAL_OWNER,
    OPENING_TURNS,
    classify_defense,
    compute_domination,
    enumerate_candidates,
    enumerate_intercept_candidates,
    enumerate_reinforce_candidates,
    enumerate_snipe_candidates,
    enumerate_support_candidates,
    select_move,
)
from .utils import parse_obs
from .world import apply_planned_arrival, build_arrival_ledger, build_timelines


def agent(obs):
    (
        player,
        planets,
        fleets,
        angular_velocity,
        remaining_turns,
        comet_ids,
        step,
    ) = parse_obs(obs)

    # 彗星は楕円軌道 + 消滅 + 生産 1 ship/turn で、本エージェントの円軌道前提
    # (intercept_pos) と value モデルに合わないため、候補生成前に除外する。
    if comet_ids:
        planets = [p for p in planets if p.id not in comet_ids]

    my_planets = [p for p in planets if p.owner == player]
    if not my_planets:
        return []

    n = len(my_planets)

    # domination mode
    my_total = sum(p.ships for p in my_planets) + sum(f.ships for f in fleets if f.owner == player)
    enemy_total = sum(p.ships for p in planets if p.owner not in (player, -1)) + sum(
        f.ships for f in fleets if f.owner not in (player, -1)
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

    # P7: opening phase フラグ (elapsed_turns < OPENING_TURNS)
    elapsed_turns = 500 - remaining_turns
    is_opening = elapsed_turns < OPENING_TURNS

    # 全自惑星の防衛ステータスを timeline 付きで事前計算
    defense_status: dict[int, tuple[str, int]] = {
        p.id: classify_defense(p, fleets, player, timeline=timelines.get(p.id)) for p in my_planets
    }

    # P7: opening phase では defense reserve を 50% に絞り expand を優先する
    if is_opening:
        defense_status = {
            pid: (status, reserve // 2) for pid, (status, reserve) in defense_status.items()
        }

    # planned[planet_id] = このターンに既に送った ships 合計
    planned: dict[int, int] = {}
    # 同一 defended planet への迎撃は 1 turn 1 本まで (細切れ迎撃で攻撃手を潰さないため)
    intercepted_ids: set[int] = set()
    # P7: opening phase での expand 発射数カウント
    expand_fired_this_turn: int = 0
    # reinforce パス用: 通常パスで発射した source と、各惑星の attack 候補
    fired_sources: set[int] = set()
    attack_cands_by_planet: dict[int, list] = {}

    moves = []
    for mine in my_planets:
        status, reserve = defense_status[mine.id]

        if status == "doomed" and n > 1:
            # safe または threatened の自惑星にだけ退避する
            safe_allies = [
                p for p in my_planets if p.id != mine.id and defense_status[p.id][0] != "doomed"
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
            my_planet_count=n,
            domination=dom,
            is_opening=is_opening,
        )
        attack_cands_by_planet[mine.id] = attack_cands
        intercept_cands = enumerate_intercept_candidates(
            mine,
            planets,
            fleets,
            player,
            angular_velocity=angular_velocity,
            timelines=timelines,
        )
        intercept_cands = [c for c in intercept_cands if c[0].id not in intercepted_ids]
        support_cands = enumerate_support_candidates(
            mine,
            planets,
            player,
            timelines=timelines,
            planned=planned,
            remaining_turns=remaining_turns,
        )
        support_cands = [c for c in support_cands if c[0].id not in intercepted_ids]
        if mode == "behind":
            snipe_cands = enumerate_snipe_candidates(
                mine,
                planets,
                fleets,
                player,
                angular_velocity=angular_velocity,
                planned=planned,
                remaining_turns=remaining_turns,
                timelines=timelines,
                ledger=ledger,
                horizon=horizon,
            )
        else:
            snipe_cands = []
        all_cands = attack_cands + intercept_cands + support_cands + snipe_cands
        picked = select_move(mine, all_cands, reserve=reserve, my_planet_count=n)
        if _cand_log_enabled():
            _cand_log(
                step=step,
                player=player,
                mine=mine,
                mode=mode,
                reserve=reserve,
                attack=attack_cands,
                intercept=intercept_cands,
                snipe=snipe_cands,
                picked_target=(picked[0] if picked is not None else None),
                fleets=fleets,
                planets=planets,
                angular_velocity=angular_velocity,
            )
        if picked is None:
            continue
        target_id, angle, ships, my_eta = picked

        # P7: opening expand 上限チェック (中立惑星への攻撃を max_expand_per_turn で制限)
        target_planet_obj = next((p for p in planets if p.id == target_id), None)
        if (
            is_opening
            and target_planet_obj is not None
            and target_planet_obj.owner == NEUTRAL_OWNER
        ):
            if expand_fired_this_turn >= MAX_EXPAND_PER_TURN:
                continue
            expand_fired_this_turn += 1

        # planned に直接記録 (逆引き不要)
        planned[target_id] = planned.get(target_id, 0) + ships
        # 採用した手を ledger/timelines に反映 (後続惑星が最新状態で判断できる)
        arrival_eta = max(1, int(math.ceil(my_eta)))
        apply_planned_arrival(
            ledger,
            timelines,
            planets,
            target_id=target_id,
            owner=player,
            ships=ships,
            eta=arrival_eta,
            horizon=horizon,
        )
        # 反映によって自惑星の timeline が変わった場合は defense_status を再計算
        if target_id in defense_status:
            intercepted_ids.add(target_id)
            target_planet = next((p for p in my_planets if p.id == target_id), None)
            if target_planet is not None:
                defense_status[target_id] = classify_defense(
                    target_planet,
                    fleets,
                    player,
                    timeline=timelines.get(target_id),
                )
        fired_sources.add(mine.id)
        moves.append([mine.id, angle, ships])

    # reinforce 独立パス (M1): 通常パス後に実行
    reinforce_missions = enumerate_reinforce_candidates(
        my_planets=my_planets,
        target_candidates_by_planet=attack_cands_by_planet,
        timelines=timelines,
        reserve_of=lambda p: defense_status[p.id][1],
    )
    reinforce_fired_sources: set[int] = set()
    for r in sorted(reinforce_missions, key=lambda m: -m.value):
        if r.source_id in fired_sources:
            continue
        if r.source_id in reinforce_fired_sources:
            continue
        moves.append([r.source_id, r.angle, r.ships])
        apply_planned_arrival(
            ledger,
            timelines,
            planets,
            target_id=r.target_id,
            owner=player,
            ships=r.ships,
            eta=r.my_eta,
            horizon=horizon,
        )
        reinforce_fired_sources.add(r.source_id)

    return moves
