# RL対応リファクタリング実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `planet_intercept` エージェントを3層 (state / action_space / policy) に分解し、模倣学習用の ReplayLogger を追加する。提出用 `agent(obs)` の動作は変えない。

**Architecture:** `state.py` で `GameState` と特徴量ベクトルを定義し、`action_space.py` で `Candidate` dataclass と ships_bucket 離散化を担い、`policy.py` で `Policy` ABC / `HeuristicPolicy` / `ReplayLogger` を実装する。`agent.py` は `HeuristicPolicy().act()` を呼ぶだけに薄くなる。

**Tech Stack:** Python 3.13, numpy, uv, pytest

---

## ファイル構成

| ファイル | 変更 | 責務 |
|---------|------|------|
| `src/state.py` | 新設 | `GameState` dataclass、`build_game_state`、特徴量ベクトル関数 |
| `src/action_space.py` | 新設 | `Candidate` dataclass、`candidates_from_heuristic`、`build_invalid_mask` |
| `src/policy.py` | 新設 | `Policy` ABC、`HeuristicPolicy`、`ReplayLogger` |
| `src/agent.py` | 変更 | `HeuristicPolicy().act()` を呼ぶだけに薄くする |
| `tests/test_state.py` | 新設 | `build_game_state` のテスト |
| `tests/test_action_space.py` | 新設 | `Candidate` 変換・mask のテスト |
| `tests/test_policy.py` | 新設 | `HeuristicPolicy` が旧 `agent(obs)` と同一 moves を返すことの確認 |
| `src/targeting.py` | 変更なし | — |
| `src/world.py` | 変更なし | — |
| `src/geometry.py` | 変更なし | — |
| `src/utils.py` | 変更なし | — |
| `src/cand_log.py` | 変更なし | — |

---

### Task 1: `state.py` — `GameState` と `build_game_state`

**Files:**
- Create: `agents/mine/planet_intercept/src/state.py`
- Test: `agents/mine/planet_intercept/tests/test_state.py`

- [ ] **Step 1: 失敗するテストを書く**

`agents/mine/planet_intercept/tests/test_state.py` を作成:

```python
import math
import pytest
from src.state import GameState, build_game_state


def _make_obs(step=10, remaining_turns=490):
    return {
        "player": 0,
        "planets": [
            [0, 0, 20.0, 20.0, 1.0, 30, 2],   # mine
            [1, -1, 70.0, 70.0, 1.0, 10, 1],   # neutral
            [2, 1, 80.0, 80.0, 1.0, 20, 3],    # enemy
        ],
        "fleets": [],
        "angular_velocity": 0.0,
        "step": step,
        "comet_planet_ids": [],
    }


def test_build_game_state_basic():
    obs = _make_obs()
    gs = build_game_state(obs)
    assert gs.player == 0
    assert gs.remaining_turns == 490
    assert gs.step == 10
    assert len(gs.my_planets) == 1
    assert gs.my_planets[0].id == 0


def test_build_game_state_mode_neutral():
    obs = _make_obs()
    gs = build_game_state(obs)
    # my_total=30, enemy_total=20 -> dom=(30-20)/(30+20)=0.2 -> neutral
    assert gs.mode == "neutral"
    assert math.isclose(gs.domination, 0.2)


def test_build_game_state_mode_ahead():
    obs = _make_obs()
    obs["planets"][0][5] = 200  # mine.ships=200
    gs = build_game_state(obs)
    assert gs.mode == "ahead"


def test_build_game_state_mode_behind():
    obs = _make_obs()
    obs["planets"][2][5] = 200  # enemy.ships=200
    gs = build_game_state(obs)
    assert gs.mode == "behind"


def test_build_game_state_timelines_exist():
    obs = _make_obs()
    gs = build_game_state(obs)
    for p in gs.planets:
        assert p.id in gs.timelines


def test_build_game_state_defense_status_keys():
    obs = _make_obs()
    gs = build_game_state(obs)
    for p in gs.my_planets:
        assert p.id in gs.defense_status
        status, reserve = gs.defense_status[p.id]
        assert status in ("safe", "threatened", "doomed")
        assert reserve >= 0


def test_build_game_state_is_opening():
    obs_early = _make_obs(step=5, remaining_turns=495)
    obs_late = _make_obs(step=100, remaining_turns=400)
    assert build_game_state(obs_early).is_opening is True
    assert build_game_state(obs_late).is_opening is False
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
cd agents/mine/planet_intercept && uv run pytest tests/test_state.py -v 2>&1 | head -20
```

期待: `ImportError: cannot import name 'GameState' from 'src.state'`

- [ ] **Step 3: `src/state.py` を実装する**

```python
"""GameState: ターンごとの状態集約と特徴量ベクトル化。"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .targeting import (
    AHEAD_THRESHOLD,
    BEHIND_THRESHOLD,
    OPENING_TURNS,
    classify_defense,
    compute_domination,
)
from .utils import Fleet, Planet, parse_obs
from .world import Arrival, PlanetState, build_arrival_ledger, build_timelines

NEUTRAL_OWNER = -1


@dataclass
class GameState:
    player: int
    planets: list[Planet]
    fleets: list[Fleet]
    angular_velocity: float
    remaining_turns: int
    step: int
    my_planets: list[Planet]
    mode: str
    domination: float
    timelines: dict[int, list[PlanetState]]
    ledger: dict[int, list[Arrival]]
    defense_status: dict[int, tuple[str, int]]
    horizon: int
    is_opening: bool


def build_game_state(obs, comet_ids: frozenset[int] | None = None) -> GameState:
    player, planets, fleets, angular_velocity, remaining_turns, parsed_comet_ids, step = (
        parse_obs(obs)
    )
    if comet_ids is None:
        comet_ids = parsed_comet_ids
    if comet_ids:
        planets = [p for p in planets if p.id not in comet_ids]

    my_planets = [p for p in planets if p.owner == player]

    my_total = sum(p.ships for p in my_planets) + sum(
        f.ships for f in fleets if f.owner == player
    )
    enemy_total = sum(p.ships for p in planets if p.owner not in (player, NEUTRAL_OWNER)) + sum(
        f.ships for f in fleets if f.owner not in (player, NEUTRAL_OWNER)
    )
    dom = compute_domination(my_total, enemy_total)
    if dom < BEHIND_THRESHOLD:
        mode = "behind"
    elif dom > AHEAD_THRESHOLD:
        mode = "ahead"
    else:
        mode = "neutral"

    horizon = max(1, min(80, remaining_turns))
    ledger = build_arrival_ledger(planets, fleets, horizon=horizon)
    timelines = build_timelines(planets, ledger, horizon=horizon)

    elapsed_turns = 500 - remaining_turns
    is_opening = elapsed_turns < OPENING_TURNS

    defense_status: dict[int, tuple[str, int]] = {
        p.id: classify_defense(p, fleets, player, timeline=timelines.get(p.id))
        for p in my_planets
    }
    if is_opening:
        defense_status = {
            pid: (status, reserve // 2)
            for pid, (status, reserve) in defense_status.items()
        }

    return GameState(
        player=player,
        planets=planets,
        fleets=fleets,
        angular_velocity=angular_velocity,
        remaining_turns=remaining_turns,
        step=step,
        my_planets=my_planets,
        mode=mode,
        domination=dom,
        timelines=timelines,
        ledger=ledger,
        defense_status=defense_status,
        horizon=horizon,
        is_opening=is_opening,
    )


def planet_features(
    p: Planet,
    gs: GameState,
    source: Planet | None = None,
) -> np.ndarray:
    """惑星ごとの特徴量ベクトル (17次元)。"""
    if source is not None:
        rel_x = (p.x - source.x) / 100.0
        rel_y = (p.y - source.y) / 100.0
        dist = math.hypot(p.x - source.x, p.y - source.y) / 141.4
    else:
        rel_x, rel_y, dist = 0.0, 0.0, 0.0

    owner_vec = [0.0] * 5
    if p.owner == gs.player:
        owner_vec[0] = 1.0
    elif p.owner == NEUTRAL_OWNER:
        owner_vec[2] = 1.0
    else:
        owner_vec[1] = 1.0

    ships_norm = min(p.ships / 200.0, 1.0)
    prod_norm = p.production / 5.0

    from .utils import CENTER
    r = math.hypot(p.x - CENTER, p.y - CENTER)
    is_orbital = float(gs.angular_velocity != 0.0 and (r + p.radius < 50))

    timeline = gs.timelines.get(p.id, [])
    tl_feats = [0.0] * 3
    for i, eta_check in enumerate([10, 20, 40]):
        idx = min(eta_check - 1, len(timeline) - 1)
        if idx >= 0:
            s = timeline[idx]
            tl_feats[i] = 1.0 if s.owner == gs.player else (-1.0 if s.owner != NEUTRAL_OWNER else 0.0)

    ds = gs.defense_status.get(p.id)
    if ds is None:
        def_vec = [1.0, 0.0, 0.0]
    elif ds[0] == "safe":
        def_vec = [1.0, 0.0, 0.0]
    elif ds[0] == "threatened":
        def_vec = [0.0, 1.0, 0.0]
    else:
        def_vec = [0.0, 0.0, 1.0]

    return np.array(
        [rel_x, rel_y, dist] + owner_vec + [ships_norm, prod_norm, is_orbital] + tl_feats + def_vec,
        dtype=np.float32,
    )


def global_features(gs: GameState) -> np.ndarray:
    """盤面全体の特徴量ベクトル (7次元)。"""
    mode_vec = [
        float(gs.mode == "behind"),
        float(gs.mode == "neutral"),
        float(gs.mode == "ahead"),
    ]
    return np.array(
        [
            gs.domination,
            gs.remaining_turns / 500.0,
            len(gs.my_planets) / 20.0,
            float(gs.is_opening),
        ]
        + mode_vec,
        dtype=np.float32,
    )
```

- [ ] **Step 4: テストが通ることを確認**

```bash
cd agents/mine/planet_intercept && uv run pytest tests/test_state.py -v
```

期待: 全テスト PASS

- [ ] **Step 5: 既存テストがリグレッションしていないことを確認**

```bash
cd agents/mine/planet_intercept && uv run pytest tests/ -v --ignore=tests/test_state.py
```

期待: 全テスト PASS (変更なし)

- [ ] **Step 6: コミット**

```bash
cd agents/mine/planet_intercept && git add src/state.py tests/test_state.py
git commit -m "feat(rl): add state.py - GameState, build_game_state, feature vectors"
```

---

### Task 2: `action_space.py` — `Candidate` と変換関数

**Files:**
- Create: `agents/mine/planet_intercept/src/action_space.py`
- Test: `agents/mine/planet_intercept/tests/test_action_space.py`

- [ ] **Step 1: 失敗するテストを書く**

`agents/mine/planet_intercept/tests/test_action_space.py` を作成:

```python
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
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
cd agents/mine/planet_intercept && uv run pytest tests/test_action_space.py -v 2>&1 | head -20
```

期待: `ImportError: cannot import name 'Candidate' from 'src.action_space'`

- [ ] **Step 3: `src/action_space.py` を実装する**

```python
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
```

- [ ] **Step 4: テストが通ることを確認**

```bash
cd agents/mine/planet_intercept && uv run pytest tests/test_action_space.py -v
```

期待: 全テスト PASS

- [ ] **Step 5: 既存テストがリグレッションしていないことを確認**

```bash
cd agents/mine/planet_intercept && uv run pytest tests/ -v --ignore=tests/test_action_space.py
```

期待: 全テスト PASS

- [ ] **Step 6: コミット**

```bash
cd agents/mine/planet_intercept && git add src/action_space.py tests/test_action_space.py
git commit -m "feat(rl): add action_space.py - Candidate, bucket_to_ships, invalid mask"
```

---

### Task 3: `policy.py` — `HeuristicPolicy` と `ReplayLogger`

**Files:**
- Create: `agents/mine/planet_intercept/src/policy.py`
- Test: `agents/mine/planet_intercept/tests/test_policy.py`

- [ ] **Step 1: 失敗するテストを書く**

`agents/mine/planet_intercept/tests/test_policy.py` を作成:

```python
import json
import math
import os
import tempfile

import pytest

from src.action_space import Candidate
from src.policy import HeuristicPolicy, ReplayLogger
from src.state import build_game_state


def _make_obs(step=50):
    return {
        "player": 0,
        "planets": [
            [0, 0,  20.0, 20.0, 1.0, 50, 2],
            [1, -1, 70.0, 70.0, 1.0, 10, 1],
            [2, 1,  80.0, 80.0, 1.0, 20, 3],
        ],
        "fleets": [],
        "angular_velocity": 0.0,
        "step": step,
        "comet_planet_ids": [],
    }


def test_heuristic_policy_returns_list():
    obs = _make_obs()
    gs = build_game_state(obs)
    policy = HeuristicPolicy()
    moves = policy.act(gs)
    assert isinstance(moves, list)


def test_heuristic_policy_move_format():
    obs = _make_obs()
    gs = build_game_state(obs)
    moves = HeuristicPolicy().act(gs)
    for m in moves:
        assert len(m) == 3
        planet_id, angle, ships = m
        assert isinstance(planet_id, int)
        assert isinstance(angle, float)
        assert isinstance(ships, int)
        assert ships > 0


def test_heuristic_policy_matches_original_agent():
    """HeuristicPolicy.act が旧 agent(obs) と同一 moves を返すこと。"""
    from src.agent import agent as original_agent
    obs = _make_obs()
    expected = original_agent(obs)
    gs = build_game_state(obs)
    got = HeuristicPolicy().act(gs)
    assert got == expected


def test_heuristic_policy_no_planets():
    obs = _make_obs()
    obs["planets"] = [
        [1, -1, 70.0, 70.0, 1.0, 10, 1],
    ]
    gs = build_game_state(obs)
    moves = HeuristicPolicy().act(gs)
    assert moves == []


def test_replay_logger_disabled_by_default(tmp_path):
    obs = _make_obs()
    gs = build_game_state(obs)
    logger = ReplayLogger()
    # 環境変数未設定なら no-op
    assert not logger.is_enabled()


def test_replay_logger_writes_jsonl(tmp_path, monkeypatch):
    log_path = tmp_path / "replay.jsonl"
    monkeypatch.setenv("ORBIT_WARS_REPLAY_LOG", str(log_path))

    obs = _make_obs()
    gs = build_game_state(obs)
    policy = HeuristicPolicy()
    logger = ReplayLogger()

    assert logger.is_enabled()

    candidates_by_source = policy.last_candidates_by_source
    chosen = policy.last_chosen
    logger.log_turn(gs, candidates_by_source, chosen)

    lines = log_path.read_text().strip().split("\n")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["step"] == gs.step
    assert record["player"] == gs.player
    assert "global_features" in record
    assert "sources" in record


def test_replay_logger_chosen_idx_is_correct(tmp_path, monkeypatch):
    log_path = tmp_path / "replay.jsonl"
    monkeypatch.setenv("ORBIT_WARS_REPLAY_LOG", str(log_path))

    obs = _make_obs()
    gs = build_game_state(obs)
    policy = HeuristicPolicy()
    policy.act(gs)

    logger = ReplayLogger()
    logger.log_turn(gs, policy.last_candidates_by_source, policy.last_chosen)

    record = json.loads(log_path.read_text().strip())
    for src_record in record["sources"]:
        if src_record["chosen_target_id"] is not None:
            assert src_record["chosen_idx"] is not None
            assert 0 <= src_record["chosen_idx"] < len(src_record["candidates"])
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
cd agents/mine/planet_intercept && uv run pytest tests/test_policy.py -v 2>&1 | head -20
```

期待: `ImportError: cannot import name 'HeuristicPolicy' from 'src.policy'`

- [ ] **Step 3: `src/policy.py` を実装する**

```python
"""Policy ABC、HeuristicPolicy、ReplayLogger。"""

from __future__ import annotations

import json
import math
import os
from abc import ABC, abstractmethod

from .action_space import Candidate, candidates_from_heuristic
from .state import GameState, global_features, planet_features
from .targeting import (
    MAX_EXPAND_PER_TURN,
    NEUTRAL_OWNER,
    enumerate_candidates,
    enumerate_intercept_candidates,
    enumerate_reinforce_candidates,
    enumerate_snipe_candidates,
    enumerate_support_candidates,
    select_move,
)
from .world import apply_planned_arrival

_REPLAY_ENV = "ORBIT_WARS_REPLAY_LOG"


class Policy(ABC):
    @abstractmethod
    def act(self, gs: GameState) -> list[tuple[int, float, int]]:
        """[[planet_id, angle, ships], ...] を返す。"""


class HeuristicPolicy(Policy):
    """現行ヒューリスティックを GameState インターフェースでラップする。

    act() 後に last_candidates_by_source と last_chosen が更新される。
    ReplayLogger はこれを使って replay を記録する。
    """

    def __init__(self):
        self.last_candidates_by_source: dict[int, list[Candidate]] = {}
        self.last_chosen: list[Candidate] = []

    def act(self, gs: GameState) -> list[tuple[int, float, int]]:
        self.last_candidates_by_source = {}
        self.last_chosen = []

        if not gs.my_planets:
            return []

        n = len(gs.my_planets)
        planned: dict[int, int] = {}
        intercepted_ids: set[int] = set()
        expand_fired_this_turn: int = 0
        fired_sources: set[int] = set()
        attack_cands_by_planet: dict[int, list] = {}

        moves = []
        for mine in gs.my_planets:
            status, reserve = gs.defense_status[mine.id]

            if status == "doomed" and n > 1:
                safe_allies = [
                    p
                    for p in gs.my_planets
                    if p.id != mine.id and gs.defense_status[p.id][0] != "doomed"
                ]
                if safe_allies:
                    nearest_ally = min(
                        safe_allies,
                        key=lambda p: (p.x - mine.x) ** 2 + (p.y - mine.y) ** 2,
                    )
                    evac_angle = math.atan2(
                        nearest_ally.y - mine.y, nearest_ally.x - mine.x
                    )
                    if mine.ships > 0:
                        moves.append([mine.id, evac_angle, mine.ships])
                continue

            attack_cands = enumerate_candidates(
                mine,
                gs.planets,
                gs.fleets,
                gs.player,
                angular_velocity=gs.angular_velocity,
                planned=planned,
                mode=gs.mode,
                remaining_turns=gs.remaining_turns,
                timelines=gs.timelines,
                my_planet_count=n,
                domination=gs.domination,
                is_opening=gs.is_opening,
            )
            attack_cands_by_planet[mine.id] = attack_cands
            intercept_cands = enumerate_intercept_candidates(
                mine,
                gs.planets,
                gs.fleets,
                gs.player,
                angular_velocity=gs.angular_velocity,
                timelines=gs.timelines,
            )
            intercept_cands = [c for c in intercept_cands if c[0].id not in intercepted_ids]
            support_cands = enumerate_support_candidates(
                mine,
                gs.planets,
                gs.player,
                timelines=gs.timelines,
                planned=planned,
                remaining_turns=gs.remaining_turns,
            )
            support_cands = [c for c in support_cands if c[0].id not in intercepted_ids]
            if gs.mode == "behind":
                snipe_cands = enumerate_snipe_candidates(
                    mine,
                    gs.planets,
                    gs.fleets,
                    gs.player,
                    angular_velocity=gs.angular_velocity,
                    planned=planned,
                    remaining_turns=gs.remaining_turns,
                    timelines=gs.timelines,
                    ledger=gs.ledger,
                    horizon=gs.horizon,
                )
            else:
                snipe_cands = []

            # Candidate 変換 (ログ用)
            cands_for_log = candidates_from_heuristic(
                mine,
                attack_cands,
                intercept_cands,
                support_cands,
                snipe_cands,
                reserve,
            )
            self.last_candidates_by_source[mine.id] = cands_for_log

            all_cands = attack_cands + intercept_cands + support_cands + snipe_cands
            picked = select_move(mine, all_cands, reserve=reserve, my_planet_count=n)
            if picked is None:
                continue

            target_id, angle, ships, my_eta = picked

            target_planet_obj = next((p for p in gs.planets if p.id == target_id), None)
            if (
                gs.is_opening
                and target_planet_obj is not None
                and target_planet_obj.owner == NEUTRAL_OWNER
            ):
                if expand_fired_this_turn >= MAX_EXPAND_PER_TURN:
                    continue
                expand_fired_this_turn += 1

            planned[target_id] = planned.get(target_id, 0) + ships
            arrival_eta = max(1, int(math.ceil(my_eta)))
            apply_planned_arrival(
                gs.ledger,
                gs.timelines,
                gs.planets,
                target_id=target_id,
                owner=gs.player,
                ships=ships,
                eta=arrival_eta,
                horizon=gs.horizon,
            )
            if target_id in gs.defense_status:
                intercepted_ids.add(target_id)
                target_planet = next(
                    (p for p in gs.my_planets if p.id == target_id), None
                )
                if target_planet is not None:
                    from .targeting import classify_defense
                    gs.defense_status[target_id] = classify_defense(
                        target_planet,
                        gs.fleets,
                        gs.player,
                        timeline=gs.timelines.get(target_id),
                    )
            fired_sources.add(mine.id)

            # 採用した Candidate を記録
            chosen_cand = next(
                (
                    c
                    for c in cands_for_log
                    if c.target_id == target_id and c.ships_bucket == 0
                ),
                None,
            )
            if chosen_cand is not None:
                chosen_ships = Candidate(
                    source_id=chosen_cand.source_id,
                    target_id=chosen_cand.target_id,
                    angle=angle,
                    ships=ships,
                    ships_bucket=chosen_cand.ships_bucket,
                    value=chosen_cand.value,
                    my_eta=my_eta,
                    kind=chosen_cand.kind,
                )
                self.last_chosen.append(chosen_ships)

            moves.append([mine.id, angle, ships])

        # reinforce パス
        reinforce_missions = enumerate_reinforce_candidates(
            my_planets=gs.my_planets,
            target_candidates_by_planet=attack_cands_by_planet,
            timelines=gs.timelines,
            reserve_of=lambda p: gs.defense_status[p.id][1],
        )
        reinforce_fired_sources: set[int] = set()
        for r in sorted(reinforce_missions, key=lambda m: -m.value):
            if r.source_id in fired_sources:
                continue
            if r.source_id in reinforce_fired_sources:
                continue
            moves.append([r.source_id, r.angle, r.ships])
            apply_planned_arrival(
                gs.ledger,
                gs.timelines,
                gs.planets,
                target_id=r.target_id,
                owner=gs.player,
                ships=r.ships,
                eta=r.my_eta,
                horizon=gs.horizon,
            )
            reinforce_fired_sources.add(r.source_id)

        return moves


class ReplayLogger:
    """模倣学習用の replay を JSONL で記録する。

    環境変数 ORBIT_WARS_REPLAY_LOG にパスが設定されているときのみ動作する。
    """

    def is_enabled(self) -> bool:
        return bool(os.environ.get(_REPLAY_ENV))

    def log_turn(
        self,
        gs: GameState,
        candidates_by_source: dict[int, list[Candidate]],
        chosen: list[Candidate],
    ) -> None:
        path = os.environ.get(_REPLAY_ENV)
        if not path:
            return

        chosen_by_source: dict[int, Candidate] = {c.source_id: c for c in chosen}

        gf = global_features(gs).tolist()
        sources_data = []
        for mine in gs.my_planets:
            cands = candidates_by_source.get(mine.id, [])
            chosen_cand = chosen_by_source.get(mine.id)

            chosen_idx = None
            chosen_target_id = None
            if chosen_cand is not None:
                chosen_target_id = chosen_cand.target_id
                for i, c in enumerate(cands):
                    if (
                        c.target_id == chosen_cand.target_id
                        and c.ships_bucket == chosen_cand.ships_bucket
                    ):
                        chosen_idx = i
                        break

            pf = planet_features(mine, gs, source=None).tolist()
            sources_data.append(
                {
                    "source_id": mine.id,
                    "planet_features": pf,
                    "candidates": [
                        {
                            "target_id": c.target_id,
                            "ships_bucket": c.ships_bucket,
                            "ships": c.ships,
                            "kind": c.kind,
                            "value": round(c.value, 4),
                            "my_eta": round(c.my_eta, 3),
                        }
                        for c in cands
                    ],
                    "chosen_idx": chosen_idx,
                    "chosen_target_id": chosen_target_id,
                }
            )

        record = {
            "step": gs.step,
            "player": gs.player,
            "global_features": gf,
            "sources": sources_data,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False))
            f.write("\n")
```

- [ ] **Step 4: テストが通ることを確認**

```bash
cd agents/mine/planet_intercept && uv run pytest tests/test_policy.py -v
```

期待: 全テスト PASS

- [ ] **Step 5: 既存テストがリグレッションしていないことを確認**

```bash
cd agents/mine/planet_intercept && uv run pytest tests/ -v --ignore=tests/test_policy.py
```

期待: 全テスト PASS

- [ ] **Step 6: コミット**

```bash
cd agents/mine/planet_intercept && git add src/policy.py tests/test_policy.py
git commit -m "feat(rl): add policy.py - HeuristicPolicy, ReplayLogger"
```

---

### Task 4: `agent.py` をリファクタリング

**Files:**
- Modify: `agents/mine/planet_intercept/src/agent.py`

- [ ] **Step 1: `agent.py` を書き換える**

`agents/mine/planet_intercept/src/agent.py` を以下に置き換える:

```python
"""Phase 1c エージェント: HeuristicPolicy + ReplayLogger ラッパー。"""

from .policy import HeuristicPolicy, ReplayLogger
from .state import build_game_state

_policy = HeuristicPolicy()
_logger = ReplayLogger()


def agent(obs):
    gs = build_game_state(obs)
    moves = _policy.act(gs)
    if _logger.is_enabled():
        _logger.log_turn(gs, _policy.last_candidates_by_source, _policy.last_chosen)
    return moves
```

- [ ] **Step 2: `test_policy.py` の同一性テストが通ることを確認**

```bash
cd agents/mine/planet_intercept && uv run pytest tests/test_policy.py::test_heuristic_policy_matches_original_agent -v
```

期待: PASS

- [ ] **Step 3: 全テストが通ることを確認**

```bash
cd agents/mine/planet_intercept && uv run pytest tests/ -v
```

期待: 全テスト PASS

- [ ] **Step 4: コミット**

```bash
cd agents/mine/planet_intercept && git add src/agent.py
git commit -m "refactor(agent): thin agent.py to use HeuristicPolicy + ReplayLogger"
```

---

## Self-Review

**Spec coverage:**
- `GameState` dataclass: Task 1 で実装 ✓
- `build_game_state`: Task 1 で実装 ✓
- `planet_features` / `global_features`: Task 1 で実装 ✓
- `Candidate` dataclass + ships_bucket: Task 2 で実装 ✓
- `candidates_from_heuristic` + `build_invalid_mask`: Task 2 で実装 ✓
- `Policy` ABC: Task 3 の `policy.py` に含む ✓
- `HeuristicPolicy`: Task 3 で実装 ✓
- `ReplayLogger` + JSONL形式: Task 3 で実装 ✓
- `agent.py` の薄い書き換え: Task 4 で実装 ✓
- 既存テストのリグレッション確認: 各タスクのStep 5で実施 ✓
- `targeting.py` / `world.py` / `geometry.py` は変更なし ✓

**Gaps:** なし

**Type consistency:**
- `Candidate` は Task 2 で定義し、Task 3 の `policy.py` でインポートして使用 ✓
- `GameState` は Task 1 で定義し、Task 3/4 で使用 ✓
- `build_game_state` の戻り型は `GameState` で一貫 ✓
- `HeuristicPolicy.last_candidates_by_source` の型は `dict[int, list[Candidate]]` で Task 3 テストと一致 ✓
