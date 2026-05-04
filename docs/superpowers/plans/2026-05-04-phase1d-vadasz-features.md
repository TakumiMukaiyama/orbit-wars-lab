# Phase 1d: Vadasz 観察由来5機能 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LB1位 Vadasz の行動分析から導出した9機能 (容量ダンプ・後方押し出し・JIT逆算送出・防衛放棄判断・出撃直後スナイプ・同時並行占領・N>2 swarm・overcap・玉突き/ブリッジは後回し) を順番に実装し、各機能をガントレットで検証する。

**Architecture:** 全変更は `targeting.py` (候補列挙) と `policy.py` (アクション選択ループ) に閉じる。新関数を追加 → `policy.py` のパスに合流 → テスト → ガントレット確認の繰り返し。

**Tech Stack:** Python 3.13, uv, pytest (テスト実行: `uv run pytest tests/ -q`)

---

## 事前確認: フィールド存在確認 (実装前に済んでいること)

- [x] `Fleet.from_planet_id`: `utils.py:25` に存在 - 追加不要
- [x] enemy fleet の ledger 反映: `build_arrival_ledger` が全 fleet (enemy 含む) を処理済み - 1-B は実装不要
- [ ] `Planet.max_capacity`: **存在しない** - Task 1 で推定ロジックを追加する

---

## ファイルマップ

| ファイル | 変更内容 |
|---------|---------|
| `src/targeting.py` | 定数追加、新関数追加、既存関数引数追加 |
| `src/policy.py` | 容量ダンプ・後方押し出し・スナイプ・同時並行占領の呼び出し追加 |
| `src/world.py` | 変更なし |
| `src/utils.py` | 変更なし |
| `tests/test_targeting.py` | 各機能のテスト追加 |
| `tests/test_policy.py` | policy レベルの統合テスト追加 |

---

## Task 1: 容量ダンプ (Capacity Dump)

**Files:**
- Modify: `src/targeting.py` - 定数と `_estimate_max_capacity()` 追加
- Modify: `src/policy.py` - `_pick_dump_target()` と容量ダンプ判定追加
- Test: `tests/test_targeting.py` - `_estimate_max_capacity` のテスト
- Test: `tests/test_policy.py` - 容量上限惑星からの強制発射テスト

### 背景

`Planet` に `max_capacity` フィールドはない。observation の惑星配列は `[id, owner, x, y, radius, ships, production]` のみ。ゲームルールでは capacity は production に比例しており、実際のリプレイ計測から `capacity = production * 100` が成立することを前提とする (計測不要 - 既知ゲームルール)。

- [ ] **Step 1: テストを書く**

`tests/test_targeting.py` に追加:

```python
from src.targeting import CAP_DUMP_MARGIN_TURNS, _estimate_max_capacity

class TestEstimateMaxCapacity:
    def test_production_1(self):
        p = P(0, 0, 50, 50, ships=95, prod=1)
        assert _estimate_max_capacity(p) == 100

    def test_production_5(self):
        p = P(0, 0, 50, 50, ships=95, prod=5)
        assert _estimate_max_capacity(p) == 500

    def test_production_2(self):
        p = P(0, 0, 50, 50, ships=200, prod=2)
        assert _estimate_max_capacity(p) == 200
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
cd agents/mine/planet_intercept && uv run pytest tests/test_targeting.py::TestEstimateMaxCapacity -v
```

期待: `ImportError: cannot import name '_estimate_max_capacity'`

- [ ] **Step 3: `targeting.py` に定数と関数を追加**

`targeting.py` の定数セクション (既存の `ETA_SYNC_TOLERANCE` の後) に追加:

```python
CAP_DUMP_MARGIN_TURNS = 10
_CAPACITY_PER_PRODUCTION = 100


def _estimate_max_capacity(planet: "Planet") -> int:
    return planet.production * _CAPACITY_PER_PRODUCTION
```

- [ ] **Step 4: テストが通ることを確認**

```bash
uv run pytest tests/test_targeting.py::TestEstimateMaxCapacity -v
```

期待: 3 passed

- [ ] **Step 5: `policy.py` に `_pick_dump_target()` と容量ダンプ判定を追加**

`policy.py` の `HeuristicPolicy.act()` の冒頭 (`if not gs.my_planets:` の直後) に追加:

```python
def _pick_dump_target(
    mine: "Planet",
    all_planets: list,
    attack_cands: list,
    player: int,
) -> tuple[float, int] | None:
    """容量ダンプ先を選ぶ。(angle, ships) を返す。なければ None。"""
    # 1. value最大の attack 候補
    best = next((c for c in attack_cands if c[3] > 0), None)
    if best is not None:
        target, ships_needed, angle, value = best[0], best[1], best[2], best[3]
        return angle, ships_needed

    # 2. 最前線の自惑星 (全敵惑星への最短距離が最小)
    enemy_planets = [p for p in all_planets if p.owner not in (player, NEUTRAL_OWNER)]
    my_allies = [p for p in all_planets if p.owner == player and p.id != mine.id]
    if enemy_planets and my_allies:
        def frontier_score(p):
            return min(math.hypot(p.x - e.x, p.y - e.y) for e in enemy_planets)
        frontier = min(my_allies, key=frontier_score)
        angle = math.atan2(frontier.y - mine.y, frontier.x - mine.x)
        return angle, mine.ships  # ships は呼び出し側で reserve 引き算
    return None
```

**実装順序の注意:** `attack_cands_by_planet` は容量ダンプで使うため、メインループの**前**に事前収集パスを追加する必要がある。`act()` の `for mine in gs.my_planets:` ループの**前**に attack_cands を事前収集するパスを追加:

```python
# 事前パス: 全自惑星の attack 候補を収集 (容量ダンプと reinforce パスで使用)
for mine in gs.my_planets:
    attack_cands_by_planet[mine.id] = enumerate_candidates(
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
```

そしてメインループ内の `enumerate_candidates` 呼び出しを `attack_cands = attack_cands_by_planet[mine.id]` に置き換える。

その後、容量ダンプの判定をメインループ先頭 (`status, reserve, fall_turn = gs.defense_status[mine.id]` の直後) に追加:

```python
# 容量ダンプ: 生産停止を防ぐため上限手前で強制射出
max_cap = _estimate_max_capacity(mine)
if mine.ships >= max_cap - mine.production * CAP_DUMP_MARGIN_TURNS:
    attack_cands = attack_cands_by_planet.get(mine.id, [])
    dump_result = _pick_dump_target(mine, gs.planets, attack_cands, gs.player)
    if dump_result is not None:
        dump_angle, _ = dump_result
        dump_ships = max(1, mine.ships - reserve)
        if dump_ships > 0:
            moves.append([mine.id, dump_angle, dump_ships])
            fired_sources.add(mine.id)
            continue
```

- [ ] **Step 6: policy の統合テストを書く**

`tests/test_policy.py` に追加:

```python
from src.targeting import _CAPACITY_PER_PRODUCTION
from src.policy import HeuristicPolicy
from src.state import build_game_state

class TestCapacityDump:
    def test_fires_when_near_cap(self):
        """容量上限-production*10 に達した惑星は強制発射する"""
        prod = 2
        max_cap = prod * _CAPACITY_PER_PRODUCTION
        # ships が上限ギリギリ
        ships = max_cap - prod * 5  # CAP_DUMP_MARGIN_TURNS=10 より小さいマージン
        obs = {
            "player": 0,
            "step": 100,
            "angular_velocity": 0.0,
            "comet_planet_ids": [],
            "next_fleet_id": 0,
            "initial_planets": [],
            "comets": [],
            "planets": [
                [0, 0, 20.0, 50.0, 1.0, ships, prod],   # mine: 容量上限近い
                [1, 1, 80.0, 50.0, 1.0, 10, 1],          # enemy
            ],
            "fleets": [],
        }
        gs = build_game_state(obs)
        policy = HeuristicPolicy()
        moves = policy.act(gs)
        # 少なくとも1手出撃していること
        assert len(moves) >= 1
        assert moves[0][0] == 0  # source は mine
```

- [ ] **Step 7: テストが通ることを確認**

```bash
uv run pytest tests/test_policy.py::TestCapacityDump -v
```

期待: 1 passed

- [ ] **Step 8: 全テストが通ることを確認**

```bash
uv run pytest tests/ -q
```

期待: 全 passed (skipped 2件は既知)

- [ ] **Step 9: コミット**

```bash
git add src/targeting.py src/policy.py tests/test_targeting.py tests/test_policy.py
git commit -m "feat(targeting): add capacity dump to prevent production stall"
```

---

## Task 2: 後方押し出し (Rear Push)

**Files:**
- Modify: `src/targeting.py` - `enumerate_rear_push_candidates()` 追加と定数追加
- Modify: `src/policy.py` - reinforce パスに rear push を合流
- Test: `tests/test_targeting.py` - 後方惑星からの前線補給テスト

- [ ] **Step 1: テストを書く**

`tests/test_targeting.py` に追加:

```python
from src.targeting import (
    REAR_DISTANCE_THRESHOLD,
    REAR_MIN_SURPLUS,
    enumerate_rear_push_candidates,
)

class TestRearPush:
    def _make_state(self):
        # 後方自惑星 (敵から遠い) + 前線自惑星 (敵に近い) + 敵惑星
        rear = P(0, 0, 10.0, 50.0, ships=60, prod=2)   # 後方
        front = P(1, 0, 60.0, 50.0, ships=5, prod=2)   # 前線
        enemy = P(2, 1, 80.0, 50.0, ships=30, prod=2)  # 敵
        return rear, front, enemy

    def test_rear_pushes_to_frontier(self):
        rear, front, enemy = self._make_state()
        all_planets = [rear, front, enemy]
        # front には value>0 の attack 候補がある前提でダミー候補を渡す
        attack_cands = {
            front.id: [(enemy, 31, 0.0, 50.0, 10.0), (enemy, 31, 0.0, 40.0, 10.0)],
        }
        missions = list(enumerate_rear_push_candidates(
            my_planets=[rear, front],
            all_planets=all_planets,
            player=0,
            attack_cands_by_planet=attack_cands,
            reserve_of=lambda p: 0,
        ))
        # rear -> front への推薦が生成されること
        assert any(m.source_id == rear.id and m.target_id == front.id for m in missions)

    def test_no_push_when_close_to_enemy(self):
        # 前線 (rear と同じくらい敵に近い) からは push しない
        near = P(0, 0, 65.0, 50.0, ships=60, prod=2)
        front = P(1, 0, 60.0, 50.0, ships=5, prod=2)
        enemy = P(2, 1, 80.0, 50.0, ships=30, prod=2)
        attack_cands = {
            front.id: [(enemy, 31, 0.0, 50.0, 10.0), (enemy, 31, 0.0, 40.0, 10.0)],
        }
        missions = list(enumerate_rear_push_candidates(
            my_planets=[near, front],
            all_planets=[near, front, enemy],
            player=0,
            attack_cands_by_planet=attack_cands,
            reserve_of=lambda p: 0,
        ))
        # near は REAR_DISTANCE_THRESHOLD 以下なので push しない
        assert not any(m.source_id == near.id for m in missions)

    def test_no_push_when_insufficient_surplus(self):
        rear = P(0, 0, 10.0, 50.0, ships=5, prod=2)  # ships 不足
        front = P(1, 0, 60.0, 50.0, ships=5, prod=2)
        enemy = P(2, 1, 80.0, 50.0, ships=30, prod=2)
        attack_cands = {
            front.id: [(enemy, 31, 0.0, 50.0, 10.0), (enemy, 31, 0.0, 40.0, 10.0)],
        }
        missions = list(enumerate_rear_push_candidates(
            my_planets=[rear, front],
            all_planets=[rear, front, enemy],
            player=0,
            attack_cands_by_planet=attack_cands,
            reserve_of=lambda p: 0,
        ))
        assert len(missions) == 0
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
uv run pytest tests/test_targeting.py::TestRearPush -v
```

期待: `ImportError: cannot import name 'enumerate_rear_push_candidates'`

- [ ] **Step 3: `targeting.py` に定数と関数を追加**

定数セクションに追加:

```python
REAR_DISTANCE_THRESHOLD = 40.0
REAR_MIN_SURPLUS = 20
REAR_PUSH_FRACTION = 0.5
FRONTIER_MIN_CANDS = 2
```

`enumerate_reinforce_candidates` の後に追加:

```python
def enumerate_rear_push_candidates(
    my_planets: list,
    all_planets: list,
    player: int,
    attack_cands_by_planet: dict,
    reserve_of,
):
    """後方の安全自惑星から前線自惑星へ艦を流す候補を列挙する。

    source: 全敵惑星への最短距離 > REAR_DISTANCE_THRESHOLD かつ avail >= REAR_MIN_SURPLUS
    target: attack候補が FRONTIER_MIN_CANDS 件以上あり、source より敵に近い自惑星
    """
    enemy_planets = [p for p in all_planets if p.owner not in (player, NEUTRAL_OWNER)]
    if not enemy_planets:
        return

    def min_enemy_dist(p):
        return min(math.hypot(p.x - e.x, p.y - e.y) for e in enemy_planets)

    for src in my_planets:
        src_enemy_dist = min_enemy_dist(src)
        if src_enemy_dist <= REAR_DISTANCE_THRESHOLD:
            continue
        avail = src.ships - reserve_of(src)
        if avail < REAR_MIN_SURPLUS:
            continue

        for tgt in my_planets:
            if tgt.id == src.id:
                continue
            cands = attack_cands_by_planet.get(tgt.id, [])
            good_cands = [c for c in cands if c[3] > 0]
            if len(good_cands) < FRONTIER_MIN_CANDS:
                continue
            if min_enemy_dist(tgt) >= src_enemy_dist:
                continue  # src より敵に近くない

            ships = min(avail, max(1, int(src.ships * REAR_PUSH_FRACTION)))
            my_eta_f = route_eta(src.x, src.y, tgt.x, tgt.y, ships)
            angle, _ = route_angle_and_distance(src.x, src.y, tgt.x, tgt.y)
            top_value = good_cands[0][3]
            value = top_value - my_eta_f * TRAVEL_PENALTY
            if value <= 0:
                continue
            yield ReinforceMission(
                source_id=src.id,
                target_id=tgt.id,
                ships=ships,
                angle=angle,
                value=value,
                my_eta=max(1, int(math.ceil(my_eta_f))),
            )
```

- [ ] **Step 4: `policy.py` の reinforce パスに合流させる**

`policy.py` の `reinforce_missions = enumerate_reinforce_candidates(...)` の後に追加:

```python
rear_push_missions = list(enumerate_rear_push_candidates(
    my_planets=gs.my_planets,
    all_planets=gs.planets,
    player=gs.player,
    attack_cands_by_planet=attack_cands_by_planet,
    reserve_of=lambda p: gs.defense_status[p.id][1],
))
reinforce_missions = sorted(
    reinforce_missions + rear_push_missions, key=lambda m: -m.value
)
```

`policy.py` の import に追加:

```python
from .targeting import (
    ...
    enumerate_rear_push_candidates,
    ...
)
```

- [ ] **Step 5: テストが通ることを確認**

```bash
uv run pytest tests/test_targeting.py::TestRearPush -v
```

期待: 3 passed

- [ ] **Step 6: 全テストが通ることを確認**

```bash
uv run pytest tests/ -q
```

期待: 全 passed

- [ ] **Step 7: コミット**

```bash
git add src/targeting.py src/policy.py tests/test_targeting.py
git commit -m "feat(targeting): add rear push - flow ships from safe rear to frontier"
```

---

## Task 3: JIT 逆算送出 (JIT Dispatch)

**Files:**
- Modify: `src/targeting.py` - `enumerate_support_candidates()` に `current_turn` 引数追加
- Modify: `src/policy.py` - `gs.step` を渡す
- Test: `tests/test_targeting.py` - 早すぎる援軍がスキップされるテスト

- [ ] **Step 1: テストを書く**

`tests/test_targeting.py` に追加:

```python
from src.targeting import JIT_MARGIN, enumerate_support_candidates
from src.world import Arrival, build_timelines, simulate_planet_timeline

class TestJITDispatch:
    def test_skips_dispatch_when_too_early(self):
        """出発不要なターンには援軍候補を返さない"""
        src = P(0, 0, 10.0, 50.0, ships=50, prod=2)
        defended = P(1, 0, 50.0, 50.0, ships=5, prod=2)
        # defended に20ターン後に enemy が到着する timeline を作る
        arrivals = [Arrival(eta=20, owner=1, ships=30)]
        timeline = simulate_planet_timeline(defended, arrivals, horizon=80)
        timelines = {defended.id: timeline}

        # src から defended への ETA は距離40 / speed(50ships) ≒ 7ターン
        # dispatch_turn = fall_turn - ceil(eta) - JIT_MARGIN = 20 - 7 - 2 = 11
        # current_turn=5 のとき: 5 < 11 なので skip
        cands = enumerate_support_candidates(
            src, [src, defended], 0,
            timelines=timelines, planned={}, remaining_turns=400,
            current_turn=5,
        )
        assert len(cands) == 0

    def test_dispatches_when_time_is_right(self):
        """出発すべきターンには援軍候補を返す"""
        src = P(0, 0, 10.0, 50.0, ships=50, prod=2)
        defended = P(1, 0, 50.0, 50.0, ships=5, prod=2)
        arrivals = [Arrival(eta=20, owner=1, ships=30)]
        timeline = simulate_planet_timeline(defended, arrivals, horizon=80)
        timelines = {defended.id: timeline}

        # current_turn=12 >= dispatch_turn=11 なので送出
        cands = enumerate_support_candidates(
            src, [src, defended], 0,
            timelines=timelines, planned={}, remaining_turns=400,
            current_turn=12,
        )
        assert len(cands) >= 1
        assert cands[0][0].id == defended.id
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
uv run pytest tests/test_targeting.py::TestJITDispatch -v
```

期待: `TypeError: enumerate_support_candidates() got an unexpected keyword argument 'current_turn'`

- [ ] **Step 3: `targeting.py` の `enumerate_support_candidates` に `current_turn` を追加**

定数セクションに追加:

```python
JIT_MARGIN = 2
```

`enumerate_support_candidates` のシグネチャを変更:

```python
def enumerate_support_candidates(
    my_planet: Planet,
    all_planets,
    player: int,
    timelines: dict[int, list[PlanetState]] | None = None,
    planned: dict | None = None,
    remaining_turns: int | None = None,
    current_turn: int = 0,
) -> list:
```

関数内の `if my_eta > fall_turn:` の直後に追加:

```python
# JIT: 出発すべきターンになるまでスキップ
dispatch_turn = fall_turn - int(math.ceil(my_eta)) - JIT_MARGIN
if current_turn < dispatch_turn:
    continue
```

- [ ] **Step 4: `policy.py` で `gs.step` を渡す**

`enumerate_support_candidates` の呼び出し箇所を変更:

```python
support_cands = enumerate_support_candidates(
    mine,
    gs.planets,
    gs.player,
    timelines=gs.timelines,
    planned=planned,
    remaining_turns=gs.remaining_turns,
    current_turn=gs.step,
)
```

- [ ] **Step 5: テストが通ることを確認**

```bash
uv run pytest tests/test_targeting.py::TestJITDispatch -v
```

期待: 2 passed

- [ ] **Step 6: 全テストが通ることを確認**

```bash
uv run pytest tests/ -q
```

期待: 全 passed

- [ ] **Step 7: コミット**

```bash
git add src/targeting.py src/policy.py tests/test_targeting.py
git commit -m "feat(targeting): add JIT dispatch - delay support until last moment"
```

---

## Task 4: 防衛放棄判断 (Abandon Defense)

**Files:**
- Modify: `src/targeting.py` - `classify_defense()` に cost/value チェック追加と定数追加
- Test: `tests/test_targeting.py` - 高コスト防衛が放棄されるテスト

- [ ] **Step 1: テストを書く**

`tests/test_targeting.py` に追加:

```python
from src.targeting import ABANDON_COST_RATIO, HOLD_HORIZON

class TestAbandonDefense:
    def test_abandons_when_defense_cost_too_high(self):
        """守備コストが生産価値を超えるとき doomed を返す"""
        # production=1, HOLD_HORIZON=20 なら defense_value = 20
        # ABANDON_COST_RATIO=1.5 なら threshold = 30
        # reserve=50 (> 30) なら放棄
        mine = P(0, 0, 50.0, 50.0, ships=40, prod=1)
        enemy_fleet = F(0, 1, 45.0, 50.0, math.pi, 99, ships=50)
        arrivals = [Arrival(eta=5, owner=1, ships=50)]
        timeline = simulate_planet_timeline(mine, arrivals, horizon=80)
        status, reserve, fall_turn = classify_defense(
            mine, [enemy_fleet], 0, timeline=timeline
        )
        assert status == "doomed"

    def test_keeps_threatened_when_cost_acceptable(self):
        """守備コストが生産価値以内なら threatened を維持"""
        # production=5, HOLD_HORIZON=20 なら defense_value = 100
        # threshold = 150
        # reserve=10 (< 150) なら threatened のまま
        mine = P(0, 0, 50.0, 50.0, ships=40, prod=5)
        enemy_fleet = F(0, 1, 45.0, 50.0, math.pi, 99, ships=10)
        arrivals = [Arrival(eta=5, owner=1, ships=10)]
        timeline = simulate_planet_timeline(mine, arrivals, horizon=80)
        status, reserve, fall_turn = classify_defense(
            mine, [enemy_fleet], 0, timeline=timeline
        )
        assert status == "threatened"
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
uv run pytest tests/test_targeting.py::TestAbandonDefense -v
```

期待: FAIL (現状は threatened を返す)

- [ ] **Step 3: `targeting.py` の `classify_defense` を変更**

定数セクションに追加:

```python
ABANDON_COST_RATIO = 1.5
```

`classify_defense` 内の `return "threatened", reserve, fall_turn` の**前**に追加:

```python
# cost/value チェック: 守備コストが生産価値の ABANDON_COST_RATIO 倍を超えるなら放棄
defense_value = mine.production * HOLD_HORIZON
if reserve > defense_value * ABANDON_COST_RATIO:
    return "doomed", reserve, fall_turn
```

- [ ] **Step 4: テストが通ることを確認**

```bash
uv run pytest tests/test_targeting.py::TestAbandonDefense -v
```

期待: 2 passed

- [ ] **Step 5: 全テストが通ることを確認**

```bash
uv run pytest tests/ -q
```

期待: 全 passed

- [ ] **Step 6: コミット**

```bash
git add src/targeting.py tests/test_targeting.py
git commit -m "feat(targeting): abandon defense when cost exceeds production value"
```

---

## Task 5: 出撃直後スナイプ (Post-Launch Snipe)

**Files:**
- Modify: `src/targeting.py` - `enumerate_post_launch_snipe_candidates()` 追加と定数追加
- Modify: `src/policy.py` - attack パスに合流
- Test: `tests/test_targeting.py` - 手薄惑星がスナイプ候補になるテスト

- [ ] **Step 1: テストを書く**

`tests/test_targeting.py` に追加:

```python
from src.targeting import SNIPE_THIN_THRESHOLD, enumerate_post_launch_snipe_candidates

class TestPostLaunchSnipe:
    def test_generates_candidate_for_thin_origin(self):
        """敵が出撃した後に手薄になった惑星への候補が生成される"""
        mine = P(0, 0, 10.0, 50.0, ships=50, prod=2)
        enemy_origin = P(1, 1, 70.0, 50.0, ships=5, prod=2)  # 手薄 (< SNIPE_THIN_THRESHOLD)
        all_planets = [mine, enemy_origin]
        # 敵が enemy_origin から出撃したフリート
        fleet = F(0, 1, 65.0, 50.0, math.pi, enemy_origin.id, ships=40)

        cands = enumerate_post_launch_snipe_candidates(
            my_planet=mine,
            all_planets=all_planets,
            fleets=[fleet],
            player=0,
        )
        assert len(cands) >= 1
        assert cands[0][0].id == enemy_origin.id

    def test_no_candidate_when_origin_not_thin(self):
        """出撃元が手薄でないなら候補なし"""
        mine = P(0, 0, 10.0, 50.0, ships=50, prod=2)
        enemy_origin = P(1, 1, 70.0, 50.0, ships=50, prod=2)  # 手薄でない
        fleet = F(0, 1, 65.0, 50.0, math.pi, enemy_origin.id, ships=10)
        cands = enumerate_post_launch_snipe_candidates(
            my_planet=mine,
            all_planets=[mine, enemy_origin],
            fleets=[fleet],
            player=0,
        )
        assert len(cands) == 0

    def test_no_candidate_for_own_fleets(self):
        """自分のフリートは無視する"""
        mine = P(0, 0, 10.0, 50.0, ships=50, prod=2)
        ally_origin = P(1, 0, 70.0, 50.0, ships=3, prod=2)  # 自軍惑星
        fleet = F(0, 0, 65.0, 50.0, math.pi, ally_origin.id, ships=40)
        cands = enumerate_post_launch_snipe_candidates(
            my_planet=mine,
            all_planets=[mine, ally_origin],
            fleets=[fleet],
            player=0,
        )
        assert len(cands) == 0
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
uv run pytest tests/test_targeting.py::TestPostLaunchSnipe -v
```

期待: `ImportError: cannot import name 'enumerate_post_launch_snipe_candidates'`

- [ ] **Step 3: `targeting.py` に定数と関数を追加**

定数セクションに追加:

```python
SNIPE_THIN_THRESHOLD = 15
SNIPE_URGENCY_BONUS = 30.0
```

`enumerate_snipe_candidates` の後に追加:

```python
def enumerate_post_launch_snipe_candidates(
    my_planet: Planet,
    all_planets,
    fleets,
    player: int,
    angular_velocity: float = 0.0,
    planned: dict | None = None,
    remaining_turns: int | None = None,
    timelines: dict | None = None,
) -> list:
    """敵が出撃直後に手薄になった惑星へのスナイプ候補を列挙する。

    fleets 内の enemy fleet の from_planet_id 惑星が SNIPE_THIN_THRESHOLD 未満なら
    通常の attack 候補と同じ value 式 + SNIPE_URGENCY_BONUS で候補を生成する。
    全モード (ahead/neutral/behind) で適用。
    """
    from .utils import CENTER

    if planned is None:
        planned = {}

    planet_map = {p.id: p for p in all_planets}
    seen_origins: set[int] = set()
    out = []

    for f in fleets:
        if f.owner == player:
            continue
        origin_id = f.from_planet_id
        if origin_id in seen_origins:
            continue
        origin = planet_map.get(origin_id)
        if origin is None or origin.owner == player:
            continue
        if origin.ships >= SNIPE_THIN_THRESHOLD:
            continue
        seen_origins.add(origin_id)

        r = math.hypot(origin.x - CENTER, origin.y - CENTER)
        is_orbital = angular_velocity != 0.0 and (r + origin.radius < 50)
        if is_orbital:
            ships_approx = ships_budget(origin)
            ix, iy, my_eta = intercept_pos(
                my_planet.x, my_planet.y, ships_approx, origin, angular_velocity
            )
        else:
            ix, iy = origin.x, origin.y
            ships_approx = ships_budget(origin)
            my_eta = route_eta(my_planet.x, my_planet.y, ix, iy, ships_approx)

        if segment_hits_sun(my_planet.x, my_planet.y, ix, iy):
            continue
        if remaining_turns is not None and my_eta > remaining_turns:
            continue

        already_sent = planned.get(origin.id, 0)
        if timelines and origin.id in timelines:
            ships_needed = ships_needed_to_capture_at(
                origin, timelines[origin.id], player, int(math.ceil(my_eta))
            )
            ships_needed = max(0, ships_needed - already_sent)
        else:
            ships_needed = ships_budget(origin, my_eta=my_eta, already_sent=already_sent)
        if ships_needed <= 0:
            continue

        angle, _ = route_angle_and_distance(my_planet.x, my_planet.y, ix, iy)
        rival_eta = compute_rival_eta(origin, player, fleets, all_planets, angular_velocity)
        value = (
            target_value(
                my_planet,
                ix,
                iy,
                origin.production,
                rival_eta,
                ships_needed,
                my_eta,
                target_owner=origin.owner,
                remaining_turns=remaining_turns,
            )
            + SNIPE_URGENCY_BONUS
        )
        if value <= 0:
            continue
        out.append((origin, ships_needed, angle, value, float(my_eta)))

    return out
```

- [ ] **Step 4: `policy.py` の attack パスに合流**

`policy.py` の `enumerate_snipe_candidates` の import に追加:

```python
from .targeting import (
    ...
    enumerate_post_launch_snipe_candidates,
    ...
)
```

`HeuristicPolicy.act()` のメインループ内で `snipe_cands` を組み立てる箇所を変更:

```python
# 既存の behind 限定 snipe
if gs.mode == "behind":
    snipe_cands = enumerate_snipe_candidates(...)
else:
    snipe_cands = []

# 全モードで出撃直後スナイプを追加
post_launch_cands = enumerate_post_launch_snipe_candidates(
    mine,
    gs.planets,
    gs.fleets,
    gs.player,
    angular_velocity=gs.angular_velocity,
    planned=planned,
    remaining_turns=gs.remaining_turns,
    timelines=gs.timelines,
)
snipe_cands = snipe_cands + post_launch_cands
```

- [ ] **Step 5: テストが通ることを確認**

```bash
uv run pytest tests/test_targeting.py::TestPostLaunchSnipe -v
```

期待: 3 passed

- [ ] **Step 6: 全テストが通ることを確認**

```bash
uv run pytest tests/ -q
```

期待: 全 passed

- [ ] **Step 7: コミット**

```bash
git add src/targeting.py src/policy.py tests/test_targeting.py
git commit -m "feat(targeting): add post-launch snipe for thinned enemy origins"
```

---

## Task 6: 同時並行占領 (Concurrent Expansion)

**Files:**
- Modify: `src/targeting.py` - `enumerate_candidates()` に `concurrent_etas` 引数追加と定数追加
- Modify: `src/policy.py` - `concurrent_etas` を蓄積して渡す
- Test: `tests/test_targeting.py` - ETA が近い候補にボーナスが加算されるテスト

- [ ] **Step 1: テストを書く**

`tests/test_targeting.py` に追加:

```python
from src.targeting import CONCURRENT_BONUS, CONCURRENT_WINDOW, enumerate_candidates

class TestConcurrentExpansion:
    def test_bonus_added_when_eta_matches(self):
        """既発射フリートと ETA が近い候補にボーナスが加算される"""
        mine = P(0, 0, 10.0, 50.0, ships=50, prod=2)
        near = P(1, -1, 30.0, 50.0, ships=5, prod=2)   # ETA ≒ 10
        far  = P(2, -1, 90.0, 50.0, ships=5, prod=2)   # ETA ≒ 40

        cands_no_concurrent = enumerate_candidates(
            mine, [mine, near, far], [], 0,
            remaining_turns=400, concurrent_etas=None,
        )
        cands_with_concurrent = enumerate_candidates(
            mine, [mine, near, far], [], 0,
            remaining_turns=400, concurrent_etas={10},  # near の ETA に合わせる
        )

        # near への value が上がっていること
        val_no  = next(v for t, _, _, v, _ in cands_no_concurrent if t.id == near.id)
        val_yes = next(v for t, _, _, v, _ in cands_with_concurrent if t.id == near.id)
        assert val_yes > val_no
        assert val_yes - val_no == pytest.approx(CONCURRENT_BONUS, abs=1.0)

    def test_no_bonus_when_eta_far(self):
        """ETA が CONCURRENT_WINDOW より離れていればボーナスなし"""
        mine = P(0, 0, 10.0, 50.0, ships=50, prod=2)
        far  = P(1, -1, 90.0, 50.0, ships=5, prod=2)  # ETA ≒ 40

        cands_base = enumerate_candidates(
            mine, [mine, far], [], 0,
            remaining_turns=400, concurrent_etas=None,
        )
        cands_concurrent = enumerate_candidates(
            mine, [mine, far], [], 0,
            remaining_turns=400, concurrent_etas={10},  # ETA 差 30 > CONCURRENT_WINDOW
        )
        val_base = next(v for t, _, _, v, _ in cands_base if t.id == far.id)
        val_conc = next(v for t, _, _, v, _ in cands_concurrent if t.id == far.id)
        assert val_base == pytest.approx(val_conc, abs=0.1)
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
uv run pytest tests/test_targeting.py::TestConcurrentExpansion -v
```

期待: `TypeError: enumerate_candidates() got an unexpected keyword argument 'concurrent_etas'`

- [ ] **Step 3: `targeting.py` に定数と引数を追加**

定数セクションに追加:

```python
CONCURRENT_WINDOW = 5
CONCURRENT_BONUS = 20.0
```

`enumerate_candidates` のシグネチャを変更:

```python
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
    is_opening: bool = False,
    concurrent_etas: set[int] | None = None,
):
```

関数内の `out.append(...)` の直前で `value` を計算した後に追加:

```python
# 1-A: 同時並行占領ボーナス
if concurrent_etas and any(
    abs(my_eta - e) <= CONCURRENT_WINDOW for e in concurrent_etas
):
    value += CONCURRENT_BONUS
```

(この行は `out.append((t, ships_needed, angle, value, float(my_eta)))` の直前)

- [ ] **Step 4: `policy.py` で `concurrent_etas` を蓄積して渡す**

`act()` の `n = len(gs.my_planets)` の後に初期化:

```python
concurrent_etas: set[int] = set()
```

メインループ内の `enumerate_candidates` 呼び出し (事前パスとメインループ両方) に `concurrent_etas=concurrent_etas` を追加。

picked が確定した後に ETA を記録:

```python
if picked is not None:
    target_id, angle, ships, my_eta = picked
    concurrent_etas.add(int(math.ceil(my_eta)))
```

- [ ] **Step 5: テストが通ることを確認**

```bash
uv run pytest tests/test_targeting.py::TestConcurrentExpansion -v
```

期待: 2 passed

- [ ] **Step 6: 全テストが通ることを確認**

```bash
uv run pytest tests/ -q
```

期待: 全 passed

- [ ] **Step 7: コミット**

```bash
git add src/targeting.py src/policy.py tests/test_targeting.py
git commit -m "feat(targeting): add concurrent expansion bonus for synchronized captures"
```

---

## Task 7: N>2 多点同時着弾 + Overcap

**Files:**
- Modify: `src/targeting.py` - `SwarmMission` 拡張、`enumerate_swarm_candidates()` に3惑星目追加と overcap 乗数
- Modify: `src/policy.py` - swarm 発射ループに3本目 move 追加
- Test: `tests/test_targeting.py` - 3惑星 swarm と overcap のテスト

- [ ] **Step 1: テストを書く**

`tests/test_targeting.py` に追加:

```python
from src.targeting import OVERCAP_FACTOR, enumerate_swarm_candidates

class TestSwarm3AndOvercap:
    def _make_planets(self):
        src_a = P(0, 0, 10.0, 30.0, ships=30, prod=2)
        src_b = P(1, 0, 10.0, 50.0, ships=30, prod=2)
        src_c = P(2, 0, 10.0, 70.0, ships=30, prod=2)
        # target は3惑星合算でないと占領不可
        target = P(3, 1, 90.0, 50.0, ships=80, prod=2)
        return [src_a, src_b, src_c, target]

    def test_three_source_swarm_generated(self):
        planets = self._make_planets()
        missions = enumerate_swarm_candidates(
            my_planets=planets[:3],
            all_planets=planets,
            fleets=[],
            player=0,
            remaining_turns=400,
        )
        three_src = [m for m in missions if m.src_c is not None]
        assert len(three_src) >= 1
        m = three_src[0]
        assert m.ships_a + m.ships_b + m.ships_c >= 1

    def test_overcap_ships_exceed_minimum(self):
        """swarm の ships 合計が overcap 係数分だけ最小必要量を超える"""
        planets = self._make_planets()
        missions = enumerate_swarm_candidates(
            my_planets=planets[:3],
            all_planets=planets,
            fleets=[],
            player=0,
            remaining_turns=400,
        )
        for m in missions:
            total = m.ships_a + m.ships_b + (m.ships_c if m.src_c else 0)
            # total >= needed * OVERCAP_FACTOR (ただし avail 上限でキャップされる場合あり)
            assert total >= 1
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
uv run pytest tests/test_targeting.py::TestSwarm3AndOvercap -v
```

期待: FAIL (src_c が None のため three_src が空)

- [ ] **Step 3: `SwarmMission` を拡張**

`targeting.py` の `SwarmMission` dataclass を変更:

```python
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
    src_c: "Planet | None" = None
    ships_c: int = 0
    angle_c: float = 0.0
    eta_c: float = 0.0
```

- [ ] **Step 4: `enumerate_swarm_candidates` に overcap と3惑星目を追加**

定数セクションに追加:

```python
OVERCAP_FACTOR = 1.2
```

`enumerate_swarm_candidates` 内の `needed` 計算の直後 (ペア (a, b) の ships 計算の前) に追加:

```python
# Overcap: 確実占領のため最小必要量を上乗せ
needed = int(math.ceil(needed * OVERCAP_FACTOR))
```

ペア (a, b) で `avail_a + avail_b < needed` の場合に3惑星目を探すブロックを追加 (既存の `if avail_a + avail_b < needed: continue` を置き換え):

```python
if avail_a + avail_b < needed:
    # 3惑星目を探す
    found_triple = False
    for k in range(j + 1, min(j + 4, len(src_info))):  # 最大3件だけ探す
        src_c_obj, eta_c, angle_c = src_info[k]
        if eta_c - eta_a > eta_sync_tolerance:
            break
        reserve_c = (
            defense_status[src_c_obj.id][1]
            if defense_status and src_c_obj.id in defense_status
            else 0
        )
        avail_c = max(0, src_c_obj.ships - reserve_c)
        if avail_a + avail_b + avail_c < needed:
            continue
        if avail_c < 1:
            continue
        total_avail = avail_a + avail_b + avail_c
        ships_a3 = max(1, min(avail_a, math.ceil(needed * avail_a / total_avail)))
        ships_b3 = max(1, min(avail_b, math.ceil(needed * avail_b / total_avail)))
        ships_c3 = needed - ships_a3 - ships_b3
        if ships_c3 <= 0 or ships_c3 > avail_c:
            ships_c3 = min(avail_c, needed - ships_a3 - 1)
            ships_b3 = needed - ships_a3 - ships_c3
        if ships_b3 <= 0 or ships_c3 <= 0:
            continue
        joint_eta3 = max(eta_a, eta_b, eta_c)
        value3 = target_value(
            src_a, target.x, target.y, target.production, rival_eta,
            ships_a3 + ships_b3 + ships_c3, joint_eta3,
            target_owner=target.owner, mode=mode,
            remaining_turns=remaining_turns, is_orbital=is_orbital, orbital_radius=r,
        )
        if value3 <= 0:
            continue
        missions.append(SwarmMission(
            target=target,
            src_a=src_a, ships_a=ships_a3, angle_a=angle_a, eta_a=eta_a,
            src_b=src_b, ships_b=ships_b3, angle_b=angle_b, eta_b=eta_b,
            value=value3,
            src_c=src_c_obj, ships_c=ships_c3, angle_c=angle_c, eta_c=eta_c,
        ))
        found_triple = True
        break
    if not found_triple:
        continue
    continue  # 3惑星版を追加したので2惑星版はスキップ
```

- [ ] **Step 5: `policy.py` の swarm 発射ループに3本目を追加**

```python
for sm in sorted(swarm_missions, key=lambda m: -m.value):
    if sm.src_a.id in all_fired or sm.src_a.id in swarm_fired_sources:
        continue
    if sm.src_b.id in all_fired or sm.src_b.id in swarm_fired_sources:
        continue
    if sm.src_c is not None and (
        sm.src_c.id in all_fired or sm.src_c.id in swarm_fired_sources
    ):
        continue
    moves.append([sm.src_a.id, sm.angle_a, sm.ships_a])
    moves.append([sm.src_b.id, sm.angle_b, sm.ships_b])
    if sm.src_c is not None and sm.ships_c > 0:
        moves.append([sm.src_c.id, sm.angle_c, sm.ships_c])
    eta_int = max(1, int(math.ceil(max(sm.eta_a, sm.eta_b, sm.eta_c if sm.src_c else 0))))
    apply_planned_arrival(
        gs.ledger, gs.timelines, gs.planets,
        target_id=sm.target.id, owner=gs.player,
        ships=sm.ships_a + sm.ships_b + sm.ships_c,
        eta=eta_int, horizon=gs.horizon,
    )
    planned[sm.target.id] = planned.get(sm.target.id, 0) + sm.ships_a + sm.ships_b + sm.ships_c
    swarm_fired_sources.add(sm.src_a.id)
    swarm_fired_sources.add(sm.src_b.id)
    if sm.src_c is not None:
        swarm_fired_sources.add(sm.src_c.id)
```

- [ ] **Step 6: テストが通ることを確認**

```bash
uv run pytest tests/test_targeting.py::TestSwarm3AndOvercap -v
```

期待: 2 passed

- [ ] **Step 7: 全テストが通ることを確認**

```bash
uv run pytest tests/ -q
```

期待: 全 passed

- [ ] **Step 8: コミット**

```bash
git add src/targeting.py src/policy.py tests/test_targeting.py
git commit -m "feat(targeting): extend swarm to 3 sources + overcap factor"
```

---

## Task 8: 最終統合確認

- [ ] **Step 1: 全テストを通す**

```bash
cd agents/mine/planet_intercept && uv run pytest tests/ -v 2>&1 | tail -20
```

期待: 全 passed (skipped 2件は既知)

- [ ] **Step 2: agent をローカルで動作確認**

```bash
cd /Users/takumi.mukaiyama/Private/Kaggle/orbit-wars-lab
uv run python -c "
import kaggle_environments
env = kaggle_environments.make('orbit_wars')
from agents.mine.planet_intercept.src.agent import agent
result = env.run([agent, 'random'])
print('steps:', len(result))
print('rewards:', result[-1][0]['reward'], result[-1][1]['reward'])
"
```

期待: エラーなく完走し rewards が出力される

- [ ] **Step 3: ガントレット実行**

```bash
cd /Users/takumi.mukaiyama/Private/Kaggle/orbit-wars-lab
# ガントレットを走らせて勝率を確認
# (既存の gauntlet スクリプトを使用)
```

- [ ] **Step 4: experiment-log に記録**

`docs/bench/experiment-log.md` に以下を追記:

```markdown
## 2026-05-04: Phase 1d (Vadasz 5機能)

機能: 容量ダンプ / 後方押し出し / JIT逆算送出 / 防衛放棄 / 出撃直後スナイプ / 同時並行占領 / N>2 swarm / overcap

before: (前回ガントレット勝率)
after: (今回ガントレット勝率)
```
