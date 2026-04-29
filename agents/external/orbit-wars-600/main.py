"""
Orbit Wars - Orbital Supremacy Agent
Key improvements over baseline:
  1. Intercept targeting for orbiting planets
  2. Production-value ROI scoring
  3. Transit-adjusted garrison estimates
  4. Sun path avoidance with angle rerouting
  5. Defence buffer against incoming threats
  6. No double-targeting
  7. Endgame cutoff
  8. Comet discounting
"""
import math

_SX, _SY = 50.0, 50.0
_SR      = 10.0
_MAX_SPD = 6.0
_L1000   = math.log(1000)
_TURNS   = [0]


def _spd(n):
    return 1.0 + (_MAX_SPD - 1.0) * (math.log(max(1, n)) / _L1000) ** 1.5


def _seg_dist(ax, ay, bx, by, px, py):
    dx, dy = bx - ax, by - ay
    s2 = dx * dx + dy * dy
    if s2 < 1e-12:
        return math.hypot(ax - px, ay - py)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / s2))
    return math.hypot(ax + t * dx - px, ay + t * dy - py)


def _sun_hit(x1, y1, x2, y2):
    return _seg_dist(x1, y1, x2, y2, _SX, _SY) < _SR + 0.5


def _is_orbiting(planet, init_p):
    return math.hypot(init_p[2] - _SX, init_p[3] - _SY) + planet[4] < 50.0


def _future_xy(planet_now, init_planet, av, dt):
    if not _is_orbiting(planet_now, init_planet):
        return planet_now[2], planet_now[3]
    r = math.hypot(init_planet[2] - _SX, init_planet[3] - _SY)
    a = math.atan2(planet_now[3] - _SY, planet_now[2] - _SX) + av * dt
    return _SX + r * math.cos(a), _SY + r * math.sin(a)


def _intercept(fx, fy, tgt, itgt, av, ships, iters=12):
    tx, ty = tgt[2], tgt[3]
    spd = _spd(ships)
    t = 0.0
    for _ in range(iters):
        d = math.hypot(fx - tx, fy - ty)
        t = d / spd
        tx, ty = _future_xy(tgt, itgt, av, t)
    return math.atan2(ty - fy, tx - fx), t, tx, ty


def _reroute_angle(fx, fy, base_angle, sign):
    for deg in range(10, 80, 5):
        a = base_angle + sign * math.radians(deg)
        ex, ey = fx + 90 * math.cos(a), fy + 90 * math.sin(a)
        if not _sun_hit(fx, fy, ex, ey):
            return a
    return None


def _safe_angle(fx, fy, tx, ty, base_angle):
    if not _sun_hit(fx, fy, tx, ty):
        return base_angle, False
    a = _reroute_angle(fx, fy, base_angle, 1) or _reroute_angle(fx, fy, base_angle, -1)
    return a, True


def _ships_incoming(planet, fleets, mode, player, tol=0.25):
    px, py, total = planet[2], planet[3], 0
    for f in fleets:
        if mode == 'enemy'    and (f[1] == player or f[1] < 0):
            continue
        if mode == 'friendly' and f[1] != player:
            continue
        da   = math.atan2(py - f[3], px - f[2])
        diff = abs((da - f[4] + math.pi) % (2 * math.pi) - math.pi)
        if diff < tol:
            total += f[6]
    return total


def agent(obs):
    _TURNS[0] += 1
    step = _TURNS[0]

    if isinstance(obs, dict):
        player    = obs.get('player', 0)
        av        = obs.get('angular_velocity', 0.03)
        planets   = obs.get('planets', [])
        init_p    = obs.get('initial_planets', [])
        fleets    = obs.get('fleets', [])
        comet_ids = set(obs.get('comet_planet_ids', []))
    else:
        player    = obs.player
        av        = obs.angular_velocity
        planets   = obs.planets
        init_p    = getattr(obs, 'initial_planets', [])
        fleets    = obs.fleets
        comet_ids = set(getattr(obs, 'comet_planet_ids', []))

    remaining = max(1, 500 - step)
    imap = {p[0]: p for p in init_p} if init_p else {}

    mine_list = [p for p in planets if p[1] == player]
    targets   = [p for p in planets if p[1] != player]

    if not mine_list or not targets:
        return []

    moves     = []
    committed = {p[0]: 0 for p in mine_list}
    targeted  = set()

    for mine in mine_list:
        mid, _, mx, my_, mr, mships, mprod = mine

        e_in   = _ships_incoming(mine, fleets, 'enemy',    player)
        f_in   = _ships_incoming(mine, fleets, 'friendly', player)
        threat = max(0, e_in - f_in)
        buffer = max(mprod * 4 + 3, int(threat * 1.1) + mprod * 2)
        avail  = mships - committed[mid] - buffer

        if avail < 2:
            continue

        best_score, best_move = -1e9, None

        for tgt in targets:
            tid, towner, tx, ty_, tr, tships, tprod = tgt

            if tid in targeted:
                continue
            if tid in comet_ids and math.hypot(mx - tx, my_ - ty_) > 20:
                continue

            itgt = imap.get(tid, tgt)
            angle, travel_t, itx, ity = _intercept(mx, my_, tgt, itgt, av, avail)

            angle, rerouted = _safe_angle(mx, my_, itx, ity, angle)
            if angle is None:
                continue
            if rerouted:
                travel_t *= 1.35

            needed = int(tships + tprod * travel_t) + 1
            if avail < needed:
                continue
            if travel_t >= remaining * 0.9:
                continue

            time_left = max(1.0, remaining - travel_t)
            value     = tprod * time_left
            if towner != -1:
                value *= 1.6
            if tid in comet_ids:
                value *= 0.3

            score = value / (needed + 1)

            if score > best_score:
                best_score = score
                best_move  = (mid, angle, needed, tid)

        if best_move and best_score > 0:
            mid_, angle_, n_, tid_ = best_move
            moves.append([mid_, angle_, n_])
            committed[mid] += n_
            targeted.add(tid_)

    return moves
