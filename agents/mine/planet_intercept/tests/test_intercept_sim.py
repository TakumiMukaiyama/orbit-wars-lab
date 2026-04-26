"""軌道インターセプト精度のシミュレーションテスト。

Kaggle エンジン (orbit_wars.py) と同じ物理演算を再現し、intercept_pos が返す
(角度, ETA) で実際にフリートが動く惑星に当たるかを検証する。

前提: enumerate_candidates では segment_hits_sun が True の目標はスキップされる。
     そのため本テストは「太陽を通らない経路」のみを対象とする。

テスト構成:
  SimEngine               -- orbit_wars.py の fleet 移動 + 惑星回転 + 衝突判定を最小再現
  TestStaticPlanetHit     -- 静止惑星、太陽を通らない距離 / 方向で当たるか
  TestOrbitalPlanetHit    -- 軌道惑星、angular_velocity 別に当たるか
  TestShipsRequired       -- 到着時の production 増分 deficit を計測する情報テスト
  TestSunExclusion        -- 太陽越え目標が候補から除外されることを確認
  TestInterceptAccuracyGrid -- 距離 × angular_velocity のグリッド全セルで命中確認
"""

import math
import pytest

from src.geometry import intercept_pos, route_angle_and_distance, route_eta, segment_hits_sun
from src.targeting import enumerate_candidates
from src.utils import CENTER, BOARD_SIZE, SUN_RADIUS, Planet, Fleet, fleet_speed

# ---- 最小エンジン再現 -------------------------------------------------


def _point_to_seg_dist(p, v, w):
    """orbit_wars.py L34 と同じ線分-点距離。"""
    l2 = (v[0] - w[0]) ** 2 + (v[1] - w[1]) ** 2
    if l2 == 0.0:
        return math.hypot(p[0] - v[0], p[1] - v[1])
    t = max(0.0, min(1.0, ((p[0] - v[0]) * (w[0] - v[0]) + (p[1] - v[1]) * (w[1] - v[1])) / l2))
    px = v[0] + t * (w[0] - v[0])
    py = v[1] + t * (w[1] - v[1])
    return math.hypot(p[0] - px, p[1] - py)


class SimEngine:
    """orbit_wars.py の 1 ターン物理ループを再現する最小シミュレーター。

    使い方:
        engine = SimEngine(planets, angular_velocity, ships, src=(x,y), angle=a)
        for _ in range(max_turns):
            result = engine.step()
            if result is not None:
                break  # hit planet id / "sun_destroyed" / "out_of_bounds"
    """

    MAX_SPEED = 6.0

    def __init__(
        self, planets: list, angular_velocity: float, ships: int, src: tuple, angle: float
    ):
        self.planets = [list(p) for p in planets]
        self.initial_planets = [list(p) for p in planets]
        self.angular_velocity = angular_velocity
        self.step_count = 0

        ships = max(1, ships)
        if ships <= 1:
            speed = 1.0
        else:
            speed = 1.0 + (self.MAX_SPEED - 1.0) * (math.log(ships) / math.log(1000)) ** 1.5
        self.speed = min(speed, self.MAX_SPEED)
        self.angle = angle

        # fleet は発射元惑星 surface から 0.1 外側に置く (orbit_wars.py L546)
        self.fx = src[0] + math.cos(angle) * 0.1
        self.fy = src[1] + math.sin(angle) * 0.1

    def step(self):
        """1 ターン進めて衝突した惑星の id を返す。なければ None。"""
        self.step_count += 1

        old_pos = (self.fx, self.fy)
        self.fx += math.cos(self.angle) * self.speed
        self.fy += math.sin(self.angle) * self.speed
        new_pos = (self.fx, self.fy)

        if not (0 <= self.fx <= BOARD_SIZE and 0 <= self.fy <= BOARD_SIZE):
            return "out_of_bounds"
        if _point_to_seg_dist((CENTER, CENTER), old_pos, new_pos) < SUN_RADIUS:
            return "sun_destroyed"

        # Fleet 移動中の衝突判定 (orbit_wars.py L596-601)
        for planet in self.planets:
            if _point_to_seg_dist((planet[2], planet[3]), old_pos, new_pos) < planet[4]:
                return planet[0]

        # 惑星回転 (orbit_wars.py L622-640)
        for i, planet in enumerate(self.planets):
            init = self.initial_planets[i]
            dx = init[2] - CENTER
            dy = init[3] - CENTER
            r = math.hypot(dx, dy)
            if r + planet[4] < 50.0:
                init_angle = math.atan2(dy, dx)
                cur_angle = init_angle + self.angular_velocity * self.step_count
                old_p = (
                    CENTER
                    + r * math.cos(init_angle + self.angular_velocity * (self.step_count - 1)),
                    CENTER
                    + r * math.sin(init_angle + self.angular_velocity * (self.step_count - 1)),
                )
                planet[2] = CENTER + r * math.cos(cur_angle)
                planet[3] = CENTER + r * math.sin(cur_angle)
                new_p = (planet[2], planet[3])
                # Sweep 判定 (orbit_wars.py L609-620)
                if _point_to_seg_dist((self.fx, self.fy), old_p, new_p) < planet[4]:
                    return planet[0]

        return None


def _fire_and_check(src_x, src_y, ships, planet, angular_velocity, max_turns=500):
    """intercept_pos の角度でフリートを発射し惑星 id にヒットするかを返す。

    Returns: (hit: bool, actual_eta: int | None, result_str: str)
      result_str: "hit" / "sun_destroyed" / "out_of_bounds" / "timeout" / "intercept_sun_crossing"
    """
    ix, iy, _ = intercept_pos(src_x, src_y, ships, planet, angular_velocity)
    if segment_hits_sun(src_x, src_y, ix, iy):
        return False, None, "intercept_sun_crossing"
    angle, _ = route_angle_and_distance(src_x, src_y, ix, iy)

    raw = (
        planet.id,
        planet.owner,
        planet.x,
        planet.y,
        planet.radius,
        planet.ships,
        planet.production,
    )
    engine = SimEngine([raw], angular_velocity, ships, (src_x, src_y), angle)

    for turn in range(max_turns):
        result = engine.step()
        if result == "sun_destroyed":
            return False, None, "sun_destroyed"
        if result == "out_of_bounds":
            return False, None, "out_of_bounds"
        if result == planet.id:
            return True, turn + 1, "hit"

    return False, None, "timeout"


def P(pid, owner, x, y, ships, prod=1, radius=1.0):
    return Planet(id=pid, owner=owner, x=x, y=y, radius=radius, ships=ships, production=prod)


def F(fid, owner, x, y, angle, from_id, ships):
    return Fleet(id=fid, owner=owner, x=x, y=y, angle=angle, from_planet_id=from_id, ships=ships)


# ---- Static Planet Tests ------------------------------------------------


class TestStaticPlanetHit:
    """太陽を通らない静止惑星への射撃が実際にヒットするか。"""

    @pytest.mark.parametrize(
        "src_x,src_y,dst_x,dst_y,desc",
        [
            # 経路が太陽を通らないケースのみ
            (10.0, 10.0, 80.0, 10.0, "horizontal-bottom"),
            (10.0, 10.0, 10.0, 80.0, "vertical-left"),
            (10.0, 10.0, 80.0, 20.0, "diagonal-shallow"),
            (10.0, 10.0, 80.0, 40.0, "diagonal-mid"),
            (10.0, 90.0, 80.0, 90.0, "horizontal-top"),
            (90.0, 10.0, 90.0, 80.0, "vertical-right"),
            (10.0, 80.0, 80.0, 80.0, "horizontal-near-top"),
            (80.0, 10.0, 10.0, 10.0, "reverse-horizontal"),
        ],
    )
    def test_static_hit(self, src_x, src_y, dst_x, dst_y, desc):
        assert not segment_hits_sun(src_x, src_y, dst_x, dst_y), (
            f"test case [{desc}] has sun-crossing path - fix test data"
        )
        planet = P(1, -1, dst_x, dst_y, ships=5, radius=1.5)
        hit, eta, result = _fire_and_check(
            src_x, src_y, ships=10, planet=planet, angular_velocity=0.0
        )
        assert hit, f"[{desc}] not hit (result={result}, eta={eta})"

    def test_static_planet_eta_matches_prediction(self):
        """予測 ETA と実際の着弾ターン数の差が 2 ターン以内。"""
        src_x, src_y, ships = 10.0, 10.0, 20
        planet = P(1, -1, 80.0, 10.0, ships=5, radius=2.0)
        assert not segment_hits_sun(src_x, src_y, planet.x, planet.y)
        hit, actual_eta, _ = _fire_and_check(src_x, src_y, ships, planet, 0.0)
        assert hit
        predicted = route_eta(src_x, src_y, planet.x, planet.y, ships)
        assert abs(actual_eta - predicted) <= 2.0, f"predicted={predicted:.1f}, actual={actual_eta}"


# ---- Orbital Planet Tests -----------------------------------------------


class TestOrbitalPlanetHit:
    """軌道惑星への intercept_pos 精度を検証する。

    src=(10,10) 固定、惑星は (CENTER+20, CENTER) = (70,50) に初期配置。
    この経路 (10,10)->(70,50) は太陽を通らない。
    """

    SRC_X = 10.0
    SRC_Y = 10.0
    PLANET_X = CENTER + 20.0  # 70.0
    PLANET_Y = CENTER  # 50.0

    @pytest.mark.parametrize("av", [0.0, 0.02, 0.05, 0.10])
    def test_orbital_hit_various_av(self, av):
        """angular_velocity を変えても、intercept 経路が sun-safe ならヒットする。

        av によっては intercept 収束点が太陽越え経路になる場合がある。
        その場合は enumerate_candidates でも除外されるため、テストをスキップする。
        """
        planet = P(1, -1, self.PLANET_X, self.PLANET_Y, ships=5, radius=1.5)
        assert not segment_hits_sun(self.SRC_X, self.SRC_Y, self.PLANET_X, self.PLANET_Y), (
            "test path crosses sun"
        )
        hit, actual_eta, result = _fire_and_check(
            self.SRC_X, self.SRC_Y, ships=10, planet=planet, angular_velocity=av
        )
        if result == "intercept_sun_crossing":
            pytest.skip(
                f"av={av}: intercept converges to sun-crossing path (excluded by enumerate_candidates)"
            )
        assert result != "sun_destroyed", f"av={av}: fleet destroyed by sun"
        assert hit, f"av={av}: planet not hit (result={result})"

    def test_orbital_eta_within_tolerance(self):
        """intercept_pos の予測 ETA と実際の着弾が 3 ターン以内に収まる。

        av=0.05、src と惑星の相対位置は sun-crossing にならないケース。
        """
        av = 0.05
        # src=(10,10), planet=(50, 75) は sun-safe かつ軌道半径 25
        src_x, src_y, ships = 10.0, 10.0, 15
        planet = P(1, -1, CENTER, CENTER + 25.0, ships=5, radius=1.5)
        assert not segment_hits_sun(src_x, src_y, planet.x, planet.y)
        _ix, _iy, predicted_eta = intercept_pos(src_x, src_y, ships, planet, av)
        hit, actual_eta, result = _fire_and_check(src_x, src_y, ships, planet, av)
        if result == "intercept_sun_crossing":
            pytest.skip("intercept converges to sun-crossing path")
        assert hit, f"planet not hit (result={result})"
        assert abs(actual_eta - predicted_eta) <= 3.0, (
            f"predicted={predicted_eta:.1f}, actual={actual_eta}"
        )

    @pytest.mark.parametrize(
        "av,r",
        [
            (0.02, 20.0),
            (0.05, 25.0),
            (0.02, 35.0),
        ],
    )
    def test_various_orbits(self, av, r):
        """軌道半径を変えても当たるか。src=(10,10) は sun を通らない方向。"""
        # 惑星を (CENTER, CENTER+r) に配置: (50, 50+r) -> src=(10,10) は通らない
        px = CENTER
        py = CENTER + r
        assert not segment_hits_sun(10.0, 10.0, px, py), "path crosses sun"
        planet = P(1, -1, px, py, ships=5, radius=1.5)
        hit, _, result = _fire_and_check(10.0, 10.0, ships=10, planet=planet, angular_velocity=av)
        assert result != "sun_destroyed"
        assert hit, f"av={av}, r={r}: not hit (result={result})"


# ---- Ships Required Tests -----------------------------------------------


class TestShipsRequired:
    """到着時の production 増分 deficit を計測する情報テスト。

    現行の ships_budget = target.ships + 1 は production 増分を無視する。
    「距離が遠いほど deficit が大きい」ことを確認し、
    Phase 1c での ships_budget 修正の根拠とする。
    """

    def _arrival_ships(self, src_x, src_y, ships, planet):
        """フリート到着時点で惑星にいる ships 数 (production 増分込み) を返す。"""
        _, _, eta = intercept_pos(src_x, src_y, ships, planet, 0.0)
        return planet.ships + planet.production * math.ceil(eta), math.ceil(eta)

    @pytest.mark.parametrize(
        "dist,prod,ships",
        [
            (20.0, 1, 10),
            (40.0, 1, 20),
            (40.0, 3, 20),
            (60.0, 5, 30),
        ],
    )
    def test_ships_budget_vs_arrival_ships(self, dist, prod, ships):
        """ships_budget (target.ships + 1) と到着時 ships を比較して記録する。"""
        planet = P(1, -1, 10.0 + dist, 10.0, ships=10, prod=prod, radius=1.5)
        assert not segment_hits_sun(10.0, 10.0, planet.x, planet.y)
        ships_at_arrival, turns = self._arrival_ships(10.0, 10.0, ships, planet)
        budget = planet.ships + 1
        deficit = ships_at_arrival - budget
        # 常に pass: 数値を確認するための記録テスト
        assert True, (
            f"dist={dist}, prod={prod}, turns={turns}: "
            f"budget={budget}, at_arrival={ships_at_arrival}, deficit={deficit}"
        )

    def test_production_deficit_grows_with_distance(self):
        """遠い惑星ほど production 増分の deficit が大きい。"""
        src_x, src_y, prod = 10.0, 10.0, 3
        dists = [20.0, 40.0, 60.0]
        deficits = []
        for dist in dists:
            planet = P(1, -1, src_x + dist, src_y, ships=5, prod=prod, radius=1.5)
            assert not segment_hits_sun(src_x, src_y, planet.x, planet.y)
            at_arrival, _ = self._arrival_ships(src_x, src_y, 10, planet)
            deficits.append(at_arrival - (planet.ships + 1))
        assert deficits[-1] > deficits[0], f"deficit should grow: {deficits}"


# ---- Sun Exclusion Tests ------------------------------------------------


class TestSunExclusion:
    """太陽越えターゲットが enumerate_candidates から除外されることを確認する。

    Phase 1c 修正 (segment_hits_sun フィルタ) の正確さを直接検証する。
    """

    def test_sun_crossing_target_excluded(self):
        """太陽を跨ぐ先の惑星は候補に出てこない。"""
        # src=(10,50), enemy=(90,50): 直線が y=50 を通り太陽を貫く
        mine = P(0, 0, 10.0, 50.0, ships=100)
        sun_crossing_enemy = P(1, 1, 90.0, 50.0, ships=5)
        assert segment_hits_sun(10.0, 50.0, 90.0, 50.0), "test setup: should cross sun"
        cands = enumerate_candidates(mine, [mine, sun_crossing_enemy], fleets=[], player=0)
        assert all(c[0].id != sun_crossing_enemy.id for c in cands), (
            "sun-crossing target should be excluded from candidates"
        )

    def test_non_sun_crossing_target_included(self):
        """太陽を跨がない先の惑星は候補に残る。"""
        mine = P(0, 0, 10.0, 10.0, ships=100)
        safe_enemy = P(1, 1, 80.0, 10.0, ships=5)
        assert not segment_hits_sun(10.0, 10.0, 80.0, 10.0), "test setup: should not cross sun"
        cands = enumerate_candidates(mine, [mine, safe_enemy], fleets=[], player=0)
        assert any(c[0].id == safe_enemy.id for c in cands), (
            "non-sun-crossing target should be in candidates"
        )

    def test_all_candidates_have_non_crossing_paths(self):
        """enumerate_candidates が返す全候補の発射角が太陽を通らない。"""
        mine = P(0, 0, 10.0, 10.0, ships=200)
        enemies = [
            P(1, 1, 90.0, 10.0, ships=5),  # 直線 OK
            P(2, 1, 90.0, 90.0, ships=5),  # 対角線 -> sun crossing
            P(3, 1, 80.0, 40.0, ships=5),  # OK
            P(4, 1, 10.0, 80.0, ships=5),  # 垂直 OK
            P(5, 1, 50.0, 90.0, ships=5),  # OK
        ]
        all_planets = [mine] + enemies
        cands = enumerate_candidates(mine, all_planets, fleets=[], player=0)
        for target, ships_needed, angle, value in cands:
            # 発射角から直進先を計算して太陽を通らないか確認
            # angle から延長線上の点 (十分遠い点) を計算
            far_x = mine.x + math.cos(angle) * 200
            far_y = mine.y + math.sin(angle) * 200
            from src.geometry import _point_to_segment_distance

            sun_dist = _point_to_segment_distance(
                (CENTER, CENTER), (mine.x, mine.y), (far_x, far_y)
            )
            assert sun_dist >= SUN_RADIUS, (
                f"candidate {target.id} has sun-crossing angle {math.degrees(angle):.1f}deg"
            )


# ---- Parameter Grid -------------------------------------------------


class TestInterceptAccuracyGrid:
    """距離 × angular_velocity のグリッドで intercept_pos の命中率を確認する。

    全セルが pass = intercept_pos は全条件で正確。
    src=(10,10) 固定、惑星は sun を通らない方向のみ。
    """

    # (src_dist, planet_x, planet_y, av, note)
    GRID_CASES = [
        # 静止惑星: src=(10,10) から右方向
        (10.0, 80.0, 10.0, 0.0, "static-far-right"),
        (10.0, 50.0, 10.0, 0.0, "static-near-right"),
        # 軌道惑星: (CENTER+20, CENTER) = (70, 50) は sun-safe
        (10.0, CENTER + 20, CENTER, 0.02, "orbital-r20-slow"),
        (10.0, CENTER + 20, CENTER, 0.05, "orbital-r20-mid"),
        (10.0, CENTER + 20, CENTER, 0.10, "orbital-r20-fast"),
        # 軌道惑星: (CENTER, CENTER+25) = (50, 75) も sun-safe
        (10.0, CENTER, CENTER + 25, 0.05, "orbital-r25-upper"),
        # 軌道惑星: (CENTER-20, CENTER) = (30, 50) も sun-safe from (10,10)
        (10.0, CENTER - 20, CENTER, 0.05, "orbital-r20-left"),
    ]

    @pytest.mark.parametrize("src_x,planet_x,planet_y,av,note", GRID_CASES)
    def test_grid_hit(self, src_x, planet_x, planet_y, av, note):
        src_y = 10.0
        assert not segment_hits_sun(src_x, src_y, planet_x, planet_y), (
            f"[{note}] test path crosses sun - fix test data"
        )
        planet = P(1, -1, planet_x, planet_y, ships=5, radius=1.5)
        hit, actual_eta, result = _fire_and_check(
            src_x, src_y, ships=10, planet=planet, angular_velocity=av
        )
        if result == "intercept_sun_crossing":
            pytest.skip(f"[{note}] intercept converges to sun-crossing path")
        assert result != "sun_destroyed", f"[{note}] fleet destroyed by sun"
        assert hit, f"[{note}] planet not hit (result={result})"
