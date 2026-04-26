import math

import pytest

from src.geometry import (
    _point_to_segment_distance,
    fleet_intercept_point,
    intercept_pos,
    route_angle_and_distance,
    route_eta,
    segment_hits_sun,
    tangent_waypoint,
)
from src.utils import CENTER, SUN_RADIUS, fleet_speed
from tests.test_targeting import F, P


class TestSegmentHitsSun:
    def test_diagonal_through_center_hits(self):
        assert segment_hits_sun(0, 0, 100, 100)

    def test_horizontal_top_edge_misses(self):
        assert not segment_hits_sun(0, 0, 100, 0)

    def test_corner_to_corner_opposite_axis_misses(self):
        assert not segment_hits_sun(0, 100, 100, 100)

    def test_just_outside_sun_misses(self):
        assert not segment_hits_sun(0, CENTER + SUN_RADIUS + 2, 100, CENTER + SUN_RADIUS + 2)

    def test_just_inside_sun_hits(self):
        assert segment_hits_sun(0, CENTER + SUN_RADIUS - 0.1, 100, CENTER + SUN_RADIUS - 0.1)

    def test_zero_length_segment_outside(self):
        assert not segment_hits_sun(10, 10, 10, 10)

    def test_zero_length_segment_inside(self):
        assert segment_hits_sun(CENTER, CENTER, CENTER, CENTER)


class TestTangentWaypoint:
    def test_no_waypoint_when_clear(self):
        assert tangent_waypoint(0, 0, 100, 0) is None

    def test_waypoint_outside_sun(self):
        w = tangent_waypoint(10, 10, 90, 90)
        assert w is not None
        d = math.hypot(w[0] - CENTER, w[1] - CENTER)
        assert d >= SUN_RADIUS

    def test_waypoint_segments_avoid_sun(self):
        src = (10, 10)
        dst = (90, 90)
        w = tangent_waypoint(*src, *dst)
        assert w is not None
        assert not segment_hits_sun(src[0], src[1], w[0], w[1])
        assert not segment_hits_sun(w[0], w[1], dst[0], dst[1])


class TestRouteAngleAndDistance:
    def test_straight_line_is_atan2(self):
        angle, dist = route_angle_and_distance(0, 0, 100, 0)
        assert angle == pytest.approx(0.0)
        assert dist == pytest.approx(100.0)

    def test_detour_longer_than_straight(self):
        src = (10, 10)
        dst = (90, 90)
        _, detour_dist = route_angle_and_distance(*src, *dst)
        straight = math.hypot(dst[0] - src[0], dst[1] - src[1])
        assert detour_dist >= straight


class TestRouteETA:
    def test_eta_scales_with_distance(self):
        eta_close = route_eta(0, 0, 10, 0, ships=1)
        eta_far = route_eta(0, 0, 100, 0, ships=1)
        assert eta_far > eta_close


class TestInterceptPos:
    def test_static_planet_returns_current_pos(self):
        planet = P(1, -1, 70, 50, ships=5)
        ix, iy, eta = intercept_pos(20, 50, 10, planet, angular_velocity=0.0)
        assert ix == pytest.approx(70.0)
        assert iy == pytest.approx(50.0)
        assert eta > 0

    def test_orbital_intercept_differs_from_current(self):
        # 太陽から 20 離れた軌道上 (CENTER+20, CENTER) の惑星、高速回転
        planet = P(1, -1, CENTER + 20, CENTER, ships=5)
        ix, iy, eta = intercept_pos(20, 50, 10, planet, angular_velocity=0.1)
        # インターセプト位置は現在位置と異なるはず (惑星が動くため)
        cur_dist = math.hypot(planet.x - 20, planet.y - 50)
        int_dist = math.hypot(ix - 20, iy - 50)
        # インターセプト後も惑星は軌道半径 20 上にある
        assert math.hypot(ix - CENTER, iy - CENTER) == pytest.approx(20.0, abs=1.0)
        assert eta > 0

    def test_orbital_intercept_eta_consistent(self):
        # インターセプト位置への ETA が返り値の eta と一致する
        planet = P(1, -1, CENTER + 25, CENTER, ships=5)
        ix, iy, eta = intercept_pos(10, 10, 10, planet, angular_velocity=0.05)
        from src.geometry import route_eta as _eta

        eta_to_intercept = _eta(10, 10, ix, iy, 10)
        assert abs(eta_to_intercept - eta) < 1.0


class TestPointToSegmentDistanceParity:
    """ゲーム側 (orbit_wars.py L34) と完全一致することを確認。"""

    def test_same_formula(self):
        p, v, w = (50, 50), (0, 0), (100, 100)
        expected = 0.0
        assert _point_to_segment_distance(p, v, w) == pytest.approx(expected, abs=1e-9)

    def test_perpendicular_distance(self):
        p, v, w = (0, 10), (0, 0), (10, 0)
        assert _point_to_segment_distance(p, v, w) == pytest.approx(10.0)


class TestFleetInterceptPoint:
    def test_stationary_fleet_equivalent_straight_chase(self):
        """fleet.ships=1 (速度 1.0)、自 ships=1 (速度 1.0) の同速ケース。
        fleet が自分に近づくベクトルを持っていれば解けるはず。"""
        # 自分 (0,0)、fleet が (10, 0) で西向き (angle=pi)、互いに近づく
        f = F(0, 1, 10.0, 0.0, angle=math.pi, from_id=99, ships=1)
        res = fleet_intercept_point(0.0, 0.0, 1, f)
        assert res is not None
        ix, iy, t = res
        assert t > 0
        # 会合点は 0 < ix < 10 に収まる
        assert 0.0 < ix < 10.0
        assert abs(iy) < 1e-6

    def test_converging_fleet_solvable(self):
        f = F(0, 1, 50.0, 0.0, angle=math.pi, from_id=99, ships=5)
        res = fleet_intercept_point(0.0, 0.0, 30, f)
        assert res is not None
        ix, iy, t = res
        assert t > 0
        # 合流時刻での fleet 位置 = 解 (ix, iy)
        fspd = fleet_speed(f.ships)
        expect_x = f.x + math.cos(f.angle) * fspd * t
        expect_y = f.y + math.sin(f.angle) * fspd * t
        assert ix == pytest.approx(expect_x)
        assert iy == pytest.approx(expect_y)
        # src から (ix, iy) への距離 / my_speed == t
        dist = math.hypot(ix, iy)
        assert dist / fleet_speed(30) == pytest.approx(t, rel=1e-6)

    def test_diverging_same_speed_fleet_returns_none(self):
        """fleet が自分より速度が高く、遠ざかる方向ならそもそも追いつけない。"""
        # 自 ships=1 (速度 1.0)、fleet ships=1000 で高速。fleet が自分から離れていく方向
        f = F(0, 1, 10.0, 0.0, angle=0.0, from_id=99, ships=1000)
        res = fleet_intercept_point(0.0, 0.0, 1, f)
        assert res is None
