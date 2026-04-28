# P5確定 + P6 forward-sim board_value 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A/Bテストで判明した P5 の相手依存性に決着をつけ、Phase 0 最後の施策 P6 (forward-sim board_value) を実装することで、「hold_turns ベースの価値評価」を導入し相手依存の揺らぎを削減する。

**Architecture:**
- `world.py` に `estimate_hold_turns()` を追加: `estimate_snipe_outcome()` の hold_turns 計算を汎用化
- `targeting.py` の `enumerate_candidates()` に P6 パス (timeline あり かつ 静止惑星) を追加し、`rival_eta` ベースの `target_value()` を `hold_turns` ベースに差し替える
- 軌道惑星は引き続き `target_value()` にフォールバック (timeline と intercept_pos の時刻整合性が複雑なため)

**Tech Stack:** Python 3.13, uv, pytest

---

## ファイルマップ

| ファイル | 変更内容 |
|---------|---------|
| `src/targeting.py:41` | Task 1: `CENTRAL_BONUS_MAX` の最終値を確定 |
| `src/world.py` | Task 2: `estimate_hold_turns()` を追加 |
| `src/targeting.py:19-25, 323-395` | Task 3: import 追加 + `enumerate_candidates` に P6 パス追加 |
| `tests/test_world.py` | Task 2: `TestEstimateHoldTurns` を追加 |
| `tests/test_targeting.py` | Task 3: `TestEnumerateCandidatesP6` を追加 |

---

## Task 1: P5 最終確定とコミット

**概要:** A/B テスト結果 (全体 -1.1pp、相手依存) に基づき `CENTRAL_BONUS_MAX` の値を確定してコミット。3 つの選択肢から 1 つを選ぶ。

**Files:**
- Modify: `agents/mine/planet_intercept/src/targeting.py:41`

- [ ] **Step 1: CENTRAL_BONUS_MAX を 40.0 (元値) に戻す**

`targeting.py:41` を以下に書き換える:

```python
CENTRAL_BONUS_MAX = 40.0  # 中心 (r=0) での最大加点
```

- [ ] **Step 2: コミット**

```bash
git add agents/mine/planet_intercept/src/targeting.py
git commit -m "feat(targeting): P5 CENTRAL_BONUS_MAX finalized to <選択値>"
```

---

## Task 2: world.py に estimate_hold_turns() を追加

**概要:** `estimate_snipe_outcome()` の hold_turns 計算を `enumerate_candidates` 汎用の関数として分離する。「my_eta ターンに自分が占領したと仮定し、その後いつ失陥するか」をタイムラインから求める。

**Files:**
- Modify: `agents/mine/planet_intercept/src/world.py` (新関数追加)
- Test: `agents/mine/planet_intercept/tests/test_world.py`

- [ ] **Step 1: 失敗テストを書く**

`tests/test_world.py` に以下を追加:

```python
from src.world import estimate_hold_turns, PlanetState


class TestEstimateHoldTurns:
    def test_no_enemy_holds_full_horizon(self):
        timeline = [PlanetState(turn=t, owner=0, ships=5) for t in range(1, 81)]
        assert estimate_hold_turns(timeline, player=0, my_eta=10, horizon=80) == 70

    def test_enemy_arrives_at_turn_20(self):
        timeline = (
            [PlanetState(turn=t, owner=0, ships=5) for t in range(1, 20)]
            + [PlanetState(turn=t, owner=1, ships=3) for t in range(20, 81)]
        )
        # turn 20 で敵占領, my_eta=10 → hold = 20 - 10 = 10
        assert estimate_hold_turns(timeline, player=0, my_eta=10, horizon=80) == 10

    def test_enemy_before_my_eta_is_skipped(self):
        # turn 5 で敵占領だが my_eta=15 → turn 5 は my_eta 以前なのでスキップ
        # → hold = horizon - my_eta = 80 - 15 = 65
        timeline = (
            [PlanetState(turn=t, owner=0, ships=5) for t in range(1, 5)]
            + [PlanetState(turn=t, owner=1, ships=3) for t in range(5, 81)]
        )
        assert estimate_hold_turns(timeline, player=0, my_eta=15, horizon=80) == 65

    def test_my_eta_at_horizon_returns_zero(self):
        timeline = [PlanetState(turn=t, owner=0, ships=5) for t in range(1, 81)]
        assert estimate_hold_turns(timeline, player=0, my_eta=80, horizon=80) == 0

    def test_neutral_owner_not_counted_as_loss(self):
        # 中立 (owner=-1) は「失陥」とみなさない
        timeline = (
            [PlanetState(turn=t, owner=0, ships=5) for t in range(1, 30)]
            + [PlanetState(turn=t, owner=-1, ships=0) for t in range(30, 81)]
        )
        assert estimate_hold_turns(timeline, player=0, my_eta=10, horizon=80) == 70
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
cd agents/mine/planet_intercept && uv run pytest tests/test_world.py::TestEstimateHoldTurns -v
```

期待: `ImportError` または `AttributeError` (関数未定義)

- [ ] **Step 3: world.py に estimate_hold_turns を追加**

`world.py` の `estimate_snipe_outcome` 定義の直前 (行 224 の手前) に以下を追加:

```python
def estimate_hold_turns(
    timeline: list[PlanetState],
    player: int,
    my_eta: int,
    horizon: int,
) -> int:
    """my_eta ターン後に player が占領した場合の保持ターン数を推定する。

    timeline を my_eta ターン以降でスキャンし、非 player かつ非中立の owner が
    最初に現れたターンを失陥ターンとみなす。
    敵が来なければ horizon - my_eta を返す。
    """
    for s in timeline:
        if s.turn <= my_eta:
            continue
        if s.owner not in (player, NEUTRAL_OWNER):
            return max(0, s.turn - my_eta)
    return max(0, horizon - my_eta)
```

- [ ] **Step 4: テストが通ることを確認**

```bash
cd agents/mine/planet_intercept && uv run pytest tests/test_world.py::TestEstimateHoldTurns -v
```

期待: 全 PASS

- [ ] **Step 5: 全テストが通ることを確認**

```bash
cd agents/mine/planet_intercept && uv run pytest -v
```

期待: 全 PASS

- [ ] **Step 6: コミット**

```bash
git add agents/mine/planet_intercept/src/world.py agents/mine/planet_intercept/tests/test_world.py
git commit -m "feat(world): add estimate_hold_turns for P6 board_value integration"
```

---

## Task 3: targeting.py に P6 timeline-based value を統合

**概要:** `enumerate_candidates()` の value 計算を、静止惑星かつ timeline あり の場合は `estimate_hold_turns()` ベースに差し替える。`rival_eta` ベースの `target_value()` は軌道惑星と timeline なし 時のフォールバックとして残す。既存の P2 (overextend_factor), P3 (focus_bonus), P5 (central_bonus) はそのまま引き継ぐ。

**Files:**
- Modify: `agents/mine/planet_intercept/src/targeting.py` (import追加, enumerate_candidates修正)
- Test: `agents/mine/planet_intercept/tests/test_targeting.py`

- [ ] **Step 1: 失敗テストを書く**

`tests/test_targeting.py` に以下のクラスを追加:

```python
import math
from src.world import PlanetState


class TestEnumerateCandidatesP6:
    def test_long_hold_gives_positive_value(self):
        """敵が来ない timeline では正の value を返す"""
        mine = P(0, 0, 0, 0, ships=50)
        target = P(1, 1, 10, 0, ships=1, prod=3)
        planets = [mine, target]
        long_hold = [PlanetState(turn=t, owner=0, ships=3) for t in range(1, 81)]

        cands = enumerate_candidates(
            mine, planets, fleets=[], player=0,
            timelines={1: long_hold}, remaining_turns=500,
        )
        assert any(c[0].id == 1 and c[3] > 0 for c in cands)

    def test_short_hold_has_lower_value_than_long_hold(self):
        """敵がすぐ来る timeline は敵が来ない timeline より value が低い"""
        mine = P(0, 0, 0, 0, ships=50)
        target = P(1, 1, 10, 0, ships=1, prod=3)
        planets = [mine, target]

        # my_eta ≈ 10 (distance=10, speed≈1.0); 敵が turn 12 で来る = hold ≈ 2
        short_hold = [
            PlanetState(turn=t, owner=(1 if t >= 12 else 0), ships=3)
            for t in range(1, 81)
        ]
        long_hold = [PlanetState(turn=t, owner=0, ships=3) for t in range(1, 81)]

        cands_short = enumerate_candidates(
            mine, planets, fleets=[], player=0,
            timelines={1: short_hold}, remaining_turns=500,
        )
        cands_long = enumerate_candidates(
            mine, planets, fleets=[], player=0,
            timelines={1: long_hold}, remaining_turns=500,
        )
        val_short = next((c[3] for c in cands_short if c[0].id == 1), None)
        val_long = next((c[3] for c in cands_long if c[0].id == 1), None)
        # short は除外されるか、または long より低い
        if val_short is not None and val_long is not None:
            assert val_short < val_long
        else:
            # short が除外 (hold=0) される場合も正しい動作
            assert val_long is not None

    def test_hold_zero_excluded_from_candidates(self):
        """hold_turns=0 の惑星は候補から除外される"""
        mine = P(0, 0, 0, 0, ships=50)
        # distance=10 → my_eta ≈ 10; enemy at turn 10 → hold = 0
        target = P(1, 1, 10, 0, ships=1, prod=3)
        planets = [mine, target]
        instant_loss = [
            PlanetState(turn=t, owner=(1 if t >= 10 else 0), ships=3)
            for t in range(1, 81)
        ]
        cands = enumerate_candidates(
            mine, planets, fleets=[], player=0,
            timelines={1: instant_loss}, remaining_turns=500,
        )
        # hold=0 なので候補から除外
        assert all(c[0].id != 1 for c in cands)
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
cd agents/mine/planet_intercept && uv run pytest tests/test_targeting.py::TestEnumerateCandidatesP6 -v
```

期待: 全 FAIL (P6 パスがまだ存在しない)

- [ ] **Step 3: targeting.py の import を更新**

`targeting.py` 19〜25 行目の `.world` import に `estimate_hold_turns` を追加:

```python
from .world import (
    PlanetState,
    estimate_hold_turns,
    estimate_snipe_outcome,
    first_turn_lost,
    ships_needed_to_capture_at,
    state_at,
)
```

- [ ] **Step 4: enumerate_candidates に elapsed_turns と P6 パスを追加**

`targeting.py` の `enumerate_candidates()` 関数本体 (targets ループの直前) に `elapsed_turns` の計算を追加:

```python
elapsed_turns = (500 - remaining_turns) if remaining_turns is not None else 500
```

続いて、ループ内の `rival_eta` 計算と `out.append` の間 (行 376〜395) を以下に差し替える:

```python
        rival_eta = compute_rival_eta(t, player, fleets, all_planets, angular_velocity)
        focus_planned = int(planned.get(t.id, 0)) if planned else 0

        # P6: timeline ベースの hold_turns 価値計算 (静止惑星のみ)
        if timelines and t.id in timelines and not is_orbital:
            _horizon = max(1, min(80, remaining_turns)) if remaining_turns is not None else 80
            hold = estimate_hold_turns(
                timelines[t.id], player, int(math.ceil(my_eta)), _horizon
            )
            if hold <= 0:
                continue
            factor = (
                _overextend_factor(my_planet_count, domination)
                if t.owner == NEUTRAL_OWNER
                else 1.0
            )
            _opening_bonus = STATIC_HIGH_PROD_BONUS if t.production >= 4 else 0.0
            _central_bonus = 0.0
            if t.owner == NEUTRAL_OWNER and elapsed_turns <= CENTRAL_OPENING_TURNS and r < CENTRAL_REF_RADIUS:
                _central_bonus = CENTRAL_BONUS_MAX * (1.0 - r / CENTRAL_REF_RADIUS)
            _focus_bonus = FOCUS_BONUS_PER_PLANNED_SHIP * max(0, int(focus_planned))
            value = (
                t.production * hold * factor
                + _opening_bonus
                + _central_bonus
                + _focus_bonus
                - ships_needed
                - my_eta * TRAVEL_PENALTY
            )
        else:
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
```

- [ ] **Step 5: テストが通ることを確認**

```bash
cd agents/mine/planet_intercept && uv run pytest tests/test_targeting.py::TestEnumerateCandidatesP6 -v
```

期待: 全 PASS

- [ ] **Step 6: 既存テスト全通を確認**

```bash
cd agents/mine/planet_intercept && uv run pytest -v
```

期待: 全 PASS

- [ ] **Step 7: コミット**

```bash
git add agents/mine/planet_intercept/src/targeting.py agents/mine/planet_intercept/tests/test_targeting.py
git commit -m "feat(targeting): P6 forward-sim board_value via estimate_hold_turns"
```

---

## Task 4: gauntlet 計測チェックポイント

**概要:** P6 実装後の gauntlet を実施し、baseline (run 024: WR 58.9%) との差分を記録する。

**Files:**
- Read: `runs/trueskill.json` または gauntlet 出力ログ

- [ ] **Step 1: 全テストが通ることを最終確認**

```bash
cd agents/mine/planet_intercept && uv run pytest -v
```

- [ ] **Step 2: gauntlet 実施**

```bash
cd /Users/takumi.mukaiyama/Private/Kaggle/orbit-wars-lab
uv run python scripts/gauntlet.py --agent mine/planet_intercept --rounds 10 --seed 42
```

- [ ] **Step 3: 結果を experiment-log.md に記録**

`docs/bench/experiment-log.md` の末尾に以下の形式で追記:

```markdown
### P6 (採用/不採用): forward-sim board_value
- 変更: estimate_hold_turns で静止惑星の value を hold_turns ベースに変更
- 結果: XX/90 (XX%), ベースライン比 +/-X.Xpt
- (採用 or リバート: `git revert <hash>`)
```

- [ ] **Step 4: 劣化した場合はリバート**

WR が run024 (58.9%) より -2pp 以上低下したらリバート:

```bash
git revert HEAD  # Task 3 のコミットをリバート
```

---

## (Optional) Task 5: Backlog P1-A - enumerate_reinforce_candidates

**概要:** implementation-backlog.md の P1-A。遊兵化した後方自惑星から最前線自惑星へ艦船を移送する候補を列挙する。リスク: 前線惑星に過剰艦船が集まり迎撃コストが跳ね上がる可能性があるため、**P6 の計測結果が +2pp 以上でなければスキップ推奨**。

`enumerate_support_candidates()` の条件を緩和し、「fall_turn のない自惑星 (safe)」でも ships が多い場合に前線への移送を候補に追加する実装。詳細設計は P6 計測後に議論。

---

## 検証方法まとめ

```bash
# ユニットテスト
cd agents/mine/planet_intercept && uv run pytest -v

# gauntlet (2P round-robin × 10 × seed=42)
cd /Users/takumi.mukaiyama/Private/Kaggle/orbit-wars-lab
uv run python scripts/gauntlet.py --agent mine/planet_intercept --rounds 10 --seed 42
```

改善判断基準:
- +2pp 以上: 採用
- -2pp 以下: リバート (`git revert`)
- それ以外: 追加計測 (rounds=20) で判断
