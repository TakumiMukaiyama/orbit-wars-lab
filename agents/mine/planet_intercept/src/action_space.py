"""行動空間の抽象化。Candidate dataclass と ships_bucket 離散化。"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .utils import Planet

SHIPS_BUCKET_COUNT = 5


@dataclass
class Candidate:
    source_id: int
    target_id: int
    angle: float
    ships: int
    ships_bucket: int   # 0-4
    value: float
    my_eta: float
    kind: str           # "attack" / "intercept" / "support" / "snipe" / "reinforce"


def bucket_to_ships(bucket: int, ships_needed: int, avail: int) -> int:
    """bucket インデックスを実際の送船数に変換する。avail を上限にクランプ。"""
    if avail <= 0:
        return 0
    raw = [
        ships_needed,
        math.ceil(ships_needed * 1.5),
        avail // 2,
        avail * 3 // 4,
        avail,
    ]
    return min(max(raw[bucket], ships_needed), avail)


def _raw_to_candidates(
    source_id: int,
    raw: list,
    kind: str,
    reserve: int,
    source_ships: int,
) -> list[Candidate]:
    """enumerate_* の出力タプルを Candidate リストに変換する。

    各 raw エントリごとに SHIPS_BUCKET_COUNT 個の Candidate を生成する。
    (target, ships_needed, angle, value[, my_eta]) 形式を受け付ける。
    """
    avail = max(0, source_ships - reserve)
    out = []
    for entry in raw:
        target = entry[0]
        ships_needed = int(entry[1])
        angle = float(entry[2])
        value = float(entry[3])
        my_eta = float(entry[4]) if len(entry) >= 5 else 0.0
        if ships_needed <= 0:
            continue
        for bucket in range(SHIPS_BUCKET_COUNT):
            ships = bucket_to_ships(bucket, ships_needed, avail)
            out.append(
                Candidate(
                    source_id=source_id,
                    target_id=target.id,
                    angle=angle,
                    ships=ships,
                    ships_bucket=bucket,
                    value=value,
                    my_eta=my_eta,
                    kind=kind,
                )
            )
    return out


def candidates_from_heuristic(
    source: Planet,
    raw_attack: list,
    raw_intercept: list,
    raw_support: list,
    raw_snipe: list,
    reserve: int,
) -> list[Candidate]:
    """enumerate_* の出力をまとめて Candidate リストに変換する。"""
    out = []
    for raw, kind in [
        (raw_attack, "attack"),
        (raw_intercept, "intercept"),
        (raw_support, "support"),
        (raw_snipe, "snipe"),
    ]:
        out.extend(_raw_to_candidates(source.id, raw, kind, reserve, source.ships))
    return out


def build_invalid_mask(
    source: Planet,
    candidates: list[Candidate],
    reserve: int,
) -> np.ndarray:
    """無効アクションのブールマスクを返す (True = invalid)。"""
    avail = max(0, source.ships - reserve)
    mask = np.zeros(len(candidates), dtype=bool)
    for i, c in enumerate(candidates):
        if c.ships > avail:
            mask[i] = True
        elif c.value <= 0:
            mask[i] = True
    return mask
