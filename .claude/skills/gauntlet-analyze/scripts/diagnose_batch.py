#!/usr/bin/env python3
"""Run analyze_loss.py over all losses in a run and emit aggregated stats.

Usage:
    python diagnose_batch.py <run_dir> [--target AGENT_ID] [--opponent REGEX] [--limit N]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from statistics import mean, median

from analyze_loss import analyze


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--target", default="mine/planet_intercept")
    ap.add_argument("--opponent", default=None, help="regex filter on opponent id")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    results_path = run_dir / "results.json"
    if not results_path.exists():
        print(f"error: {results_path} not found", file=sys.stderr)
        return 1

    with results_path.open() as f:
        data = json.load(f)

    opp_re = re.compile(args.opponent) if args.opponent else None
    losses = []
    for m in data["matches"]:
        if args.target not in m["agent_ids"]:
            continue
        opp = [a for a in m["agent_ids"] if a != args.target][0]
        if opp_re and not opp_re.search(opp):
            continue
        if m["winner"] == args.target:
            continue
        losses.append((m, opp))

    if args.limit:
        losses = losses[: args.limit]

    records = []
    for m, opp in losses:
        replay_path = run_dir / m["replay_path"]
        if not replay_path.exists():
            continue
        target_idx = m["agent_ids"].index(args.target)
        try:
            r = analyze(replay_path, target_idx)
        except Exception as exc:
            print(f"skip {m['match_id']}: {exc}", file=sys.stderr)
            continue
        r["match_id"] = m["match_id"]
        r["opponent"] = opp
        r["seed"] = m["seed"]
        records.append(r)

    if args.json:
        print(json.dumps(records, indent=2, ensure_ascii=False))
        return 0

    # Aggregate
    def stats(values: list, unit: str = "") -> str:
        vals = [v for v in values if v is not None]
        if not vals:
            return "n/a"
        return f"min={min(vals)}{unit} median={median(vals):.0f}{unit} mean={mean(vals):.1f}{unit} max={max(vals)}{unit}"

    print(f"target: {args.target}")
    print(f"run: {run_dir.name}  losses analyzed: {len(records)}")
    print()
    print("Distribution across losses:")
    print(f"  total_turns            {stats([r['total_turns'] for r in records])}")
    print(f"  home_fall_turn         {stats([r['home_fall_turn'] for r in records])}")
    print(f"  first_loss_turn        {stats([r['first_loss_turn'] for r in records])}")
    print(f"  planet_parity_lost     {stats([r['planet_parity_lost_turn'] for r in records])}")
    print(f"  peak_incoming_to_mine  {stats([r['peak_incoming_to_mine'] for r in records])}")
    print(f"  peak_simul_arrivals    {stats([r['peak_simultaneous_arrivals'] for r in records])}")
    print(f"  sun_crossings          {stats([r['mine_sun_crossings'] for r in records])}")
    print(f"  sun_crossing_ratio(%)  {stats([round(r['sun_crossing_ratio'] * 100, 1) for r in records])}")

    print()
    print("Per-loss table:")
    print(
        f"{'match':>6s} {'opp':30s} {'turns':>5s} {'home_fall':>10s} {'parity_lost':>11s} {'peak_in':>8s} {'peak_sim':>9s} {'sun%':>5s}"
    )
    for r in records:
        opp_short = r["opponent"].replace("external/", "").replace("baselines/", "")[:30]
        sun_pct = f"{r['sun_crossing_ratio'] * 100:.1f}"
        print(
            f"{r['match_id']:>6s} {opp_short:30s} {r['total_turns']:>5d} "
            f"{str(r['home_fall_turn']):>10s} {str(r['planet_parity_lost_turn']):>11s} "
            f"{r['peak_incoming_to_mine']:>8d} {r['peak_simultaneous_arrivals']:>9d} {sun_pct:>5s}"
        )

    print()
    print("Milestone medians (mine_p / opp_p  mine_s / opp_s):")
    all_turns = sorted({t for r in records for t in r["milestones"].keys()}, key=int)
    for t in all_turns:
        mp, op, ms, os = [], [], [], []
        for r in records:
            m = r["milestones"].get(t)
            if not m:
                continue
            mp.append(m["mine_planets"])
            op.append(m["opp_planets"])
            ms.append(m["mine_ships"])
            os.append(m["opp_ships"])
        if not mp:
            continue
        print(
            f"  t={t:>4}: {median(mp):>4.0f} / {median(op):>4.0f}  "
            f"{median(ms):>5.0f} / {median(os):>5.0f}  (n={len(mp)})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
