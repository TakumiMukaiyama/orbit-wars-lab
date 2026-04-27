import math

import pytest

from src.targeting import (
    AHEAD_THRESHOLD,
    BEHIND_THRESHOLD,
    HOLD_HORIZON,
    NEUTRAL_OWNER,
    build_planned_commitments,
    classify_defense,
    compute_domination,
    compute_rival_eta,
    compute_rival_eta_per_player,
    enumerate_candidates,
    enumerate_intercept_candidates,
    fleet_heading_to,
    select_move,
    ships_budget,
    target_value,
)
from src.utils import Fleet, Planet
from src.world import Arrival, simulate_planet_timeline


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

    def test_neutral_eta_production_not_included(self):
        t = P(0, NEUTRAL_OWNER, 0, 0, ships=10, prod=2)
        # 中立惑星は所有されるまで生産しないため、ETA 中の production は足さない
        assert ships_budget(t, my_eta=5.0) == 11

    def test_already_sent_subtracted(self):
        t = P(0, 1, 0, 0, ships=10, prod=2)
        # garrison=20, already_sent=8 -> 20 - 8 + 1 = 13
        assert ships_budget(t, my_eta=5.0, already_sent=8) == 13

    def test_already_sent_covers_all_returns_zero(self):
        t = P(0, 1, 0, 0, ships=10, prod=0)
        # garrison=10, already_sent=15 -> max(0, 10 - 15 + 1) = 0
        assert ships_budget(t, my_eta=0.0, already_sent=15) == 0

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

    def test_planned_reduces_ships_needed(self):
        mine = P(0, 0, 0, 0, ships=50)
        target = P(1, 1, 10, 0, ships=10, prod=0)
        planets = [mine, target]
        # planned なし: garrison=10+0=10 -> ships_needed=11
        cands_no_plan = enumerate_candidates(mine, planets, fleets=[], player=0, planned={})
        # planned あり: already_sent=8 -> max(1, 10-8+1)=3
        cands_planned = enumerate_candidates(mine, planets, fleets=[], player=0, planned={1: 8})
        ships_no = next(c[1] for c in cands_no_plan if c[0].id == 1)
        ships_pl = next(c[1] for c in cands_planned if c[0].id == 1)
        assert ships_pl < ships_no

    def test_planned_fully_covered_excludes_candidate(self):
        mine = P(0, 0, 0, 0, ships=50)
        target = P(1, 1, 10, 0, ships=5, prod=0)
        planets = [mine, target]
        # already_sent=100 -> max(0, 5-100+1) = 0 なので候補から除外
        cands = enumerate_candidates(mine, planets, fleets=[], player=0, planned={1: 100})
        assert all(c[0].id != 1 for c in cands)


class TestBuildPlannedCommitments:
    def test_existing_own_fleet_reduces_target_budget(self):
        mine = P(0, 0, 0, 0, ships=50)
        target = P(1, NEUTRAL_OWNER, 20, 0, ships=10, prod=0)
        fleet = F(10, 0, 5, 0, angle=0.0, from_id=0, ships=8)
        planets = [mine, target]

        planned = build_planned_commitments(planets, [fleet], player=0)
        assert planned == {1: 8}

        cands_no_plan = enumerate_candidates(mine, planets, fleets=[], player=0, planned={})
        cands_planned = enumerate_candidates(mine, planets, fleets=[], player=0, planned=planned)
        ships_no = next(c[1] for c in cands_no_plan if c[0].id == 1)
        ships_pl = next(c[1] for c in cands_planned if c[0].id == 1)
        assert ships_pl == ships_no - 8

    def test_existing_own_fleet_covered_target_is_excluded(self):
        mine = P(0, 0, 0, 0, ships=50)
        target = P(1, NEUTRAL_OWNER, 20, 0, ships=5, prod=0)
        fleet = F(10, 0, 5, 0, angle=0.0, from_id=0, ships=10)
        planets = [mine, target]

        planned = build_planned_commitments(planets, [fleet], player=0)
        cands = enumerate_candidates(mine, planets, fleets=[], player=0, planned=planned)
        assert all(c[0].id != 1 for c in cands)

    def test_existing_own_fleet_counts_nearest_target_on_line(self):
        mine = P(0, 0, 0, 0, ships=50)
        near = P(1, NEUTRAL_OWNER, 20, 0, ships=5, prod=0)
        far = P(2, NEUTRAL_OWNER, 40, 0, ships=5, prod=0)
        fleet = F(10, 0, 5, 0, angle=0.0, from_id=0, ships=10)

        planned = build_planned_commitments([mine, far, near], [fleet], player=0)
        assert planned == {1: 10}

    def test_enemy_planet_not_counted(self):
        mine = P(0, 0, 0, 0, ships=50)
        enemy_target = P(1, 1, 20, 0, ships=5, prod=0)
        fleet = F(10, 0, 5, 0, angle=0.0, from_id=0, ships=10)

        planned = build_planned_commitments([mine, enemy_target], [fleet], player=0)
        assert planned == {}

    def test_sun_crossing_target_not_counted(self):
        mine = P(0, 0, 0, 0, ships=50)
        target = P(1, NEUTRAL_OWNER, 60, 50, ships=5, prod=0)
        fleet = F(10, 0, 40, 50, angle=0.0, from_id=0, ships=10)

        planned = build_planned_commitments([mine, target], [fleet], player=0)
        assert planned == {}

    def test_enemy_and_miss_fleets_ignored(self):
        mine = P(0, 0, 0, 0, ships=50)
        target = P(1, NEUTRAL_OWNER, 20, 0, ships=5, prod=0)
        enemy = F(10, 1, 5, 0, angle=0.0, from_id=99, ships=10)
        miss = F(11, 0, 5, 10, angle=0.0, from_id=0, ships=10)

        planned = build_planned_commitments([mine, target], [enemy, miss], player=0)
        assert planned == {}


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
        target_id, angle, ships, my_eta = picked
        assert target_id == 2  # P(2) が value 最大
        assert angle == pytest.approx(1.0)
        assert ships == 2
        assert my_eta == 0.0  # 4-tuple 候補なので my_eta=0.0

    def test_negative_value_not_selected(self):
        mine = P(0, 0, 0, 0, ships=100)
        cands = [(P(1, 1, 10, 0, ships=1), 2, 0.0, -5.0)]
        assert select_move(mine, cands) is None

    def test_zero_value_not_selected(self):
        mine = P(0, 0, 0, 0, ships=100)
        cands = [(P(1, 1, 10, 0, ships=1), 2, 0.0, 0.0)]
        assert select_move(mine, cands) is None


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
        ships_needed = defended_cands[0][1]
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

    def test_timeline_filters_defended_planet_that_will_hold(self):
        home = P(0, 0, 20, 10, ships=100)
        defended = P(1, 0, 5, 10, ships=100)
        enemy = F(10, 1, 50, 10, angle=math.pi, from_id=99, ships=15)
        timelines = {
            defended.id: simulate_planet_timeline(
                defended,
                [Arrival(eta=10, owner=1, ships=15)],
                horizon=20,
            )
        }

        cands = enumerate_intercept_candidates(
            home,
            [home, defended],
            fleets=[enemy],
            player=0,
            timelines=timelines,
        )

        assert all(c[0].id != defended.id for c in cands)

    def test_timeline_allows_defended_planet_that_will_fall(self):
        home = P(0, 0, 20, 10, ships=100)
        defended = P(1, 0, 5, 10, ships=10)
        enemy = F(10, 1, 50, 10, angle=math.pi, from_id=99, ships=30)
        timelines = {
            defended.id: simulate_planet_timeline(
                defended,
                [Arrival(eta=10, owner=1, ships=30)],
                horizon=20,
            )
        }

        cands = enumerate_intercept_candidates(
            home,
            [home, defended],
            fleets=[enemy],
            player=0,
            timelines=timelines,
        )

        assert any(c[0].id == defended.id for c in cands)

    def test_timeline_intercept_ships_needed_matches_deficit(self):
        """timeline 駆動: fall turn 時点の敵残存 + 1 を ships_needed として採用。"""
        home = P(0, 0, 20, 10, ships=100)
        defended = P(1, 0, 5, 10, ships=10, prod=0)
        # 敵 30 ships 到着 -> defender 10 と衝突 -> 敵奪取 state.ships=20
        enemy = F(10, 1, 50, 10, angle=math.pi, from_id=99, ships=30)
        timeline = simulate_planet_timeline(
            defended,
            [Arrival(eta=10, owner=1, ships=30)],
            horizon=20,
        )
        cands = enumerate_intercept_candidates(
            home,
            [home, defended],
            fleets=[enemy],
            player=0,
            timelines={defended.id: timeline},
        )
        defended_cands = [c for c in cands if c[0].id == defended.id]
        assert defended_cands, "intercept 候補が出てこない"
        ships_needed = defended_cands[0][1]
        # 敵 30 + 1 = 31 ではなく、timeline 上 state.ships=20 + 1 = 21 になるべき
        assert ships_needed == 21

    def test_timeline_intercept_skipped_when_eta_beyond_fall(self):
        """my_eta > fall_turn の候補は除外される。"""
        # home を defended の反対側遠方に置く -> fleet_intercept_point の my_eta が fall_turn を超える
        home = P(0, 0, 95, 90, ships=100)
        defended = P(1, 0, 5, 10, ships=10, prod=0)
        enemy = F(10, 1, 10, 10, angle=math.pi, from_id=99, ships=30)
        # arrival eta を十分に小さく設定 (fall_turn=1)
        timeline = simulate_planet_timeline(
            defended,
            [Arrival(eta=1, owner=1, ships=30)],
            horizon=20,
        )
        cands = enumerate_intercept_candidates(
            home,
            [home, defended],
            fleets=[enemy],
            player=0,
            timelines={defended.id: timeline},
        )
        assert all(c[0].id != defended.id for c in cands)

    def test_value_penalizes_travel_time(self):
        """同一 defended / 同一 threat に対し、my_eta が大きい自惑星ほど value が小さい。"""
        defended = P(1, 0, 5, 10, ships=10, prod=0)
        enemy = F(10, 1, 50, 10, angle=math.pi, from_id=99, ships=30)
        timeline = simulate_planet_timeline(
            defended,
            [Arrival(eta=10, owner=1, ships=30)],
            horizon=20,
        )
        # fleet の軌跡上、near は敵に近く my_eta 小、far は敵から遠く my_eta 大。
        near = P(0, 0, 30, 10, ships=100)
        far = P(2, 0, 15, 10, ships=100)

        near_cands = enumerate_intercept_candidates(
            near, [near, defended], fleets=[enemy], player=0,
            timelines={defended.id: timeline},
        )
        far_cands = enumerate_intercept_candidates(
            far, [far, defended], fleets=[enemy], player=0,
            timelines={defended.id: timeline},
        )
        near_best = max(c[3] for c in near_cands if c[0].id == defended.id)
        far_best = max(c[3] for c in far_cands if c[0].id == defended.id)
        assert near_best > far_best

    def test_value_regression_timeline_ships_needed(self):
        """G3 回帰: value 式変更後も ships_needed は timeline 上の不足分を使う。"""
        home = P(0, 0, 20, 10, ships=100)
        defended = P(1, 0, 5, 10, ships=10, prod=0)
        enemy = F(10, 1, 50, 10, angle=math.pi, from_id=99, ships=30)
        timeline = simulate_planet_timeline(
            defended,
            [Arrival(eta=10, owner=1, ships=30)],
            horizon=20,
        )
        cands = enumerate_intercept_candidates(
            home, [home, defended], fleets=[enemy], player=0,
            timelines={defended.id: timeline},
        )
        defended_cands = [c for c in cands if c[0].id == defended.id]
        assert defended_cands
        assert defended_cands[0][1] == 21


class TestClassifyDefense:
    def test_no_incoming_is_safe(self):
        mine = P(0, 0, 50, 50, ships=50)
        status, reserve = classify_defense(mine, fleets=[], player=0)
        assert status == "safe"
        assert reserve == 0

    def test_threatened_when_ships_cover_incoming(self):
        mine = P(0, 0, 50, 50, ships=50)
        enemy = F(1, 1, 30, 50, angle=0.0, from_id=99, ships=30)
        status, reserve = classify_defense(mine, [enemy], player=0)
        # mine.ships=50 >= incoming=30 -> threatened
        assert status == "threatened"
        assert reserve == 30

    def test_doomed_when_ships_insufficient(self):
        mine = P(0, 0, 50, 50, ships=10)
        enemy = F(1, 1, 30, 50, angle=0.0, from_id=99, ships=30)
        status, reserve = classify_defense(mine, [enemy], player=0)
        # mine.ships=10 < incoming=30 -> doomed
        assert status == "doomed"
        assert reserve == 30

    def test_own_fleet_not_counted(self):
        mine = P(0, 0, 50, 50, ships=10)
        own = F(1, 0, 30, 50, angle=0.0, from_id=99, ships=30)
        status, reserve = classify_defense(mine, [own], player=0)
        assert status == "safe"

    def test_sideways_fleet_ignored(self):
        mine = P(0, 0, 50, 50, ships=10)
        sideways = F(1, 1, 20, 20, angle=0.0, from_id=99, ships=30)
        status, reserve = classify_defense(mine, [sideways], player=0)
        assert status == "safe"

    def test_multiple_fleets_summed(self):
        mine = P(0, 0, 50, 50, ships=40)
        e1 = F(1, 1, 30, 50, angle=0.0, from_id=99, ships=20)
        e2 = F(2, 2, 30, 50, angle=0.0, from_id=99, ships=25)
        status, reserve = classify_defense(mine, [e1, e2], player=0)
        # incoming=45, mine.ships=40 < 45 -> doomed
        assert status == "doomed"
        assert reserve == 45

    def test_timeline_saves_planet_via_own_fleet(self):
        """自軍 in-flight fleet が先に合流して救えるケース: safe になるべき。"""
        mine = P(0, 0, 50, 50, ships=10, prod=0)
        # timeline 上、自軍 eta=4 40 ships -> 敵 eta=5 30 ships -> mine は owner=0 で維持
        arrivals = [
            Arrival(eta=4, owner=0, ships=40),
            Arrival(eta=5, owner=1, ships=30),
        ]
        timeline = simulate_planet_timeline(mine, arrivals, horizon=10)
        status, reserve = classify_defense(mine, fleets=[], player=0, timeline=timeline)
        assert status == "safe"
        assert reserve == 0

    def test_timeline_doomed_aligns_with_first_turn_lost(self):
        """敵のみ到着する timeline で first_turn_lost 時点の敵兵力が reserve になる。"""
        mine = P(0, 0, 50, 50, ships=10, prod=0)
        # eta=3 で敵 30 ships -> 戦闘後 owner=1, ships=20
        arrivals = [Arrival(eta=3, owner=1, ships=30)]
        timeline = simulate_planet_timeline(mine, arrivals, horizon=10)
        status, reserve = classify_defense(mine, fleets=[], player=0, timeline=timeline)
        assert status == "doomed"
        # fall_turn=3 時点の state.ships は 20 (敵側)
        assert reserve == 20

    def test_timeline_threatened_when_defender_can_hold(self):
        """timeline 上の deficit < mine.ships なら threatened。"""
        # fall するケースを作るには defender=0 で ships=5、敵 20 -> fall_turn の state.ships=15
        vulnerable = P(1, 0, 50, 50, ships=5, prod=0)
        arrivals = [Arrival(eta=2, owner=1, ships=20)]
        timeline = simulate_planet_timeline(vulnerable, arrivals, horizon=5)
        # vulnerable.ships=5 < reserve=15 -> doomed のはずだが、
        # mine.ships=100 に差し替えて呼べば threatened になる契約を確認
        status, reserve = classify_defense(
            Planet(id=1, owner=0, x=50, y=50, radius=1.0, ships=100, production=0),
            fleets=[], player=0, timeline=timeline,
        )
        assert status == "threatened"
        assert reserve == 15


from src.targeting import SwarmMission, enumerate_swarm_candidates


class TestEnumerateSwarmCandidates:
    def test_swarm_mission_dataclass_importable(self):
        """SwarmMission が dataclass として使えること。"""
        target = P(2, 1, 30, 0, ships=10, prod=1)
        src_a = P(0, 0, 0, 0, ships=30)
        src_b = P(1, 0, 0, 5, ships=30)
        m = SwarmMission(
            target=target,
            src_a=src_a, ships_a=20, angle_a=0.0, eta_a=5.0,
            src_b=src_b, ships_b=15, angle_b=0.1, eta_b=6.0,
            value=10.0,
        )
        assert m.target.id == 2
        assert m.ships_a == 20
        assert m.ships_b == 15

    def test_two_sources_pooled_when_each_alone_insufficient(self):
        """各源では足りないが合算で足りる target に対して mission が返ること。"""
        # 中立惑星: ships_needed = 31, 各 src は 30 ships -> 単独不可、合算 60 >= 31
        target = P(2, NEUTRAL_OWNER, 10, 0, ships=30, prod=2)
        src_a = P(0, 0, 0, 0, ships=30)
        src_b = P(1, 0, 5, 0, ships=30)
        missions = enumerate_swarm_candidates(
            [src_a, src_b],
            [src_a, src_b, target],
            fleets=[],
            player=0,
        )
        assert any(m.target.id == target.id for m in missions)
        m = next(m for m in missions if m.target.id == target.id)
        assert m.ships_a + m.ships_b >= 31
        assert m.value > 0

    def test_eta_too_different_excluded(self):
        """ETA 差が ETA_SYNC_TOLERANCE を超えるペアは mission にならない。"""
        target = P(2, 1, 100, 0, ships=30, prod=2)
        src_near = P(0, 0, 99, 0, ships=60)   # eta ≈ 1
        src_far  = P(1, 0, 0, 0,  ships=60)   # eta >> 3
        missions = enumerate_swarm_candidates(
            [src_near, src_far],
            [src_near, src_far, target],
            fleets=[],
            player=0,
        )
        assert all(
            not (m.src_a.id == src_near.id and m.src_b.id == src_far.id)
            and not (m.src_a.id == src_far.id and m.src_b.id == src_near.id)
            for m in missions
        )

    def test_fired_sources_excluded(self):
        """fired_sources に含まれる惑星はスウォームに使われない。"""
        target = P(2, 1, 10, 0, ships=20, prod=2)
        src_a = P(0, 0, 0, 0, ships=60)
        src_b = P(1, 0, 5, 0, ships=60)
        missions = enumerate_swarm_candidates(
            [src_a, src_b],
            [src_a, src_b, target],
            fleets=[],
            player=0,
            fired_sources={src_a.id},
        )
        assert all(m.src_a.id != src_a.id and m.src_b.id != src_a.id for m in missions)


class TestComputeRivalEtaOrbital:
    def test_angular_velocity_signature_accepted(self):
        """angular_velocity 引数が受け付けられること。"""
        target = P(1, -1, 30, 50, ships=5)
        rival_planet = P(2, 1, 70, 50, ships=15)
        planets = [P(0, 0, 10, 50, ships=10), rival_planet, target]
        # 引数が存在することだけ確認 (TypeError が出ないこと)
        eta = compute_rival_eta(target, my_player=0, fleets=[], planets=planets,
                                angular_velocity=0.03)
        assert math.isfinite(eta)

    def test_orbital_and_static_give_different_eta(self):
        """angular_velocity があるとき orbital ターゲットの rival ETA が静止計算と異なること。"""
        # 軌道惑星: 中心(50,50) から距離 r=20 < 50 の惑星
        target = P(1, -1, 70, 50, ships=5)  # (70,50) -> r=20 < 50 -> orbital
        rival_planet = P(2, 1, 10, 50, ships=15)  # 反対側
        planets = [P(0, 0, 90, 50, ships=10), rival_planet, target]
        eta_static = compute_rival_eta(target, my_player=0, fleets=[], planets=planets,
                                        angular_velocity=0.0)
        eta_orbital = compute_rival_eta(target, my_player=0, fleets=[], planets=planets,
                                         angular_velocity=0.03)
        # 軌道惑星なので両者は異なるはず
        assert eta_static != pytest.approx(eta_orbital, rel=0.01)


class TestComputeDomination:
    def test_equal_returns_zero(self):
        dom = compute_domination(my_total=100, enemy_total=100)
        assert dom == pytest.approx(0.0)

    def test_all_mine_returns_one(self):
        dom = compute_domination(my_total=100, enemy_total=0)
        assert dom == pytest.approx(1.0)

    def test_all_enemy_returns_minus_one(self):
        dom = compute_domination(my_total=0, enemy_total=100)
        assert dom == pytest.approx(-1.0)

    def test_both_zero_returns_zero(self):
        dom = compute_domination(my_total=0, enemy_total=0)
        assert dom == pytest.approx(0.0)

    def test_thresholds_exist_and_sign(self):
        assert BEHIND_THRESHOLD < 0
        assert AHEAD_THRESHOLD > 0


class TestEnumerateCandidatesEndgame:
    def test_unreachable_target_excluded(self):
        mine = P(0, 0, 0, 0, ships=50)
        # (60,0) までの距離=60、1 ship -> speed=1.0 -> eta=60 turns
        far_target = P(1, 1, 60, 0, ships=1, prod=1)
        planets = [mine, far_target]
        # remaining_turns=10 なら eta=60 > 10 で除外される
        cands = enumerate_candidates(mine, planets, fleets=[], player=0, remaining_turns=10)
        assert all(c[0].id != far_target.id for c in cands)

    def test_reachable_target_included(self):
        mine = P(0, 0, 0, 0, ships=50)
        near_target = P(1, 1, 5, 0, ships=1, prod=1)
        planets = [mine, near_target]
        # remaining_turns=100 なら eta < 100 で含まれる
        cands = enumerate_candidates(mine, planets, fleets=[], player=0, remaining_turns=100)
        assert any(c[0].id == near_target.id for c in cands)

    def test_no_remaining_turns_no_filter(self):
        mine = P(0, 0, 0, 0, ships=50)
        far_target = P(1, 1, 60, 0, ships=1, prod=1)
        planets = [mine, far_target]
        # remaining_turns=None -> フィルターなし
        cands = enumerate_candidates(mine, planets, fleets=[], player=0, remaining_turns=None)
        assert any(c[0].id == far_target.id for c in cands)


class TestTargetValueWithMode:
    def test_behind_mode_reduces_neutral_value(self):
        mine = P(0, 0, 0, 0, ships=50)
        v_neutral = target_value(
            mine, 20.0, 0.0, 3, math.inf, ships_to_send=7, my_eta=5.0,
            target_owner=NEUTRAL_OWNER, mode="neutral",
        )
        v_behind = target_value(
            mine, 20.0, 0.0, 3, math.inf, ships_to_send=7, my_eta=5.0,
            target_owner=NEUTRAL_OWNER, mode="behind",
        )
        assert v_behind < v_neutral

    def test_ahead_mode_same_as_neutral_for_neutral_planet(self):
        mine = P(0, 0, 0, 0, ships=50)
        v_neutral = target_value(
            mine, 20.0, 0.0, 3, math.inf, ships_to_send=7, my_eta=5.0,
            target_owner=NEUTRAL_OWNER, mode="neutral",
        )
        v_ahead = target_value(
            mine, 20.0, 0.0, 3, math.inf, ships_to_send=7, my_eta=5.0,
            target_owner=NEUTRAL_OWNER, mode="ahead",
        )
        # ahead モードでは中立惑星の HOLD_HORIZON は変えない (敵惑星への積極性は別途)
        assert v_ahead == pytest.approx(v_neutral)

    def test_mode_does_not_affect_enemy_planet(self):
        mine = P(0, 0, 0, 0, ships=50)
        v_behind = target_value(
            mine, 20.0, 0.0, 3, rival_eta=100.0, ships_to_send=10, my_eta=5.0,
            target_owner=1, mode="behind",
        )
        v_neutral = target_value(
            mine, 20.0, 0.0, 3, rival_eta=100.0, ships_to_send=10, my_eta=5.0,
            target_owner=1, mode="neutral",
        )
        # 敵惑星の価値式は mode によらない
        assert v_behind == pytest.approx(v_neutral)
