#!/usr/bin/env python3
"""Summarize a gauntlet run: per-opponent W-L, loss metadata, outcome classes.

Usage:
    python summarize_run.py <run_dir> [--target AGENT_ID]

<run_dir> is the directory containing results.json (e.g. runs/2026-04-28-001).
--target defaults to 'mine/planet_intercept'.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def classify_outcome(mine_score: int, opp_score: int, turns: int, win: bool, episode_steps: int = 500) -> str:
    if win:
        return "win"
    ratio = mine_score / max(opp_score, 1)
    if turns < episode_steps:
        return "zero_early"  # short match, implies resign/elimination
    if ratio < 0.1:
        return "blowout_full"
    return "close_full"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--target", default="mine/planet_intercept")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    results_path = run_dir / "results.json"
    if not results_path.exists():
        print(f"error: {results_path} not found", file=sys.stderr)
        return 1

    with results_path.open() as f:
        data = json.load(f)

    matches = data.get("matches", [])
    if not matches:
        print("error: no matches", file=sys.stderr)
        return 1

    # Read episodeSteps from first replay config if available, else default 500.
    episode_steps = 500
    first_replay = run_dir / matches[0].get("replay_path", "")
    if first_replay.exists():
        try:
            with first_replay.open() as f:
                rep = json.load(f)
            episode_steps = rep.get("configuration", {}).get("episodeSteps", 500)
        except Exception:
            pass

    by_opp: dict[str, dict] = defaultdict(lambda: {"W": 0, "L": 0, "losses": [], "outcomes": defaultdict(int)})
    for m in matches:
        if args.target not in m["agent_ids"]:
            continue
        opp = [a for a in m["agent_ids"] if a != args.target][0]
        mine_idx = m["agent_ids"].index(args.target)
        opp_idx = 1 - mine_idx
        mine_score = m["scores"][mine_idx]
        opp_score = m["scores"][opp_idx]
        turns = m["turns"]
        win = m["winner"] == args.target
        outcome = classify_outcome(mine_score, opp_score, turns, win, episode_steps)

        rec = by_opp[opp]
        rec["outcomes"][outcome] += 1
        if win:
            rec["W"] += 1
        else:
            rec["L"] += 1
            rec["losses"].append(
                {
                    "match_id": m["match_id"],
                    "seed": m["seed"],
                    "turns": turns,
                    "mine_score": mine_score,
                    "opp_score": opp_score,
                    "ratio": round(mine_score / max(opp_score, 1), 4),
                    "outcome": outcome,
                    "replay_path": m.get("replay_path"),
                }
            )

    total_w = sum(r["W"] for r in by_opp.values())
    total_l = sum(r["L"] for r in by_opp.values())

    if args.json:
        out = {
            "run_id": data.get("run_id") or run_dir.name,
            "target": args.target,
            "total_w": total_w,
            "total_l": total_l,
            "episode_steps": episode_steps,
            "by_opp": {
                opp: {
                    "W": r["W"],
                    "L": r["L"],
                    "outcomes": dict(r["outcomes"]),
                    "losses": r["losses"],
                }
                for opp, r in by_opp.items()
            },
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    print(f"target: {args.target}")
    print(f"run: {run_dir.name}")
    print(f"TOTAL: {total_w}-{total_l}  ({total_w / (total_w + total_l) * 100:.1f}% WR, n={total_w + total_l})")
    print()
    print(f"{'opponent':40s} {'W-L':>6s}  outcomes")
    for opp in sorted(by_opp):
        r = by_opp[opp]
        outcomes = ", ".join(f"{k}={v}" for k, v in sorted(r["outcomes"].items()))
        print(f"{opp:40s} {r['W']:>2}-{r['L']:<2}  {outcomes}")

    print()
    print("losses:")
    for opp in sorted(by_opp):
        r = by_opp[opp]
        if not r["losses"]:
            continue
        print(f"  {opp}")
        for loss in r["losses"]:
            print(
                f"    {loss['match_id']} seed={loss['seed']} turns={loss['turns']} "
                f"score={loss['mine_score']} vs {loss['opp_score']} ratio={loss['ratio']} "
                f"[{loss['outcome']}]"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
