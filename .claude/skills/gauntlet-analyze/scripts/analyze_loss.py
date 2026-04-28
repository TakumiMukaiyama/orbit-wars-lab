#!/usr/bin/env python3
"""Analyze a single replay to extract loss diagnostics.

Usage:
    python analyze_loss.py <replay.json> [--target-index 0|1] [--json]

If --target-index is not supplied, defaults to 0 (first agent in the replay).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

SUN_X = 50.0
SUN_Y = 50.0
SUN_RADIUS = 10.0  # generous; actual is ~8 but we want to flag near-misses too
SHIP_SPEED_BASE = 1.0  # fallback, overridden from config
COMET_OWNER = -2
NEUTRAL_OWNER = -1


def dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def segment_intersects_circle(
    x1: float, y1: float, x2: float, y2: float, cx: float, cy: float, r: float
) -> bool:
    # Closest point on segment to (cx, cy)
    dx = x2 - x1
    dy = y2 - y1
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq == 0:
        return dist((x1, y1), (cx, cy)) <= r
    t = ((cx - x1) * dx + (cy - y1) * dy) / seg_len_sq
    t = max(0.0, min(1.0, t))
    px = x1 + t * dx
    py = y1 + t * dy
    return dist((px, py), (cx, cy)) <= r


def parse_planet(p: list) -> dict:
    # [id, owner, x, y, radius, ships, production]
    return {
        "id": p[0],
        "owner": p[1],
        "x": p[2],
        "y": p[3],
        "radius": p[4],
        "ships": p[5],
        "production": p[6],
    }


def parse_fleet(f: list) -> dict:
    # [id, owner, x, y, angle, ships, ???]
    return {
        "id": f[0],
        "owner": f[1],
        "x": f[2],
        "y": f[3],
        "angle": f[4],
        "ships": f[5],
    }


def fleet_target_planet(f: dict, planets: list[dict]) -> int | None:
    """Heuristic: find the planet the fleet is heading towards (nearest forward)."""
    fx, fy, ang = f["x"], f["y"], f["angle"]
    dx, dy = math.cos(ang), math.sin(ang)
    best_id = None
    best_dist = math.inf
    for p in planets:
        # project planet position onto fleet heading
        rx, ry = p["x"] - fx, p["y"] - fy
        forward = rx * dx + ry * dy
        if forward <= 0:
            continue
        perp = abs(rx * dy - ry * dx)
        if perp > max(p["radius"], 2.0):
            continue
        if forward < best_dist:
            best_dist = forward
            best_id = p["id"]
    return best_id


def eta_to_planet(f: dict, planet: dict, ship_speed: float) -> int:
    d = dist((f["x"], f["y"]), (planet["x"], planet["y"]))
    return max(1, int(math.ceil(d / max(ship_speed, 0.1))))


def analyze(replay_path: Path, target_idx: int) -> dict:
    with replay_path.open() as f:
        rep = json.load(f)

    cfg = rep.get("configuration", {})
    ship_speed = cfg.get("shipSpeed", SHIP_SPEED_BASE)
    episode_steps = cfg.get("episodeSteps", 500)
    steps = rep["steps"]
    rewards = rep.get("rewards", [])
    statuses = rep.get("statuses", [])

    mine = target_idx
    opp = 1 - mine

    total_turns = len(steps)
    won = rewards[mine] == 1 if rewards else None

    # Per-turn series
    mine_planets_series: list[int] = []
    opp_planets_series: list[int] = []
    mine_ships_series: list[int] = []  # planet-stationed only
    opp_ships_series: list[int] = []
    mine_fleet_ships_series: list[int] = []
    opp_fleet_ships_series: list[int] = []

    home_fall_turn = None
    first_loss_turn = None
    prev_mine_planet_ids: set[int] | None = None

    mine_sun_crossings = 0
    mine_launches_total = 0

    peak_incoming_to_mine = 0  # fleets headed to mine planets in any single turn
    peak_simultaneous_arrivals = 0  # max fleets arriving at same planet within 2 turns

    for turn_idx, step in enumerate(steps):
        # observations: both agents have same obs (full observability), use mine's
        obs = step[mine]["observation"]
        planets = [parse_planet(p) for p in obs["planets"]]
        fleets = [parse_fleet(f) for f in obs["fleets"]]

        mine_planets = [p for p in planets if p["owner"] == mine]
        opp_planets = [p for p in planets if p["owner"] == opp]
        mine_fleets = [f for f in fleets if f["owner"] == mine]
        opp_fleets = [f for f in fleets if f["owner"] == opp]

        mine_planets_series.append(len(mine_planets))
        opp_planets_series.append(len(opp_planets))
        mine_ships_series.append(sum(p["ships"] for p in mine_planets))
        opp_ships_series.append(sum(p["ships"] for p in opp_planets))
        mine_fleet_ships_series.append(sum(f["ships"] for f in mine_fleets))
        opp_fleet_ships_series.append(sum(f["ships"] for f in opp_fleets))

        mine_planet_ids = {p["id"] for p in mine_planets}

        if home_fall_turn is None and turn_idx > 0 and len(mine_planets) == 0:
            home_fall_turn = turn_idx
        if (
            first_loss_turn is None
            and prev_mine_planet_ids is not None
            and prev_mine_planet_ids - mine_planet_ids
        ):
            first_loss_turn = turn_idx

        # Incoming to mine planets
        incoming_counts: Counter[int] = Counter()
        arrival_bins: Counter[tuple[int, int]] = Counter()  # (planet_id, eta_bucket)
        for f in opp_fleets:
            tp_id = fleet_target_planet(f, mine_planets)
            if tp_id is None:
                continue
            incoming_counts[tp_id] += 1
            tp = next(p for p in mine_planets if p["id"] == tp_id)
            eta = eta_to_planet(f, tp, ship_speed)
            arrival_bins[(tp_id, eta // 2)] += 1
        if incoming_counts:
            peak_incoming_to_mine = max(peak_incoming_to_mine, sum(incoming_counts.values()))
        if arrival_bins:
            peak_simultaneous_arrivals = max(peak_simultaneous_arrivals, max(arrival_bins.values()))

        # Mine launches this turn: check sun crossing
        mine_action = step[mine].get("action") or []
        for act in mine_action:
            # act = [source_planet_id, angle, ships]
            if len(act) < 3:
                continue
            src_id, angle, ships = act[0], act[1], act[2]
            src = next((p for p in planets if p["id"] == src_id), None)
            if src is None:
                continue
            mine_launches_total += 1
            # pick a point ~25 units out along angle to check sun crossing
            x2 = src["x"] + 30.0 * math.cos(angle)
            y2 = src["y"] + 30.0 * math.sin(angle)
            if segment_intersects_circle(src["x"], src["y"], x2, y2, SUN_X, SUN_Y, SUN_RADIUS):
                mine_sun_crossings += 1

        prev_mine_planet_ids = mine_planet_ids

    # Summarize series into key milestones
    def series_at(series: list[int], turn: int) -> int:
        if turn < 0 or turn >= len(series):
            return -1
        return series[turn]

    milestones = [0, 25, 50, 75, 100, 150, 200, 300, total_turns - 1]
    milestones = [t for t in milestones if 0 <= t < total_turns]

    result: dict = {
        "replay": str(replay_path.name),
        "total_turns": total_turns,
        "episode_steps": episode_steps,
        "won": won,
        "target_index": mine,
        "home_fall_turn": home_fall_turn,
        "first_loss_turn": first_loss_turn,
        "mine_sun_crossings": mine_sun_crossings,
        "mine_launches_total": mine_launches_total,
        "sun_crossing_ratio": (
            round(mine_sun_crossings / mine_launches_total, 3) if mine_launches_total else 0
        ),
        "peak_incoming_to_mine": peak_incoming_to_mine,
        "peak_simultaneous_arrivals": peak_simultaneous_arrivals,
        "milestones": {
            str(t): {
                "mine_planets": series_at(mine_planets_series, t),
                "opp_planets": series_at(opp_planets_series, t),
                "mine_ships": series_at(mine_ships_series, t),
                "opp_ships": series_at(opp_ships_series, t),
                "mine_fleet_ships": series_at(mine_fleet_ships_series, t),
                "opp_fleet_ships": series_at(opp_fleet_ships_series, t),
            }
            for t in milestones
        },
    }

    # Turn at which planet-count parity was lost (mine falls below opp)
    parity_lost = None
    for t in range(total_turns):
        if mine_planets_series[t] < opp_planets_series[t]:
            parity_lost = t
            break
    result["planet_parity_lost_turn"] = parity_lost

    return result


def format_text(r: dict) -> str:
    lines = []
    lines.append(f"replay: {r['replay']}  turns={r['total_turns']}/{r['episode_steps']}  won={r['won']}")
    lines.append(f"home_fall_turn: {r['home_fall_turn']}")
    lines.append(f"first_loss_turn: {r['first_loss_turn']}   parity_lost_turn: {r['planet_parity_lost_turn']}")
    lines.append(
        f"mine_launches: {r['mine_launches_total']}  "
        f"sun_crossings: {r['mine_sun_crossings']} ({r['sun_crossing_ratio'] * 100:.1f}%)"
    )
    lines.append(
        f"peak_incoming_to_mine: {r['peak_incoming_to_mine']}  "
        f"peak_simultaneous_arrivals(eta-bucket=2turns): {r['peak_simultaneous_arrivals']}"
    )
    lines.append("milestones (turn: mine_p/opp_p  mine_s/opp_s  mine_ff/opp_ff):")
    for t, m in r["milestones"].items():
        lines.append(
            f"  t={t:>4}: {m['mine_planets']}/{m['opp_planets']}  "
            f"{m['mine_ships']}/{m['opp_ships']}  {m['mine_fleet_ships']}/{m['opp_fleet_ships']}"
        )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("replay")
    ap.add_argument("--target-index", type=int, default=0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    replay_path = Path(args.replay)
    if not replay_path.exists():
        print(f"error: {replay_path} not found", file=sys.stderr)
        return 1

    result = analyze(replay_path, args.target_index)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_text(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
