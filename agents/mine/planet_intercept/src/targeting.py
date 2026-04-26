"""目標価値計算、艦船予算、候補手列挙。

敵惑星: value = production * max(0, rival_eta - my_eta) - ships_to_send
中立惑星: value = production * HOLD_HORIZON - ships_to_send - my_eta * TRAVEL_PENALTY
        (ただし rival が先着する脅威下では敵式に縮退)
"""

import math

from .geometry import (
    fleet_intercept_point,
    intercept_pos,
    route_angle_and_distance,
    route_eta,
    segment_hits_sun,
)
from .utils import Planet, distance, fleet_speed

NEUTRAL_OWNER = -1

HOLD_HORIZON = 20.0
HOLD_HORIZON_BEHIND = 4.0
THREAT_MARGIN = 0.0
TRAVEL_PENALTY = 0.0

BEHIND_THRESHOLD = -0.3
AHEAD_THRESHOLD = 0.3


def ships_budget(target: Planet, my_eta: float = 0.0, already_sent: int = 0) -> int:
    """占領に必要な最小艦船量。

    到着時点のガリソン (駐留 + production * ETA) から既送艦を差し引く。
    """
    garrison_at_arrival = target.ships + int(target.production * my_eta)
    return max(1, garrison_at_arrival - already_sent + 1)


def compute_rival_eta_per_player(
    target: Planet, my_player: int, fleets, planets, angular_velocity: float = 0.0
) -> dict:
    """プレイヤー別の最速 ETA dict を返す。自分と中立は含まない。"""
    from .utils import CENTER

    r_target = math.hypot(target.x - CENTER, target.y - CENTER)
    is_orbital = angular_velocity != 0.0 and (r_target + target.radius < 50)

    per: dict = {}
    for f in fleets:
        if f.owner == my_player:
            continue
        if is_orbital:
            result = intercept_pos(f.x, f.y, max(1, f.ships), target, angular_velocity)
            e = result[2]
        else:
            e = route_eta(f.x, f.y, target.x, target.y, max(1, f.ships))
        if e < per.get(f.owner, math.inf):
            per[f.owner] = e

    for p in planets:
        if p.owner == my_player or p.owner == NEUTRAL_OWNER:
            continue
        if p.id == target.id:
            continue
        ships = max(1, p.ships)
        if is_orbital:
            result = intercept_pos(p.x, p.y, ships, target, angular_velocity)
            e = result[2]
        else:
            e = route_eta(p.x, p.y, target.x, target.y, ships)
        if e < per.get(p.owner, math.inf):
            per[p.owner] = e

    return per


def compute_rival_eta(
    target: Planet, my_player: int, fleets, planets, angular_velocity: float = 0.0
) -> float:
    """自分以外のプレイヤーがターゲットに到達する最速 ETA。"""
    per = compute_rival_eta_per_player(target, my_player, fleets, planets, angular_velocity)
    return min(per.values()) if per else math.inf


def compute_domination(my_total: int, enemy_total: int) -> float:
    """domination スコア: (my - enemy) / (my + enemy)。範囲 [-1, 1]。"""
    total = my_total + enemy_total
    if total == 0:
        return 0.0
    return (my_total - enemy_total) / total


def target_value(
    mine: Planet,
    target_x: float,
    target_y: float,
    production: int,
    rival_eta: float,
    ships_to_send: int,
    my_eta: float,
    target_owner: int = NEUTRAL_OWNER,
    mode: str = "neutral",
) -> float:
    """占領価値。

    中立 (target_owner == NEUTRAL_OWNER):
        rival 未脅威 -> production * horizon - ships - my_eta * TRAVEL_PENALTY
        rival 脅威あり -> production * max(0, rival_eta - my_eta) - ships
    敵惑星 (target_owner != NEUTRAL_OWNER):
        production * max(0, rival_eta - my_eta) - ships
    """
    horizon = HOLD_HORIZON_BEHIND if mode == "behind" else HOLD_HORIZON
    threat = math.isfinite(rival_eta) and (rival_eta - my_eta) <= THREAT_MARGIN
    if target_owner == NEUTRAL_OWNER:
        if not threat:
            return production * horizon - ships_to_send - my_eta * TRAVEL_PENALTY
        return production * max(0.0, rival_eta - my_eta) - ships_to_send
    gain = production * max(0.0, rival_eta - my_eta)
    return gain - ships_to_send


def enumerate_candidates(
    my_planet: Planet,
    all_planets,
    fleets,
    player: int,
    top_n: int = 16,
    angular_velocity: float = 0.0,
    planned: dict | None = None,
    mode: str = "neutral",
):
    """自分以外が所有する惑星をインターセプト位置で距離昇順ソートし上位 top_n 件を返す。

    返り値: list[(target, ships_needed, angle, value)]
    """
    from .utils import CENTER

    targets = [p for p in all_planets if p.owner != player and p.id != my_planet.id]

    def sort_key(t):
        r = math.hypot(t.x - CENTER, t.y - CENTER)
        is_orbital = angular_velocity != 0.0 and (r + t.radius < 50)
        cur_dist = distance(my_planet, t)
        # 静止惑星を先、同グループ内は現在距離でソート
        return (1 if is_orbital else 0, cur_dist)

    targets.sort(key=sort_key)
    targets = targets[:top_n]

    out = []
    for t in targets:
        r = math.hypot(t.x - CENTER, t.y - CENTER)
        is_orbital = angular_velocity != 0.0 and (r + t.radius < 50)
        if is_orbital:
            # 近似 ships で ETA を求め、そのあと正確な ships_needed を再計算
            ships_approx = ships_budget(t)
            ix, iy, my_eta = intercept_pos(
                my_planet.x, my_planet.y, ships_approx, t, angular_velocity
            )
        else:
            ix, iy = t.x, t.y
            ships_approx = ships_budget(t)
            my_eta = route_eta(my_planet.x, my_planet.y, ix, iy, ships_approx)
        if segment_hits_sun(my_planet.x, my_planet.y, ix, iy):
            continue
        angle, _ = route_angle_and_distance(my_planet.x, my_planet.y, ix, iy)
        # my_eta が確定してから正確な ships_needed を計算
        already_sent = planned.get(t.id, 0) if planned else 0
        ships_needed = ships_budget(t, my_eta=my_eta, already_sent=already_sent)
        rival_eta = compute_rival_eta(t, player, fleets, all_planets, angular_velocity)
        value = target_value(
            my_planet, ix, iy, t.production, rival_eta, ships_needed, my_eta,
            target_owner=t.owner, mode=mode,
        )
        out.append((t, ships_needed, angle, value))
    return out


def fleet_heading_to(
    fleet, planet, tolerance_turns: float = 50.0, perp_margin: float = 3.0
) -> bool:
    """fleet が planet に向かっている (forward & 最接近が radius+margin 内) か。"""
    dx = planet.x - fleet.x
    dy = planet.y - fleet.y
    forward = math.cos(fleet.angle) * dx + math.sin(fleet.angle) * dy
    if forward <= 0:
        return False
    perp = abs(-math.sin(fleet.angle) * dx + math.cos(fleet.angle) * dy)
    if perp > planet.radius + perp_margin:
        return False
    eta_turns = forward / fleet_speed(fleet.ships)
    return eta_turns <= tolerance_turns


def classify_defense(mine: Planet, fleets, player: int) -> tuple[str, int]:
    """mine の防衛状況を ("safe"|"threatened"|"doomed", incoming_ships) で返す。

    "doomed": 守れない (mine.ships < incoming)
    "threatened": 守れる (mine.ships >= incoming > 0)
    "safe": 敵フリートなし
    """
    incoming = sum(
        f.ships for f in fleets
        if f.owner != player and fleet_heading_to(f, mine)
    )
    if incoming == 0:
        return "safe", 0
    if mine.ships >= incoming:
        return "threatened", incoming
    return "doomed", incoming


def enumerate_intercept_candidates(
    my_planet: Planet,
    all_planets,
    fleets,
    player: int,
    angular_velocity: float = 0.0,
):
    """自惑星に向かう敵フリートへの迎撃候補。

    返り値は enumerate_candidates と同じ (target, ships_needed, angle, value) 形式。
    target には守る自惑星 (Planet) を入れる。value は production * HOLD_HORIZON - ships_needed
    で attack 側と同スケール。
    """
    out = []
    for defended in all_planets:
        if defended.owner != player:
            continue
        for f in fleets:
            if f.owner == player:
                continue
            if not fleet_heading_to(f, defended):
                continue
            ships_needed = max(1, f.ships + 1)
            result = fleet_intercept_point(my_planet.x, my_planet.y, ships_needed, f)
            if result is None:
                continue
            ix, iy, my_eta = result
            fleet_eta = math.hypot(f.x - defended.x, f.y - defended.y) / fleet_speed(f.ships)
            if my_eta > fleet_eta:
                continue
            if segment_hits_sun(my_planet.x, my_planet.y, ix, iy):
                continue
            angle, _ = route_angle_and_distance(my_planet.x, my_planet.y, ix, iy)
            save_value = defended.production * HOLD_HORIZON
            value = save_value - ships_needed
            out.append((defended, ships_needed, angle, value))
    return out


def select_move(my_planet: Planet, candidates, reserve: int = 0, my_planet_count: int = 1):
    """value 最大の発射可能候補を返す。なければ None。"""
    best = None
    best_value = -math.inf
    for target, ships_needed, angle, value in candidates:
        if my_planet.ships - reserve < ships_needed:
            continue
        if value > best_value:
            best_value = value
            best = (angle, ships_needed)
    return best
