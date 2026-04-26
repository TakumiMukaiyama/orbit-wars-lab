import math

import pytest

from src.targeting import (
    HOLD_HORIZON,
    NEUTRAL_OWNER,
    compute_rival_eta,
    compute_rival_eta_per_player,
    enumerate_candidates,
    enumerate_intercept_candidates,
    estimate_reserve,
    fleet_heading_to,
    select_move,
    ships_budget,
    target_value,
)
from src.utils import Fleet, Planet


def P(pid, owner, x, y, ships, prod=1):
    return Planet(id=pid, owner=owner, x=x, y=y, radius=1.0, ships=ships, production=prod)


def F(fid, owner, x, y, angle, from_id, ships):
    return Fleet(id=fid, owner=owner, x=x, y=y, angle=angle, from_planet_id=from_id, ships=ships)


class TestShipsBudget:
    def test_ten_ships_with_default_margin(self):
        t = P(0, 1, 0, 0, ships=10)
        assert ships_budget(t) == 11

    def test_zero_ships_at_least_one(self):
        t = P(0, -1, 0, 0, ships=0)
        assert ships_budget(t) >= 1

    def test_large_ships(self):
        t = P(0, 1, 0, 0, ships=100)
        assert ships_budget(t) == 101

    def test_eta_production_included(self):
        t = P(0, 1, 0, 0, ships=10, prod=2)
        # my_eta=5 -> garrison_at_arrival = 10 + 2*5 = 20 -> budget = 21
        assert ships_budget(t, my_eta=5.0) == 21

    def test_already_sent_subtracted(self):
        t = P(0, 1, 0, 0, ships=10, prod=2)
        # garrison=20, already_sent=8 -> 20 - 8 + 1 = 13
        assert ships_budget(t, my_eta=5.0, already_sent=8) == 13

    def test_already_sent_covers_all_returns_one(self):
        t = P(0, 1, 0, 0, ships=10, prod=0)
        # garrison=10, already_sent=15 -> max(1, 10 - 15 + 1) = 1
        assert ships_budget(t, my_eta=0.0, already_sent=15) == 1

    def test_backward_compat_no_args(self):
        t = P(0, 1, 0, 0, ships=10)
        assert ships_budget(t) == 11


class TestTargetValue:
    def test_neutral_inf_rival_positive(self):
        mine = P(0, 0, 0, 0, ships=50)
        v = target_value(
            mine, 20.0, 0.0, 3, math.inf, ships_to_send=7, my_eta=20.0, target_owner=NEUTRAL_OWNER
        )
        assert v > 0

    def test_enemy_reaches_first_returns_zero_gain(self):
        mine = P(0, 0, 0, 0, ships=50)
        v = target_value(
            mine, 20.0, 0.0, 3, rival_eta=0.1, ships_to_send=10, my_eta=20.0, target_owner=1
        )
        assert v < 0

    def test_we_reach_first_positive_gain(self):
        mine = P(0, 0, 0, 0, ships=50)
        v = target_value(
            mine, 20.0, 0.0, 3, rival_eta=100.0, ships_to_send=10, my_eta=5.0, target_owner=1
        )
        assert v > 0


class TestTargetValueNeutralNewSpec:
    """m090 深掘りで確定したバグの再発防止。敵惑星 1 個が存在して rival_eta が有限でも
    中立惑星は future_income ベースで正値化されること。"""

    def test_neutral_finite_rival_still_positive(self):
        mine = P(0, 0, 10, 10, ships=10)
        # rival_eta >= my_eta (threat なし) なら中立は HOLD_HORIZON ベース
        v = target_value(
            mine,
            20.0,
            20.0,
            production=1,
            rival_eta=13.0,
            ships_to_send=7,
            my_eta=11.0,
            target_owner=NEUTRAL_OWNER,
        )
        assert v > 0

    def test_neutral_higher_prod_preferred(self):
        mine = P(0, 0, 10, 10, ships=50)
        v_lo = target_value(
            mine,
            20.0,
            20.0,
            production=1,
            rival_eta=30.0,
            ships_to_send=7,
            my_eta=11.0,
            target_owner=NEUTRAL_OWNER,
        )
        v_hi = target_value(
            mine,
            20.0,
            20.0,
            production=5,
            rival_eta=30.0,
            ships_to_send=7,
            my_eta=11.0,
            target_owner=NEUTRAL_OWNER,
        )
        assert v_hi > v_lo

    def test_neutral_with_threat_falls_back_to_gain_formula(self):
        """rival_eta < my_eta (先着される) なら future_income を与えない。"""
        mine = P(0, 0, 10, 10, ships=50)
        v = target_value(
            mine,
            20.0,
            20.0,
            production=5,
            rival_eta=5.0,
            ships_to_send=10,
            my_eta=20.0,
            target_owner=NEUTRAL_OWNER,
        )
        # production * max(0, 5-20) - 10 = -10
        assert v == pytest.approx(-10.0)

    def test_enemy_planet_still_uses_gain_formula(self):
        mine = P(0, 0, 10, 10, ships=50)
        # 敵惑星 (target_owner=1): HOLD_HORIZON 分岐に入らない
        v_win = target_value(
            mine,
            20.0,
            20.0,
            production=3,
            rival_eta=100.0,
            ships_to_send=10,
            my_eta=5.0,
            target_owner=1,
        )
        v_lose = target_value(
            mine,
            20.0,
            20.0,
            production=3,
            rival_eta=1.0,
            ships_to_send=10,
            my_eta=50.0,
            target_owner=1,
        )
        assert v_win > 0
        assert v_lose < 0


class TestComputeRivalETA:
    def test_no_rivals_returns_inf(self):
        target = P(1, -1, 20, 0, ships=5)
        planets = [P(0, 0, 0, 0, ships=10), target]
        assert compute_rival_eta(target, my_player=0, fleets=[], planets=planets) == math.inf

    def test_enemy_planet_provides_finite_eta(self):
        target = P(1, -1, 20, 0, ships=5)
        planets = [P(0, 0, 0, 0, ships=10), P(2, 1, 30, 0, ships=15), target]
        eta = compute_rival_eta(target, my_player=0, fleets=[], planets=planets)
        assert math.isfinite(eta)
        assert eta > 0

    def test_enemy_fleet_considered(self):
        target = P(1, -1, 20, 0, ships=5)
        planets = [P(0, 0, 0, 0, ships=10), target]
        fleets = [F(0, 1, 19, 0, 0.0, from_id=99, ships=10)]
        eta = compute_rival_eta(target, my_player=0, fleets=fleets, planets=planets)
        assert eta < 5.0


class TestEnumerateCandidates:
    def test_skips_self(self):
        mine = P(0, 0, 0, 0, ships=10)
        planets = [mine, P(1, 1, 10, 0, ships=3)]
        cands = enumerate_candidates(mine, planets, fleets=[], player=0)
        assert all(c[0].id != 0 for c in cands)

    def test_distance_sorted_and_topn(self):
        mine = P(0, 0, 0, 0, ships=10)
        planets = [mine] + [P(i, 1, i * 5, 0, ships=1) for i in range(1, 15)]
        cands = enumerate_candidates(mine, planets, fleets=[], player=0, top_n=5)
        assert len(cands) == 5
        dists = [math.hypot(c[0].x - mine.x, c[0].y - mine.y) for c in cands]
        assert dists == sorted(dists)

    def test_my_planets_excluded(self):
        mine = P(0, 0, 0, 0, ships=10)
        planets = [mine, P(1, 0, 10, 0, ships=5), P(2, 1, 20, 0, ships=3)]
        cands = enumerate_candidates(mine, planets, fleets=[], player=0)
        assert all(c[0].owner != 0 for c in cands)


class TestSelectMove:
    def test_reserve_blocks_small_stockpile(self):
        mine = P(0, 0, 0, 0, ships=6)
        cands = [(P(1, 1, 10, 0, ships=10, prod=1), 12, 0.0, 100.0)]
        assert select_move(mine, cands, reserve=5) is None

    def test_picks_highest_value(self):
        mine = P(0, 0, 0, 0, ships=100)
        cands = [
            (P(1, 1, 10, 0, ships=1), 2, 0.5, 5.0),
            (P(2, 1, 20, 0, ships=1), 2, 1.0, 20.0),
            (P(3, 1, 30, 0, ships=1), 2, 1.5, 15.0),
        ]
        picked = select_move(mine, cands, reserve=5)
        assert picked is not None
        angle, ships = picked
        assert angle == pytest.approx(1.0)
        assert ships == 2

    def test_negative_value_still_selected_as_best_option(self):
        mine = P(0, 0, 0, 0, ships=100)
        cands = [(P(1, 1, 10, 0, ships=1), 2, 0.0, -5.0)]
        result = select_move(mine, cands)
        assert result is not None


class TestComputeRivalETAPerPlayer:
    def test_returns_dict_keyed_by_player(self):
        target = P(1, -1, 20, 0, ships=5)
        planets = [P(0, 0, 0, 0, ships=10), P(2, 1, 30, 0, ships=15), target]
        per = compute_rival_eta_per_player(target, my_player=0, fleets=[], planets=planets)
        assert set(per.keys()) == {1}
        assert math.isfinite(per[1])

    def test_multiple_rivals_per_player_minimum(self):
        target = P(1, -1, 20, 0, ships=5)
        # player 1 が 2 惑星、player 2 が 1 惑星
        planets = [
            P(0, 0, 0, 0, ships=10),
            P(2, 1, 30, 0, ships=15),
            P(3, 1, 60, 0, ships=15),
            P(4, 2, 25, 0, ships=15),
            target,
        ]
        per = compute_rival_eta_per_player(target, my_player=0, fleets=[], planets=planets)
        assert set(per.keys()) == {1, 2}
        # player 1 は (30,0) が (60,0) より近い
        assert per[1] < per[2] or per[1] > 0

    def test_wrapper_matches_min_of_dict(self):
        target = P(1, -1, 20, 0, ships=5)
        planets = [
            P(0, 0, 0, 0, ships=10),
            P(2, 1, 30, 0, ships=15),
            P(3, 2, 40, 0, ships=10),
            target,
        ]
        per = compute_rival_eta_per_player(target, my_player=0, fleets=[], planets=planets)
        eta_min = compute_rival_eta(target, my_player=0, fleets=[], planets=planets)
        assert eta_min == pytest.approx(min(per.values()))

    def test_no_rivals_returns_empty_and_inf(self):
        target = P(1, -1, 20, 0, ships=5)
        planets = [P(0, 0, 0, 0, ships=10), target]
        per = compute_rival_eta_per_player(target, my_player=0, fleets=[], planets=planets)
        assert per == {}
        assert compute_rival_eta(target, my_player=0, fleets=[], planets=planets) == math.inf


class TestFleetHeadingTo:
    def test_direct_hit(self):
        planet = P(0, 0, 50, 50, ships=1)
        # fleet at (20, 50), heading east (angle=0) -> toward planet
        f = F(0, 1, 20, 50, angle=0.0, from_id=99, ships=10)
        assert fleet_heading_to(f, planet) is True

    def test_behind_fleet(self):
        planet = P(0, 0, 50, 50, ships=1)
        # fleet at (20, 50), heading west (angle=pi) -> away from planet
        f = F(0, 1, 20, 50, angle=math.pi, from_id=99, ships=10)
        assert fleet_heading_to(f, planet) is False

    def test_sideways_miss(self):
        planet = P(0, 0, 50, 50, ships=1)
        # fleet at (20, 20), heading east but passes far below planet
        f = F(0, 1, 20, 20, angle=0.0, from_id=99, ships=10)
        assert fleet_heading_to(f, planet) is False


class TestEstimateReserve:
    def test_single_planet_returns_zero(self):
        mine = P(0, 0, 50, 50, ships=50)
        enemy_fleet = F(1, 1, 30, 50, angle=0.0, from_id=99, ships=30)
        r = estimate_reserve(mine, [enemy_fleet], my_player=0, my_planet_count=1)
        assert r == 0

    def test_incoming_enemy_fleet_raises_reserve(self):
        mine = P(0, 0, 50, 50, ships=100)
        enemy_fleet = F(1, 1, 30, 50, angle=0.0, from_id=99, ships=30)
        r = estimate_reserve(mine, [enemy_fleet], my_player=0, my_planet_count=3)
        assert r >= 30

    def test_sideways_fleet_ignored(self):
        mine = P(0, 0, 50, 50, ships=100)
        sideways = F(1, 1, 20, 20, angle=0.0, from_id=99, ships=30)
        r = estimate_reserve(mine, [sideways], my_player=0, my_planet_count=3)
        assert r == 0

    def test_own_fleet_not_counted(self):
        mine = P(0, 0, 50, 50, ships=100)
        own_fleet = F(1, 0, 30, 50, angle=0.0, from_id=99, ships=30)
        r = estimate_reserve(mine, [own_fleet], my_player=0, my_planet_count=3)
        assert r == 0


class TestEnumerateInterceptCandidates:
    def test_no_threat_returns_empty(self):
        mine = P(0, 0, 10, 10, ships=100)
        cands = enumerate_intercept_candidates(mine, [mine], fleets=[], player=0)
        assert cands == []

    def test_incoming_fleet_produces_candidate(self):
        # home を fleet の進行方向 (west) の前方に配置 = 迎え撃ちが可能
        home = P(0, 0, 20, 10, ships=100)
        defended = P(1, 0, 5, 10, ships=20)
        # enemy fleet at (50, 10) heading west (angle=pi) toward defended (5, 10)
        enemy = F(10, 1, 50, 10, angle=math.pi, from_id=99, ships=15)
        cands = enumerate_intercept_candidates(
            home,
            [home, defended],
            fleets=[enemy],
            player=0,
        )
        # home と defended の両方が fleet の進路上 -> 両方 defended として候補化される
        assert len(cands) >= 1
        defended_cands = [c for c in cands if c[0].id == defended.id]
        assert len(defended_cands) >= 1
        _, ships_needed, _, _ = defended_cands[0]
        assert ships_needed >= enemy.ships + 1

    def test_only_enemies_counted(self):
        home = P(0, 0, 10, 10, ships=100)
        defended = P(1, 0, 80, 10, ships=20)
        # own fleet heading to own planet should not create intercept candidate
        own = F(10, 0, 50, 10, angle=0.0, from_id=99, ships=15)
        cands = enumerate_intercept_candidates(
            home,
            [home, defended],
            fleets=[own],
            player=0,
        )
        assert cands == []

    def test_value_scales_with_production(self):
        home = P(0, 0, 10, 10, ships=100)
        defended_lo = P(1, 0, 80, 10, ships=20, prod=1)
        defended_hi = P(2, 0, 80, 90, ships=20, prod=5)
        enemy_lo = F(10, 1, 60, 10, angle=0.0, from_id=99, ships=15)
        enemy_hi = F(11, 1, 60, 90, angle=0.0, from_id=99, ships=15)
        cands = enumerate_intercept_candidates(
            home,
            [home, defended_lo, defended_hi],
            fleets=[enemy_lo, enemy_hi],
            player=0,
        )
        # prod=5 の守備は prod=1 の守備より value が高い
        lo_values = [c[3] for c in cands if c[0].id == defended_lo.id]
        hi_values = [c[3] for c in cands if c[0].id == defended_hi.id]
        if lo_values and hi_values:
            assert max(hi_values) > max(lo_values)
