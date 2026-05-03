import pytest
from src.action_space import (
    Candidate,
    SHIPS_BUCKET_COUNT,
    bucket_to_ships,
    candidates_from_heuristic,
    build_invalid_mask,
)
from src.utils import Planet


def _planet(id, owner, ships=50, production=2, x=20.0, y=20.0):
    return Planet(id=id, owner=owner, x=x, y=y, radius=1.0, ships=ships, production=production)


def test_candidate_fields():
    c = Candidate(
        source_id=0,
        target_id=1,
        angle=1.57,
        ships=10,
        ships_bucket=0,
        value=15.0,
        my_eta=5.0,
        kind="attack",
    )
    assert c.source_id == 0
    assert c.kind == "attack"


def test_bucket_to_ships_five_buckets():
    src = _planet(0, 0, ships=50)
    reserve = 10
    avail = 40  # 50 - 10
    ships_needed = 12
    results = [bucket_to_ships(b, ships_needed, avail) for b in range(SHIPS_BUCKET_COUNT)]
    assert results[0] == 12           # bucket 0: ships_needed
    assert results[1] == 18           # bucket 1: ceil(12 * 1.5) = 18
    assert results[2] == 20           # bucket 2: avail // 2 = 20
    assert results[3] == 30           # bucket 3: avail * 3 // 4 = 30
    assert results[4] == 40           # bucket 4: avail
    # 昇順になっている
    assert results == sorted(results)


def test_bucket_to_ships_clamp_to_avail():
    # ships_needed > avail の場合 bucket 0 は avail にクランプされる
    ships = bucket_to_ships(0, ships_needed=100, avail=30)
    assert ships == 30


def test_candidates_from_heuristic_attack():
    src = _planet(0, 0, ships=50)
    tgt = _planet(1, -1, ships=5)
    reserve = 10
    # enumerate_candidates 形式: (target, ships_needed, angle, value, my_eta)
    raw_attack = [(tgt, 6, 0.785, 20.0, 8.0)]
    cands = candidates_from_heuristic(src, raw_attack, [], [], [], reserve)
    assert len(cands) == SHIPS_BUCKET_COUNT
    assert all(c.kind == "attack" for c in cands)
    assert all(c.source_id == 0 for c in cands)
    assert all(c.target_id == 1 for c in cands)
    assert cands[0].ships_bucket == 0
    assert cands[0].ships == 6


def test_candidates_from_heuristic_kind_labels():
    src = _planet(0, 0, ships=50)
    tgt = _planet(1, -1, ships=5)
    reserve = 0
    raw_intercept = [(tgt, 6, 0.1, 10.0, 3.0)]
    raw_support = [(tgt, 6, 0.2, 8.0, 4.0)]
    raw_snipe = [(tgt, 6, 0.3, 12.0, 5.0)]
    cands = candidates_from_heuristic(src, [], raw_intercept, raw_support, raw_snipe, reserve)
    kinds = {c.kind for c in cands}
    assert "intercept" in kinds
    assert "support" in kinds
    assert "snipe" in kinds


def test_build_invalid_mask_ships_budget():
    src = _planet(0, 0, ships=20)
    reserve = 10
    avail = 10
    # bucket 4 (avail=10) は OK、bucket が avail超えのときのみ mask
    cands = [
        Candidate(source_id=0, target_id=1, angle=0.0, ships=5,  ships_bucket=0, value=10.0, my_eta=5.0, kind="attack"),
        Candidate(source_id=0, target_id=1, angle=0.0, ships=15, ships_bucket=4, value=10.0, my_eta=5.0, kind="attack"),
    ]
    mask = build_invalid_mask(src, cands, reserve)
    assert mask[0] == False   # 5 <= 10: valid
    assert mask[1] == True    # 15 > 10: invalid


def test_build_invalid_mask_nonpositive_value():
    src = _planet(0, 0, ships=50)
    cands = [
        Candidate(source_id=0, target_id=1, angle=0.0, ships=5, ships_bucket=0, value=0.0,  my_eta=5.0, kind="attack"),
        Candidate(source_id=0, target_id=1, angle=0.0, ships=5, ships_bucket=0, value=-1.0, my_eta=5.0, kind="attack"),
    ]
    mask = build_invalid_mask(src, cands, reserve=0)
    assert mask[0] == True   # value=0: invalid
    assert mask[1] == True   # value<0: invalid
