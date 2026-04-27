"""目標価値計算、艦船予算、候補手列挙。

敵惑星: value = production * max(0, rival_eta - my_eta) - ships_to_send
中立惑星: value = production * HOLD_HORIZON - ships_to_send - my_eta * TRAVEL_PENALTY
        (ただし rival が先着する脅威下では敵式に縮退)
"""

import math
from dataclasses import dataclass

from .geometry import (
    fleet_intercept_point,
    intercept_pos,
    route_angle_and_distance,
    route_eta,
    segment_hits_sun,
)
from .utils import Planet, distance, fleet_speed
from .world import (
    PlanetState,
    estimate_snipe_outcome,
    first_turn_lost,
    ships_needed_to_capture_at,
    state_at,
)

NEUTRAL_OWNER = -1

HOLD_HORIZON = 20.0
HOLD_HORIZON_BEHIND = 4.0
THREAT_MARGIN = 0.0
TRAVEL_PENALTY = 0.15
ASSET_HORIZON = 120.0
ORBITAL_OPENING_TURNS = 160
INNER_ORBITAL_RADIUS = 34.0
INNER_ORBITAL_BONUS = 55.0
STATIC_HIGH_PROD_BONUS = 30.0

# P5: 中央性ボーナス — 盤面中心に近いほど加点 (右寄り閉塞の回避)
CENTRAL_REF_RADIUS = 35.0  # この距離でボーナス 0
CENTRAL_BONUS_MAX = 40.0  # 中心 (r=0) での最大加点
CENTRAL_OPENING_TURNS = 200  # 序盤〜中盤のみ適用 (後半は不要)

# P2: 過拡張ペナルティ — 勝敗拮抗時に広げすぎた場合の中立 value 減衰
OVEREXTEND_MIN_PLANETS = 6  # これ未満なら抑制しない (序盤は広げる)
OVEREXTEND_DOM_WINDOW = 0.15  # |dom| < これ = 拮抗
OVEREXTEND_DECAY_PER_PLANET = 0.08  # 惑星 1 個超過ごとに 8% 減衰
OVEREXTEND_FLOOR = 0.4  # factor の下限

# P3: 集中攻撃 — 既に別惑星が planned した target への追加加点
FOCUS_BONUS_PER_PLANNED_SHIP = 0.5  # planned 1 ship ごとに value +0.5

BEHIND_THRESHOLD = -0.3
AHEAD_THRESHOLD = 0.3

SNIPE_MIN_HOLD = 5  # hold_turns がこれ未満のとき SNIPE_HOLD_PENALTY を加算
SNIPE_HOLD_PENALTY = 30.0  # 短命 snipe に対するペナルティ

ETA_SYNC_TOLERANCE = 8  # max ETA difference (turns) between swarm sources (P3 緩和: 3→8)


@dataclass
class SwarmMission:
    target: "Planet"
    src_a: "Planet"
    ships_a: int
    angle_a: float
    eta_a: float
    src_b: "Planet"
    ships_b: int
    angle_b: float
    eta_b: float
    value: float


def _fleet_forward_distance(fleet, planet) -> float:
    dx = planet.x - fleet.x
    dy = planet.y - fleet.y
    return math.cos(fleet.angle) * dx + math.sin(fleet.angle) * dy


def build_planned_commitments(planets, fleets, player: int) -> dict[int, int]:
    """既に飛んでいる自フリートが到達しそうな中立惑星ごとの ships 合計。

    フリートは直線上で最初に衝突した惑星で消えるため、進行方向上で最も近い
    中立惑星だけをコミット済みとして扱う。敵惑星は ownership と production による
    必要艦数の変動が大きいため、保守的に差し引き対象から外す。
    """
    targets = [p for p in planets if p.owner == NEUTRAL_OWNER]
    planned: dict[int, int] = {}
    for f in fleets:
        if f.owner != player:
            continue
        candidates = [
            t
            for t in targets
            if fleet_heading_to(f, t, tolerance_turns=500.0)
            and not segment_hits_sun(f.x, f.y, t.x, t.y)
        ]
        if not candidates:
            continue
        target = min(candidates, key=lambda t: _fleet_forward_distance(f, t))
        planned[target.id] = planned.get(target.id, 0) + f.ships
    return planned


def ships_budget(target: Planet, my_eta: float = 0.0, already_sent: int = 0) -> int:
    """占領に必要な最小艦船量。

    所有惑星だけ到着までの production 増分を見込む。中立惑星は生産しない。
    既送艦で足りている場合は 0 を返し、呼び出し側で候補から除外する。
    """
    growth = 0 if target.owner == NEUTRAL_OWNER else int(target.production * my_eta)
    garrison_at_arrival = target.ships + growth
    return max(0, garrison_at_arrival - already_sent + 1)


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


def _overextend_factor(my_planet_count: int, domination: float) -> float:
    """P2: 過拡張ペナルティの乗数 (中立獲得の value 減衰)。

    条件: 惑星数 >= OVEREXTEND_MIN_PLANETS かつ dom が拮抗域 (|dom| < WINDOW) のとき減衰。
    勝敗が大差ついている場面ではこのペナルティは適用しない (勝ち確なら広げて問題ないし、
    負け確なら一点突破に賭けるため中立価値はそのまま高い方が良い)。
    """
    if my_planet_count < OVEREXTEND_MIN_PLANETS:
        return 1.0
    if abs(domination) > OVEREXTEND_DOM_WINDOW:
        return 1.0
    excess = my_planet_count - OVEREXTEND_MIN_PLANETS
    return max(OVEREXTEND_FLOOR, 1.0 - excess * OVEREXTEND_DECAY_PER_PLANET)


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
    remaining_turns: int | None = None,
    is_orbital: bool = False,
    orbital_radius: float | None = None,
    my_planet_count: int = 0,
    domination: float = 0.0,
    focus_planned_ships: int = 0,
) -> float:
    """占領価値。

    中立 (target_owner == NEUTRAL_OWNER):
        rival 未脅威 -> production * horizon - ships - my_eta * TRAVEL_PENALTY
        rival 脅威あり -> production * max(0, rival_eta - my_eta) - ships
    敵惑星 (target_owner != NEUTRAL_OWNER):
        production * max(0, rival_eta - my_eta) - ships

    P2: 中立 not-threat ブランチに overextend_factor を乗算。
    P3: focus_planned_ships > 0 のとき FOCUS_BONUS_PER_PLANNED_SHIP * ships を加算。
    """
    if remaining_turns is None:
        asset_horizon = HOLD_HORIZON
    else:
        asset_horizon = min(ASSET_HORIZON, max(HOLD_HORIZON, float(remaining_turns)))
    horizon = HOLD_HORIZON_BEHIND if mode == "behind" else asset_horizon

    threat = math.isfinite(rival_eta) and (rival_eta - my_eta) <= THREAT_MARGIN
    eta_penalty = my_eta * TRAVEL_PENALTY
    opening_bonus = 0.0
    elapsed_turns = 500 - remaining_turns if remaining_turns is not None else 500
    if is_orbital and orbital_radius is not None and elapsed_turns <= ORBITAL_OPENING_TURNS:
        if orbital_radius <= INNER_ORBITAL_RADIUS:
            opening_bonus = INNER_ORBITAL_BONUS + production * 8.0
    elif not is_orbital and production >= 4:
        opening_bonus = STATIC_HIGH_PROD_BONUS

    # P5: 中央性ボーナス — 盤面中心に近い惑星ほど加点、序盤のみ有効
    central_bonus = 0.0
    if target_owner == NEUTRAL_OWNER and elapsed_turns <= CENTRAL_OPENING_TURNS:
        r_target = math.hypot(target_x - 50.0, target_y - 50.0)
        if r_target < CENTRAL_REF_RADIUS:
            central_bonus = CENTRAL_BONUS_MAX * (1.0 - r_target / CENTRAL_REF_RADIUS)

    # P3: 集中攻撃ボーナス — 既に別 source が planned した target は追加加点
    focus_bonus = FOCUS_BONUS_PER_PLANNED_SHIP * max(0, int(focus_planned_ships))

    if target_owner == NEUTRAL_OWNER:
        if not threat:
            # P2: 過拡張ペナルティ (中立 not-threat のみ)
            factor = _overextend_factor(my_planet_count, domination)
            base = production * horizon + opening_bonus + central_bonus
            return base * factor + focus_bonus - ships_to_send - eta_penalty
        return production * max(0.0, rival_eta - my_eta) - ships_to_send + focus_bonus
    if threat:
        gain = 0.0
    elif math.isfinite(rival_eta):
        gain = production * min(asset_horizon, max(0.0, rival_eta - my_eta))
    else:
        gain = production * asset_horizon
    return gain + opening_bonus + focus_bonus - ships_to_send - eta_penalty


def enumerate_candidates(
    my_planet: Planet,
    all_planets,
    fleets,
    player: int,
    top_n: int = 16,
    angular_velocity: float = 0.0,
    planned: dict | None = None,
    mode: str = "neutral",
    remaining_turns: int | None = None,
    timelines: dict[int, list[PlanetState]] | None = None,
    my_planet_count: int = 0,
    domination: float = 0.0,
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
        if remaining_turns is not None:
            elapsed_turns = 500 - remaining_turns
            inner_bonus = 0.0
            if is_orbital and elapsed_turns <= ORBITAL_OPENING_TURNS and r <= INNER_ORBITAL_RADIUS:
                inner_bonus = 120.0
            static_bonus = 40.0 if (not is_orbital and t.production >= 4) else 0.0
            # P5: 静止中央惑星を top_n に残りやすくする
            central_bonus_sort = 0.0
            if (
                t.owner == NEUTRAL_OWNER
                and not is_orbital
                and elapsed_turns <= CENTRAL_OPENING_TURNS
                and r < CENTRAL_REF_RADIUS
            ):
                central_bonus_sort = CENTRAL_BONUS_MAX * (1.0 - r / CENTRAL_REF_RADIUS)
            priority = (
                t.production * 25.0 + inner_bonus + static_bonus + central_bonus_sort - cur_dist
            )
            return (-priority, cur_dist)
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
        if remaining_turns is not None and my_eta > remaining_turns:
            continue
        # my_eta が確定してから正確な ships_needed を計算
        already_sent = planned.get(t.id, 0) if planned else 0
        if timelines and t.id in timelines:
            base_needed = ships_needed_to_capture_at(
                t,
                timelines[t.id],
                player,
                int(math.ceil(my_eta)),
            )
            ships_needed = max(0, base_needed - already_sent)
        else:
            ships_needed = ships_budget(t, my_eta=my_eta, already_sent=already_sent)
        if ships_needed <= 0:
            continue
        # P0: 実 ships で会合点を再計算 (ships_approx との乖離で狙いが外れる問題の修正)
        if is_orbital and ships_needed != ships_approx:
            ix, iy, my_eta = intercept_pos(
                my_planet.x, my_planet.y, ships_needed, t, angular_velocity
            )
            if segment_hits_sun(my_planet.x, my_planet.y, ix, iy):
                continue
            if remaining_turns is not None and my_eta > remaining_turns:
                continue
            if timelines and t.id in timelines:
                base_needed = ships_needed_to_capture_at(
                    t,
                    timelines[t.id],
                    player,
                    int(math.ceil(my_eta)),
                )
                ships_needed = max(0, base_needed - already_sent)
            else:
                ships_needed = ships_budget(t, my_eta=my_eta, already_sent=already_sent)
            if ships_needed <= 0:
                continue
        angle, _ = route_angle_and_distance(my_planet.x, my_planet.y, ix, iy)
        rival_eta = compute_rival_eta(t, player, fleets, all_planets, angular_velocity)
        focus_planned = int(planned.get(t.id, 0)) if planned else 0
        value = target_value(
            my_planet,
            ix,
            iy,
            t.production,
            rival_eta,
            ships_needed,
            my_eta,
            target_owner=t.owner,
            mode=mode,
            remaining_turns=remaining_turns,
            is_orbital=is_orbital,
            orbital_radius=r,
            my_planet_count=my_planet_count,
            domination=domination,
            focus_planned_ships=focus_planned,
        )
        out.append((t, ships_needed, angle, value, float(my_eta)))
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


def classify_defense(
    mine: Planet,
    fleets,
    player: int,
    timeline: list[PlanetState] | None = None,
) -> tuple[str, int]:
    """mine の防衛状況を ("safe"|"threatened"|"doomed", reserve) で返す。

    timeline があるとき:
      first_turn_lost が None -> "safe" (自軍 in-flight で救われるケース含む)
      そうでなければ fall turn 時点の state.ships を敵側兵力とみなし、
        mine.ships 未満なら "doomed"、それ以外は "threatened"。
    timeline=None のときは旧 fleet_heading_to ベース判定 (後方互換)。
    """
    if timeline is not None:
        fall_turn = first_turn_lost(mine, timeline, player)
        if fall_turn is None:
            return "safe", 0
        state = state_at(timeline, fall_turn)
        enemy_ships = int(state.ships) if state is not None else int(mine.ships) + 1
        reserve = max(0, enemy_ships)
        if mine.ships < reserve:
            return "doomed", reserve
        return "threatened", reserve

    incoming = sum(
        f.ships
        for f in fleets
        if f.owner != player and fleet_heading_to(f, mine, tolerance_turns=15.0)
    )
    if incoming == 0:
        return "safe", 0
    if mine.ships >= incoming:
        return "threatened", incoming
    return "doomed", incoming


def enumerate_support_candidates(
    my_planet: Planet,
    all_planets,
    player: int,
    timelines: dict[int, list[PlanetState]] | None = None,
    planned: dict | None = None,
    remaining_turns: int | None = None,
) -> list:
    """threatened / doomed な他の自惑星への着地補強候補。

    intercept (空中迎撃) とは別の枠。timeline 上 fall_turn がある自惑星に対して、
    my_eta <= fall_turn 内に到達でき、state.ships + 1 の deficit を埋められる
    ships を送る。value = production * HOLD_HORIZON - ships - eta*TRAVEL_PENALTY。
    """
    if timelines is None:
        return []
    if planned is None:
        planned = {}

    out = []
    for ally in all_planets:
        if ally.owner != player:
            continue
        if ally.id == my_planet.id:
            continue
        timeline = timelines.get(ally.id)
        if timeline is None:
            continue
        fall_turn = first_turn_lost(ally, timeline, player)
        if fall_turn is None:
            continue
        state = state_at(timeline, fall_turn)
        if state is None or state.owner == player:
            continue
        # ally 静止前提で route_eta。軌道惑星への support は現状同様に
        # 現在位置狙いで良い (fall_turn は小さく、軌道移動は無視できる)。
        my_eta = route_eta(my_planet.x, my_planet.y, ally.x, ally.y, max(1, my_planet.ships))
        if my_eta > fall_turn:
            continue
        if segment_hits_sun(my_planet.x, my_planet.y, ally.x, ally.y):
            continue
        if remaining_turns is not None and my_eta > remaining_turns:
            continue
        already_sent = planned.get(ally.id, 0)
        deficit = max(1, int(state.ships) + 1)
        ships_needed = max(0, deficit - already_sent)
        if ships_needed <= 0:
            continue
        angle, _ = route_angle_and_distance(my_planet.x, my_planet.y, ally.x, ally.y)
        value = ally.production * HOLD_HORIZON - ships_needed - my_eta * TRAVEL_PENALTY
        if value <= 0:
            continue
        out.append((ally, ships_needed, angle, value, float(my_eta)))
    return out


def enumerate_intercept_candidates(
    my_planet: Planet,
    all_planets,
    fleets,
    player: int,
    angular_velocity: float = 0.0,
    timelines: dict[int, list[PlanetState]] | None = None,
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
        timeline = timelines.get(defended.id) if timelines else None
        fall_turn: int | None = None
        deficit: int | None = None
        if timeline is not None:
            fall_turn = first_turn_lost(defended, timeline, player)
            if fall_turn is None:
                continue
            state = state_at(timeline, fall_turn)
            if state is not None and state.owner != player:
                deficit = max(1, int(state.ships) + 1)
        for f in fleets:
            if f.owner == player:
                continue
            if not fleet_heading_to(f, defended):
                continue
            # timeline 駆動なら fall turn 時点の敵残存 + 1、なければ旧フォールバック
            ships_needed = deficit if deficit is not None else max(1, f.ships + 1)
            result = fleet_intercept_point(my_planet.x, my_planet.y, ships_needed, f)
            if result is None:
                continue
            ix, iy, my_eta = result
            fleet_eta = math.hypot(f.x - defended.x, f.y - defended.y) / fleet_speed(f.ships)
            if my_eta > fleet_eta:
                continue
            if fall_turn is not None and my_eta > fall_turn:
                continue
            if segment_hits_sun(my_planet.x, my_planet.y, ix, iy):
                continue
            angle, _ = route_angle_and_distance(my_planet.x, my_planet.y, ix, iy)
            save_value = defended.production * HOLD_HORIZON
            value = save_value - ships_needed - my_eta * TRAVEL_PENALTY
            out.append((defended, ships_needed, angle, value, float(my_eta)))
    return out


def enumerate_snipe_candidates(
    my_planet: Planet,
    all_planets,
    fleets,
    player: int,
    angular_velocity: float = 0.0,
    planned: dict | None = None,
    remaining_turns: int | None = None,
    timelines: dict | None = None,
    ledger: dict | None = None,
    horizon: int = 80,
) -> list:
    """中立惑星への snipe 候補を列挙する。

    条件: 中立 + ledger に enemy arrival あり + 自 eta < 最速 enemy eta
    value = production * hold_turns - ships_needed - my_eta * TRAVEL_PENALTY
            - (SNIPE_HOLD_PENALTY if hold_turns < SNIPE_MIN_HOLD else 0)
    """
    from .utils import CENTER

    if planned is None:
        planned = {}
    if ledger is None:
        ledger = {}

    out = []
    for target in all_planets:
        if target.owner != NEUTRAL_OWNER:
            continue
        if target.id == my_planet.id:
            continue
        enemy_arrivals = [a for a in ledger.get(target.id, []) if a.owner != player]
        if not enemy_arrivals:
            continue
        enemy_min_eta = min(a.eta for a in enemy_arrivals)

        r = math.hypot(target.x - CENTER, target.y - CENTER)
        is_orbital = angular_velocity != 0.0 and (r + target.radius < 50)
        if is_orbital:
            ships_approx = max(1, my_planet.ships // 2)
            ix, iy, my_eta = intercept_pos(
                my_planet.x, my_planet.y, ships_approx, target, angular_velocity
            )
        else:
            ix, iy = target.x, target.y
            ships_approx = max(1, my_planet.ships // 2)
            my_eta = route_eta(my_planet.x, my_planet.y, ix, iy, ships_approx)

        if my_eta >= enemy_min_eta:
            continue
        if segment_hits_sun(my_planet.x, my_planet.y, ix, iy):
            continue
        if remaining_turns is not None and my_eta > remaining_turns:
            continue

        already_sent = planned.get(target.id, 0)
        if timelines and target.id in timelines:
            needed = ships_needed_to_capture_at(
                target, timelines[target.id], player, int(math.ceil(my_eta))
            )
        else:
            needed = ships_budget(target, my_eta=my_eta)
        needed = max(0, needed - already_sent)
        if needed <= 0:
            continue
        # P0: 実 ships で会合点を再計算
        if is_orbital and needed != ships_approx:
            ix, iy, my_eta = intercept_pos(
                my_planet.x, my_planet.y, needed, target, angular_velocity
            )
            if my_eta >= enemy_min_eta:
                continue
            if segment_hits_sun(my_planet.x, my_planet.y, ix, iy):
                continue
            if remaining_turns is not None and my_eta > remaining_turns:
                continue
            if timelines and target.id in timelines:
                needed = ships_needed_to_capture_at(
                    target, timelines[target.id], player, int(math.ceil(my_eta))
                )
            else:
                needed = ships_budget(target, my_eta=my_eta)
            needed = max(0, needed - already_sent)
            if needed <= 0:
                continue
        angle, _ = route_angle_and_distance(my_planet.x, my_planet.y, ix, iy)

        timeline = timelines.get(target.id) if timelines else None
        if timeline is not None:
            hold_turns, _ = estimate_snipe_outcome(
                target,
                timeline,
                player,
                my_eta=int(math.ceil(my_eta)),
                ships_after_capture=needed,
                horizon=horizon,
            )
        else:
            hold_turns = max(0, horizon - int(my_eta))

        if hold_turns == 0:
            continue

        penalty = SNIPE_HOLD_PENALTY if hold_turns < SNIPE_MIN_HOLD else 0.0
        value = target.production * hold_turns - needed - my_eta * TRAVEL_PENALTY - penalty
        if value <= 0:
            continue

        out.append((target, needed, angle, value, float(my_eta)))
    return out


def enumerate_swarm_candidates(
    my_planets,
    all_planets,
    fleets,
    player: int,
    angular_velocity: float = 0.0,
    planned: dict | None = None,
    fired_sources: set | None = None,
    defense_status: dict | None = None,
    mode: str = "neutral",
    remaining_turns: int | None = None,
    timelines: dict | None = None,
    eta_sync_tolerance: int = ETA_SYNC_TOLERANCE,
) -> list[SwarmMission]:
    """2 自惑星から同一ターゲットへの協調攻撃候補を列挙する。

    各ソース単独では占領不能だが合算なら可能な target を対象に、
    ETA 差 <= eta_sync_tolerance の source ペアを探して SwarmMission を返す。
    Phase 1: 2-source のみ。
    """
    from .utils import CENTER

    if planned is None:
        planned = {}
    if fired_sources is None:
        fired_sources = set()

    available_sources = [p for p in my_planets if p.id not in fired_sources]
    if len(available_sources) < 2:
        return []

    targets = [p for p in all_planets if p.owner != player]
    missions: list[SwarmMission] = []

    for target in targets:
        if planned.get(target.id, 0) > 0:
            continue

        r = math.hypot(target.x - CENTER, target.y - CENTER)
        is_orbital = angular_velocity != 0.0 and (r + target.radius < 50)

        src_info: list[tuple] = []
        for src in available_sources:
            ships_approx = max(1, src.ships // 2)
            if is_orbital:
                ix, iy, eta = intercept_pos(src.x, src.y, ships_approx, target, angular_velocity)
            else:
                ix, iy = target.x, target.y
                eta = route_eta(src.x, src.y, ix, iy, ships_approx)
            if segment_hits_sun(src.x, src.y, ix, iy):
                continue
            if remaining_turns is not None and eta > remaining_turns:
                continue
            angle, _ = route_angle_and_distance(src.x, src.y, ix, iy)
            src_info.append((src, eta, angle))

        src_info.sort(key=lambda x: x[1])

        rival_eta = compute_rival_eta(target, player, fleets, all_planets, angular_velocity)

        for i in range(len(src_info)):
            src_a, eta_a, angle_a = src_info[i]
            for j in range(i + 1, len(src_info)):
                src_b, eta_b, angle_b = src_info[j]
                if eta_b - eta_a > eta_sync_tolerance:
                    break

                joint_eta = max(eta_a, eta_b)
                if timelines and target.id in timelines:
                    needed = ships_needed_to_capture_at(
                        target, timelines[target.id], player, int(math.ceil(joint_eta))
                    )
                else:
                    needed = ships_budget(target, my_eta=joint_eta)

                if needed <= 0:
                    continue

                reserve_a = (
                    defense_status[src_a.id][1]
                    if defense_status and src_a.id in defense_status
                    else 0
                )
                reserve_b = (
                    defense_status[src_b.id][1]
                    if defense_status and src_b.id in defense_status
                    else 0
                )
                avail_a = max(0, src_a.ships - reserve_a)
                avail_b = max(0, src_b.ships - reserve_b)

                if avail_a + avail_b < needed:
                    continue
                if avail_a < 1 or avail_b < 1:
                    continue

                total_avail = avail_a + avail_b
                ships_a = max(1, min(avail_a, math.ceil(needed * avail_a / total_avail)))
                ships_b = needed - ships_a
                if ships_b <= 0 or ships_b > avail_b:
                    ships_b = min(avail_b, needed - 1)
                    ships_a = needed - ships_b
                if ships_a <= 0 or ships_a > avail_a:
                    continue

                value = target_value(
                    src_a,
                    target.x,
                    target.y,
                    target.production,
                    rival_eta,
                    ships_a + ships_b,
                    joint_eta,
                    target_owner=target.owner,
                    mode=mode,
                    remaining_turns=remaining_turns,
                    is_orbital=is_orbital,
                    orbital_radius=r,
                )
                if value <= 0:
                    continue

                missions.append(
                    SwarmMission(
                        target=target,
                        src_a=src_a,
                        ships_a=ships_a,
                        angle_a=angle_a,
                        eta_a=eta_a,
                        src_b=src_b,
                        ships_b=ships_b,
                        angle_b=angle_b,
                        eta_b=eta_b,
                        value=value,
                    )
                )

    return missions


def select_move(my_planet: Planet, candidates, reserve: int = 0, my_planet_count: int = 1):
    """value 最大の発射可能候補を返す。なければ None。

    返り値: (target_id, angle, ships_needed, my_eta) または None。
    候補タプルは (target, ships_needed, angle, value) または
    (target, ships_needed, angle, value, my_eta) を受け付ける。
    """
    best = None
    best_value = -math.inf
    for cand in candidates:
        target, ships_needed, angle, value = cand[0], cand[1], cand[2], cand[3]
        my_eta = float(cand[4]) if len(cand) >= 5 else 0.0
        if ships_needed <= 0 or value <= 0:
            continue
        if my_planet.ships - reserve < ships_needed:
            continue
        if value > best_value:
            best_value = value
            best = (target.id, angle, ships_needed, my_eta)
    return best
