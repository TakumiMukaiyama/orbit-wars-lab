"""候補列挙のデバッグロガー。

環境変数 ``ORBIT_WARS_CAND_LOG`` にファイルパスが設定されているときのみ有効。
各ターンの (planet, mode) ごとに、attack/intercept/snipe 候補の
(target_id, target_owner, ships_needed, my_eta, value, rival_eta) と、
select_move で採用された target_id を JSON Lines で追記する。

「value<=0 で不発だったターンがどれだけあるか」「敵陣 / 中立のどちらで詰まっているか」
を後で集計するための生ログ。解析側の形を固定しすぎないよう、キー名は小文字+snake。
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Iterable

from .targeting import compute_rival_eta

_ENV_VAR = "ORBIT_WARS_CAND_LOG"


def is_enabled() -> bool:
    return bool(os.environ.get(_ENV_VAR))


def _encode_value(v: float) -> float | str:
    if v == math.inf:
        return "inf"
    if v == -math.inf:
        return "-inf"
    if isinstance(v, float) and math.isnan(v):
        return "nan"
    return v


def _candidate_to_dict(
    kind: str,
    cand: tuple,
    rival_eta: float,
) -> dict:
    target, ships_needed, _angle, value = cand[0], cand[1], cand[2], cand[3]
    my_eta = float(cand[4]) if len(cand) >= 5 else 0.0
    return {
        "kind": kind,
        "target": int(target.id),
        "target_owner": int(target.owner),
        "target_ships": int(target.ships),
        "target_prod": int(target.production),
        "ships_needed": int(ships_needed),
        "my_eta": round(float(my_eta), 3),
        "value": round(float(value), 3),
        "rival_eta": _encode_value(float(rival_eta)) if rival_eta is not None else None,
    }


def log_turn(
    *,
    step: int,
    player: int,
    mine,
    mode: str,
    reserve: int,
    attack: Iterable[tuple],
    intercept: Iterable[tuple],
    snipe: Iterable[tuple],
    picked_target: int | None,
    fleets,
    planets,
    angular_velocity: float,
) -> None:
    path = os.environ.get(_ENV_VAR)
    if not path:
        return

    def dump(kind, cands):
        out = []
        for c in cands:
            target = c[0]
            try:
                rival_eta = compute_rival_eta(target, player, fleets, planets, angular_velocity)
            except Exception:
                rival_eta = math.inf
            out.append(_candidate_to_dict(kind, c, rival_eta))
        return out

    record = {
        "step": int(step),
        "player": int(player),
        "planet": int(mine.id),
        "planet_owner": int(mine.owner),
        "planet_ships": int(mine.ships),
        "mode": mode,
        "reserve": int(reserve),
        "picked_target": int(picked_target) if picked_target is not None else None,
        "candidates": (
            dump("attack", attack) + dump("intercept", intercept) + dump("snipe", snipe)
        ),
    }

    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False))
        f.write("\n")
