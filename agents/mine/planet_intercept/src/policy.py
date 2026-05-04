"""Policy ABC、HeuristicPolicy、ReplayLogger。"""

from __future__ import annotations

import json
import math
import os
from abc import ABC, abstractmethod

from .action_space import Candidate, candidates_from_heuristic
from .state import GameState, global_features, planet_features
from .targeting import (
    CAP_DUMP_MARGIN_TURNS,
    MAX_EXPAND_PER_TURN,
    NEUTRAL_OWNER,
    _estimate_max_capacity,
    classify_defense,
    enumerate_candidates,
    enumerate_intercept_candidates,
    enumerate_reinforce_candidates,
    enumerate_snipe_candidates,
    enumerate_support_candidates,
    select_move,
)
from .world import apply_planned_arrival

_REPLAY_ENV = "ORBIT_WARS_REPLAY_LOG"


def _pick_dump_target(
    mine: "Planet",
    all_planets: list,
    attack_cands: list,
    player: int,
) -> tuple[float, int] | None:
    """容量ダンプ先を選ぶ。(angle, ships) を返す。なければ None。"""
    # 1. value最大の attack 候補 (value > 0 優先、なければ最大でも使う)
    if attack_cands:
        best = max(attack_cands, key=lambda c: c[3])
        angle = best[2]
        return angle, best[1]

    # 2. 最前線の自惑星 (全敵惑星への最短距離が最小)
    enemy_planets = [p for p in all_planets if p.owner not in (player, NEUTRAL_OWNER)]
    my_allies = [p for p in all_planets if p.owner == player and p.id != mine.id]
    if enemy_planets and my_allies:
        def frontier_score(p):
            return min(math.hypot(p.x - e.x, p.y - e.y) for e in enemy_planets)
        frontier = min(my_allies, key=frontier_score)
        angle = math.atan2(frontier.y - mine.y, frontier.x - mine.x)
        return angle, mine.ships

    # 3. 最も近い敵惑星に直接発射
    enemy_planets = [p for p in all_planets if p.owner not in (player, NEUTRAL_OWNER)]
    if enemy_planets:
        nearest = min(enemy_planets, key=lambda p: math.hypot(p.x - mine.x, p.y - mine.y))
        angle = math.atan2(nearest.y - mine.y, nearest.x - mine.x)
        return angle, mine.ships
    return None


class Policy(ABC):
    @abstractmethod
    def act(self, gs: GameState) -> list[tuple[int, float, int]]:
        """[[planet_id, angle, ships], ...] を返す。"""


class HeuristicPolicy(Policy):
    """現行ヒューリスティックを GameState インターフェースでラップする。

    act() 後に last_candidates_by_source と last_chosen が更新される。
    ReplayLogger はこれを使って replay を記録する。
    """

    def __init__(self):
        self.last_candidates_by_source: dict[int, list[Candidate]] = {}
        self.last_chosen: list[Candidate] = []

    def act(self, gs: GameState) -> list[tuple[int, float, int]]:
        self.last_candidates_by_source = {}
        self.last_chosen = []

        if not gs.my_planets:
            return []

        n = len(gs.my_planets)
        planned: dict[int, int] = {}
        intercepted_ids: set[int] = set()
        expand_fired_this_turn: int = 0
        fired_sources: set[int] = set()

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
                mode=gs.mode,
                remaining_turns=gs.remaining_turns,
                timelines=gs.timelines,
                my_planet_count=n,
                domination=gs.domination,
                is_opening=gs.is_opening,
            )

        moves = []
        for mine in gs.my_planets:
            status, reserve = gs.defense_status[mine.id]

            # 容量ダンプ: 生産停止を防ぐため上限手前で強制射出
            max_cap = _estimate_max_capacity(mine)
            if mine.ships >= max_cap - mine.production * CAP_DUMP_MARGIN_TURNS:
                attack_cands = attack_cands_by_planet.get(mine.id, [])
                dump_result = _pick_dump_target(mine, gs.planets, attack_cands, gs.player)
                if dump_result is not None:
                    dump_angle, _ = dump_result
                    dump_ships = max(1, mine.ships - reserve)
                    if dump_ships > 0:
                        moves.append([mine.id, dump_angle, dump_ships])
                        fired_sources.add(mine.id)
                        continue

            if status == "doomed" and n > 1:
                safe_allies = [
                    p
                    for p in gs.my_planets
                    if p.id != mine.id and gs.defense_status[p.id][0] != "doomed"
                ]
                if safe_allies:
                    nearest_ally = min(
                        safe_allies,
                        key=lambda p: (p.x - mine.x) ** 2 + (p.y - mine.y) ** 2,
                    )
                    evac_angle = math.atan2(
                        nearest_ally.y - mine.y, nearest_ally.x - mine.x
                    )
                    if mine.ships > 0:
                        moves.append([mine.id, evac_angle, mine.ships])
                continue

            attack_cands = attack_cands_by_planet[mine.id]
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
            )
            support_cands = [c for c in support_cands if c[0].id not in intercepted_ids]
            if gs.mode == "behind":
                snipe_cands = enumerate_snipe_candidates(
                    mine,
                    gs.planets,
                    gs.fleets,
                    gs.player,
                    angular_velocity=gs.angular_velocity,
                    planned=planned,
                    remaining_turns=gs.remaining_turns,
                    timelines=gs.timelines,
                    ledger=gs.ledger,
                    horizon=gs.horizon,
                )
            else:
                snipe_cands = []

            # Candidate 変換 (ログ用)
            cands_for_log = candidates_from_heuristic(
                mine,
                attack_cands,
                intercept_cands,
                support_cands,
                snipe_cands,
                reserve,
            )
            self.last_candidates_by_source[mine.id] = cands_for_log

            all_cands = attack_cands + intercept_cands + support_cands + snipe_cands
            picked = select_move(mine, all_cands, reserve=reserve, my_planet_count=n)
            if picked is None:
                continue

            target_id, angle, ships, my_eta = picked

            target_planet_obj = next((p for p in gs.planets if p.id == target_id), None)
            if (
                gs.is_opening
                and target_planet_obj is not None
                and target_planet_obj.owner == NEUTRAL_OWNER
            ):
                if expand_fired_this_turn >= MAX_EXPAND_PER_TURN:
                    continue
                expand_fired_this_turn += 1

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

            # 採用した Candidate を記録
            chosen_cand = next(
                (
                    c
                    for c in cands_for_log
                    if c.target_id == target_id and c.ships_bucket == 0
                ),
                None,
            )
            if chosen_cand is not None:
                chosen_ships = Candidate(
                    source_id=chosen_cand.source_id,
                    target_id=chosen_cand.target_id,
                    angle=angle,
                    ships=ships,
                    ships_bucket=chosen_cand.ships_bucket,
                    value=chosen_cand.value,
                    my_eta=my_eta,
                    kind=chosen_cand.kind,
                )
                self.last_chosen.append(chosen_ships)

            moves.append([mine.id, angle, ships])

        # reinforce パス
        reinforce_missions = enumerate_reinforce_candidates(
            my_planets=gs.my_planets,
            target_candidates_by_planet=attack_cands_by_planet,
            timelines=gs.timelines,
            reserve_of=lambda p: gs.defense_status[p.id][1],
        )
        reinforce_fired_sources: set[int] = set()
        for r in sorted(reinforce_missions, key=lambda m: -m.value):
            if r.source_id in fired_sources:
                continue
            if r.source_id in reinforce_fired_sources:
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


class ReplayLogger:
    """模倣学習用の replay を JSONL で記録する。

    環境変数 ORBIT_WARS_REPLAY_LOG にパスが設定されているときのみ動作する。
    """

    def is_enabled(self) -> bool:
        return bool(os.environ.get(_REPLAY_ENV))

    def log_turn(
        self,
        gs: GameState,
        candidates_by_source: dict[int, list[Candidate]],
        chosen: list[Candidate],
    ) -> None:
        path = os.environ.get(_REPLAY_ENV)
        if not path:
            return

        chosen_by_source: dict[int, Candidate] = {c.source_id: c for c in chosen}

        gf = global_features(gs).tolist()
        sources_data = []
        for mine in gs.my_planets:
            cands = candidates_by_source.get(mine.id, [])
            chosen_cand = chosen_by_source.get(mine.id)

            chosen_idx = None
            chosen_target_id = None
            if chosen_cand is not None:
                chosen_target_id = chosen_cand.target_id
                for i, c in enumerate(cands):
                    if (
                        c.target_id == chosen_cand.target_id
                        and c.ships_bucket == chosen_cand.ships_bucket
                    ):
                        chosen_idx = i
                        break

            pf = planet_features(mine, gs, source=None).tolist()
            sources_data.append(
                {
                    "source_id": mine.id,
                    "planet_features": pf,
                    "candidates": [
                        {
                            "target_id": c.target_id,
                            "ships_bucket": c.ships_bucket,
                            "ships": c.ships,
                            "kind": c.kind,
                            "value": round(c.value, 4),
                            "my_eta": round(c.my_eta, 3),
                        }
                        for c in cands
                    ],
                    "chosen_idx": chosen_idx,
                    "chosen_target_id": chosen_target_id,
                }
            )

        record = {
            "step": gs.step,
            "player": gs.player,
            "global_features": gf,
            "sources": sources_data,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False))
            f.write("\n")
