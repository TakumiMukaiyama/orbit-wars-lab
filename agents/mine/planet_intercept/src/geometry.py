"""太陽回避ルーティングと幾何ユーティリティ。

Orbit Wars の太陽衝突判定 (orbit_wars.py L541) は、フリートの旧位置 - 新位置
セグメントと太陽中心 (50, 50) の距離が SUN_RADIUS (=10) を下回った時に消滅する。
Phase 1a では 1 回の発射 = 1 つの angle で太陽を避けて目標にできるだけ近づく
近似ルーティングを行う。
"""

import math

from .utils import BOARD_SIZE, CENTER, SUN_RADIUS, fleet_speed

_SUN = (CENTER, CENTER)
_MARGIN = 0.5
_TANGENT_EXTRA = 1.5


def _point_to_segment_distance(p, v, w):
    """orbit_wars.py L34 と同じ線分 - 点距離。"""
    l2 = (v[0] - w[0]) ** 2 + (v[1] - w[1]) ** 2
    if l2 == 0.0:
        return math.hypot(p[0] - v[0], p[1] - v[1])
    t = max(
        0.0,
        min(
            1.0,
            ((p[0] - v[0]) * (w[0] - v[0]) + (p[1] - v[1]) * (w[1] - v[1])) / l2,
        ),
    )
    px = v[0] + t * (w[0] - v[0])
    py = v[1] + t * (w[1] - v[1])
    return math.hypot(p[0] - px, p[1] - py)


def segment_hits_sun(x1, y1, x2, y2, margin=_MARGIN):
    """線分 (x1,y1)-(x2,y2) が太陽 (半径 SUN_RADIUS + margin) と交わるか。"""
    return _point_to_segment_distance(_SUN, (x1, y1), (x2, y2)) < SUN_RADIUS + margin


def _normalize_angle(a):
    while a > math.pi:
        a -= 2 * math.pi
    while a < -math.pi:
        a += 2 * math.pi
    return a


def tangent_waypoint(x1, y1, x2, y2, margin=_MARGIN):
    """太陽迂回用の接点 (waypoint) を返す。線分が太陽を通らなければ None。

    src から太陽中心への距離 d、迂回半径 R = SUN_RADIUS + margin として、
    接線角 = phi ± asin(R / d)。dst に近い側を選び、接点 = src から接線方向に
    tangent_length = sqrt(d^2 - R^2) 進んだ点。
    """
    if not segment_hits_sun(x1, y1, x2, y2, margin):
        return None

    cx = CENTER - x1
    cy = CENTER - y1
    d = math.hypot(cx, cy)
    r = SUN_RADIUS + margin + _TANGENT_EXTRA
    if d <= r:
        return None

    phi = math.atan2(cy, cx)
    alpha = math.asin(r / d)
    theta = math.atan2(y2 - y1, x2 - x1)

    cand_a = phi + alpha
    cand_b = phi - alpha
    diff_a = abs(_normalize_angle(cand_a - theta))
    diff_b = abs(_normalize_angle(cand_b - theta))
    tangent_angle = cand_a if diff_a <= diff_b else cand_b

    tangent_length = math.sqrt(max(0.0, d * d - r * r))
    wx = x1 + tangent_length * math.cos(tangent_angle)
    wy = y1 + tangent_length * math.sin(tangent_angle)
    return (wx, wy)


def route_angle_and_distance(src_x, src_y, dst_x, dst_y, margin=_MARGIN):
    """発射角と総経路長を返す。

    フリートは角度固定・直進のため、Phase 1a では "太陽を避ける接線方向に発射し、
    接点まで進んだあと dst 方向へ向かう" という 2 セグメント近似で距離を見積もる。
    実際の発射角は接線角 1 つ。到達するかはゲーム側の判定に委ねる。
    """
    waypoint = tangent_waypoint(src_x, src_y, dst_x, dst_y, margin)
    if waypoint is None:
        dx = dst_x - src_x
        dy = dst_y - src_y
        return math.atan2(dy, dx), math.hypot(dx, dy)

    wx, wy = waypoint
    angle = math.atan2(wy - src_y, wx - src_x)
    leg1 = math.hypot(wx - src_x, wy - src_y)
    leg2 = math.hypot(dst_x - wx, dst_y - wy)
    return angle, leg1 + leg2


def route_eta(src_x, src_y, dst_x, dst_y, ships, margin=_MARGIN):
    """経路長 / フリート速度 によるターン数近似。"""
    _, dist = route_angle_and_distance(src_x, src_y, dst_x, dst_y, margin)
    return dist / fleet_speed(ships)


def in_bounds(x, y):
    return 0.0 <= x <= BOARD_SIZE and 0.0 <= y <= BOARD_SIZE


def fleet_intercept_point(src_x, src_y, src_ships, fleet):
    """src から最短 ETA で fleet の直進経路上に到達する点と ETA を返す。

    フリートは固定角度・直進なので
        P(t) = (fleet.x + vfx*t, fleet.y + vfy*t)
    と src から P(t) までの距離が my_speed*t になる正の最小 t を二次方程式で解く。
    到達解が無ければ None。太陽回避は呼び出し側で route_angle_and_distance が処理。
    """
    fs = fleet_speed(fleet.ships)
    vfx = math.cos(fleet.angle) * fs
    vfy = math.sin(fleet.angle) * fs
    my_speed = fleet_speed(src_ships)

    ex = fleet.x - src_x
    ey = fleet.y - src_y

    a = vfx * vfx + vfy * vfy - my_speed * my_speed
    b = 2.0 * (ex * vfx + ey * vfy)
    c = ex * ex + ey * ey

    if abs(a) < 1e-9:
        if abs(b) < 1e-9:
            return None
        t = -c / b
        if t <= 0:
            return None
    else:
        disc = b * b - 4.0 * a * c
        if disc < 0:
            return None
        sq = math.sqrt(disc)
        t1 = (-b - sq) / (2.0 * a)
        t2 = (-b + sq) / (2.0 * a)
        roots = [r for r in (t1, t2) if r > 0]
        if not roots:
            return None
        t = min(roots)

    ix = fleet.x + vfx * t
    iy = fleet.y + vfy * t
    return ix, iy, t


def _iterate_orbital_intercept(
    src_x, src_y, ships, planet, angular_velocity, initial_t, max_iter=30
):
    """初期 t から軌道惑星会合点の固定点反復を回し (px, py, t, converged) を返す。

    接線速度と fleet_speed が近いときは反復が発散することがあるので、
    収束フラグを呼び出し側に渡して選別させる。
    """
    r = math.hypot(planet.x - CENTER, planet.y - CENTER)
    base_angle = math.atan2(planet.y - CENTER, planet.x - CENTER)

    t = initial_t
    px = planet.x
    py = planet.y
    for _ in range(max_iter):
        future_angle = base_angle + angular_velocity * t
        px = CENTER + r * math.cos(future_angle)
        py = CENTER + r * math.sin(future_angle)
        t_new = route_eta(src_x, src_y, px, py, ships)
        if abs(t_new - t) < 0.5:
            return px, py, t_new, True
        t = t_new
    return px, py, t, False


def intercept_pos(src_x, src_y, ships, planet, angular_velocity, max_iter=30):
    """軌道惑星のインターセプト位置 (x, y) と ETA を返す。

    前方会合 (現在位置を初期値) と後方会合 (半周分遅らせた初期値) の 2 解を
    反復で求め、**両方とも収束した** 場合だけ後方会合を採用候補に入れる。
    収束しなかった解は発散しているのでそのままでは使えない。
    静止惑星は angular_velocity=0 なので現在位置がそのまま返る。
    """
    if angular_velocity == 0.0:
        return planet.x, planet.y, route_eta(src_x, src_y, planet.x, planet.y, ships)

    t0 = route_eta(src_x, src_y, planet.x, planet.y, ships)
    forward = _iterate_orbital_intercept(
        src_x, src_y, ships, planet, angular_velocity, t0, max_iter
    )

    period = 2.0 * math.pi / abs(angular_velocity)
    t0_back = t0 + period / 2.0
    backward = _iterate_orbital_intercept(
        src_x, src_y, ships, planet, angular_velocity, t0_back, max_iter
    )

    # 収束した解のうち最小 ETA を採用。収束解がなければ forward (従来の挙動を維持)。
    converged = [c for c in (forward, backward) if c[3] and c[2] > 0]
    if not converged:
        px, py, t, _ = forward
        return px, py, t
    best = min(converged, key=lambda c: c[2])
    px, py, t, _ = best
    return px, py, t
