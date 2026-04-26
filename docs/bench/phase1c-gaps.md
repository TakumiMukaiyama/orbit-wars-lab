# Phase 1c ロジックギャップ分析

- 作成日: 2026-04-26
- 対象: `agents/mine/planet_intercept` vs 外部エージェント群
- 目的: Phase 1b 計測後にコード比較で発見した「外部エージェントが持ち、mine が欠く」ロジックを列挙し、実装優先度を整理する

---

## サマリ

| 優先度 | ギャップ | 推定効果 | 実装コスト |
|--------|---------|---------|-----------|
| P1 | In-flight Fleet Tracking | 連射抑制 + ships_budget 精度改善 | 小 |
| P2 | Doomed Detection + Evacuation | 落失確定惑星の艦船ロス削減 | 中 |
| P3 | State Machine (behind/ahead) | 攻守切り替えによる安定勝率 | 中 |
| P4 | Snipe Mission | 敵 fleet 到着タイミングの中立先取り | 中 |
| P5 | Crash Exploit | 敵同士衝突の漁夫の利 | 大 |
| P6 | Multi-source Swarm | 複数拠点からの同時着弾 | 大 |
| P7 | Rear-to-Front Logistics | 後方補給流動 | 大 |

**Phase 1c 着手順: P1 → P2 → P3。P4 以降は Phase 2 候補。**

---

## P1: In-flight Fleet Tracking (planned_commitments)

### 何が問題か

`targeting.py` の `ships_budget(target)` は `target.ships + 1` を返すだけ。これは:

1. **ETA 中の production 増分を無視**: 距離 30 の惑星に production=3 があれば、到着 ETA 約 10 ターン分の 30 ships が加算されているはずだが計算に含まない。到着してみたら艦船が足りなかった、という失陥の原因。
2. **既発射 fleet を考慮しない**: 同じターゲットに前のターンで既に fleet を送っていても毎ターン新たに `ships_budget` 分を送ろうとする。目視観察の「連射」問題はこれ。

### 外部実装の参考

**sigmaborov-reinforce** は `planned_commitments: dict[planet_id, list[(arrival_turn, owner, ships)]]` を毎ターン構築し、`ships_needed_to_capture()` がこれを加味して必要艦船を再計算する。

```
# sigmaborov-reinforce/main.py L916-932 (概念)
planned_commitments[target.id].append((arrival_turn, player, ships_sent))

def ships_needed_to_capture(target, my_eta, planned_commitments):
    already_arriving = sum(ships for eta, owner, ships
                           in planned_commitments[target.id]
                           if owner == my_player and eta <= my_eta + ARRIVAL_WINDOW)
    garrison_at_arrival = target.ships + target.production * my_eta
    return max(0, garrison_at_arrival - already_arriving + 1)
```

### mine への実装方針

`agent.py` の `for mine in my_planets` ループ外でターンごとの `planned: dict[int, int]` を初期化し、送出決定のたびに `planned[target.id] += ships_sent` と記録する。

`ships_budget(target, my_eta)` のシグネチャを拡張:

```python
def ships_budget(target, my_eta=0.0, already_sent=0):
    garrison_at_arrival = target.ships + int(target.production * my_eta)
    return max(1, garrison_at_arrival - already_sent + 1)
```

`enumerate_candidates` に `planned` dict を渡し、`already_sent = planned.get(t.id, 0)` として差し引く。

**効果の仮説**: 連射抑制で無駄な小艦フリートが減り、余剰艦を防衛に回せる。ships_budget 精度改善で「到着したが守備が増えて取れない」失敗が減る。

---

## P2: Doomed Detection + Evacuation (撤退)

### 何が問題か

現在の `estimate_reserve` は「向かってくる敵 fleet の合計 ships」を reserve として返すだけ。しかし:

- 敵 fleet が `mine.ships + reserve` より多ければ、その惑星は**確実に失陥する**。
- 失陥確定なのに `reserve` で拘束された艦船はそのまま失われる。
- `select_move` が reserve 不足として攻撃を抑制しても、その reserve は守備に使われず消える。

### 外部実装の参考

**pilkwang** は `live_doomed: set[planet_id]` を毎ターン構築する。

```
# pilkwang/main.py L2274-2993 (概念)
for planet in my_planets:
    incoming_enemy = sum(f.ships for f in enemy_fleets if heading_to(f, planet))
    if incoming_enemy > planet.ships + reserve_margin:
        live_doomed.add(planet.id)
        # → 同惑星から後方の safe_ally に全艦を退避させる
```

**sigmaborov-reinforce** は `doomed_candidates` と `threatened_candidates` を分けて:
- doomed: 今すぐ撤退フリートを送る
- threatened: 防衛支援を要請する

### mine への実装方針

`estimate_reserve` を 2 段階に分ける:

```python
def classify_defense(mine, fleets, player, my_planet_count):
    incoming = sum(f.ships for f in fleets
                   if f.owner != player and fleet_heading_to(f, mine))
    if incoming == 0:
        return "safe", 0
    if mine.ships >= incoming:
        return "threatened", incoming  # 守れる
    return "doomed", incoming          # 守れない
```

`agent.py` で `"doomed"` 判定が出た惑星からは、攻撃候補ではなく「最も近い自惑星への退避フリート」を優先発射する。

**効果の仮説**: 失陥確定の惑星から艦船を逃がすことで、総艦船数の減少を抑えられる。特に 4P で複数方向から攻められるとき有効。

---

## P3: State Machine (behind / ahead / finishing)

### 何が問題か

現在の `select_move` は常に同じロジック (value 最大の候補を 1 つ選ぶ) で動く。自分が大幅劣勢のとき、積極攻撃よりも守備固めが期待値で上回るシチュエーションを考慮していない。

目視観察の「近い動く惑星を狙い続けていたが、はずしかつ取れず死亡」は、劣勢時に攻撃を続けた結果の典型。

### 外部実装の参考

**sigmaborov-reinforce** は `build_modes()` で `domination = (my_total - enemy_total) / (my_total + enemy_total)` を計算し、しきい値を超えたらモードを切り替える。

```
# sigmaborov-reinforce/main.py L993-1021 (概念)
BEHIND_DOMINATION = -0.3
AHEAD_DOMINATION  =  0.3

def build_modes(world):
    dom = (world.my_total - world.enemy_total) / max(1, world.my_total + world.enemy_total)
    return {
        "is_behind":      dom < BEHIND_DOMINATION,
        "is_ahead":       dom > AHEAD_DOMINATION,
        "attack_margin":  0.8 if dom < BEHIND_DOMINATION else 1.2,
    }
```

- **behind モード**: 中立惑星優先、attack_margin を下げて艦船消費を抑える
- **ahead モード**: 積極的な敵本星攻撃、attack_margin を上げてダメージ重視
- **finishing モード**: 残敵惑星への集中

### mine への実装方針

`agent.py` の先頭でゲーム状態サマリを計算:

```python
my_total = sum(p.ships for p in my_planets) + sum(f.ships for f in fleets if f.owner == player)
enemy_total = sum(p.ships for p in planets if p.owner not in (player, -1)) + \
              sum(f.ships for f in fleets if f.owner not in (player, -1))
dom = (my_total - enemy_total) / max(1, my_total + enemy_total)
mode = "behind" if dom < -0.3 else "ahead" if dom > 0.3 else "neutral"
```

`target_value` と `ships_budget` に `mode` を渡し、behind では `HOLD_HORIZON` を小さくして無謀な中立攻略を抑制する。

**効果の仮説**: 4P で特に有効。2P では sigmaborov-reinforce 相手に自スコア 0 が続いている根本原因の一部がここにある可能性。

---

## P4: Snipe Mission (敵 fleet 到着タイミングの中立先取り)

### 何か

中立惑星に敵 fleet が向かっている場合、敵到着直前 (ETA - 1 以内) にこちらが先着して占領できると、敵 fleet を吸収できる。

### 外部実装の参考

**sigmaborov-reinforce** の `build_snipe_mission()` (L1182-1256) は、中立惑星への敵 fleet ETA 一覧を取得し、自分の ETA が敵 ETA より早い場合にだけ snipe 候補として列挙する。

### mine への実装方針

`enumerate_candidates` の中立惑星評価に「敵 fleet が向かっているなら ETA を比較して bonus value を付加」する形で組み込める。P1 の planned_commitments 完成後に実装しやすい。

---

## P5: Crash Exploit (敵同士衝突の利用)

### 何か

複数の敵プレイヤーの fleet が同一惑星に近い ETA で到着する場合、戦闘ルール上「最大勢力 vs 2位勢力の差分のみ残る」ため、衝突後の惑星は少数艦で奪取できる。

### 外部実装の参考

**sigmaborov-reinforce** の `detect_enemy_crashes()` (L643-687) は `arrivals_by_planet` で複数敵の到着 ETA を比較し、±`eta_window` ターン以内に 2 人以上の敵が到着する惑星を候補にする。

### mine への実装方針

P1 の `planned_commitments` と P3 の state machine が完成した後に実装する。4P でのみ意味がある。

---

## P6: Multi-source Swarm (複数拠点からの同時着弾)

### 何か

1 つの惑星から送る艦船が足りなくても、複数の自惑星から同タイミングで到着させることで占領できる。

### 外部実装の参考

**sigmaborov-reinforce** (L1549-1656) は ETA 許容差 (例: ±3 ターン) 以内に到着する拠点の組み合わせを探索し、合算 ships が `ships_budget` を超える組み合わせを選択する。

### mine への実装方針

現在の `for mine in my_planets` ループは各惑星を独立に扱う。協調を入れるには惑星間の候補をマージする設計変更が必要で、実装コストが大きい。Phase 2 の Greedy rollout フレームワークに自然に組み込める。

---

## P7: Rear-to-Front Logistics (後方補給流動)

### 何か

前線から遠い自惑星 (後方) に艦船が溜まっていても、攻撃候補を持ちにくいため無駄に蓄積する。この余剰艦を前線惑星に流動させることで、前線の火力を維持する。

### 外部実装の参考

**sigmaborov-reinforce** と **pilkwang** はともに `frontier_distance` (各自惑星と前線との距離) を計算し、後方惑星に溜まった余剰艦を前線に転送する処理を持つ。

2P と 4P でそれぞれ異なる `REAR_SEND_RATIO` を使っている。

### mine への実装方針

Phase 1c では簡易版として、自惑星の ships が `reserve * REAR_THRESHOLD` を超えたとき、最前線の自惑星に転送するアクションを候補に追加する形で入れられる。

---

## Phase 1c 実装ロードマップ

```
[P1] In-flight Fleet Tracking
  - targeting.py: ships_budget(target, my_eta, already_sent)
  - agent.py: planned dict の管理
  - tests/test_targeting.py: 追加テスト
  推定工数: 1-2h

[P2] Doomed Detection + Evacuation
  - targeting.py: classify_defense() 追加
  - agent.py: doomed 判定で撤退フリート優先
  推定工数: 2-3h

[P3] State Machine
  - agent.py: domination 計算、mode 判定
  - targeting.py: HOLD_HORIZON を mode 連動に
  推定工数: 1-2h

[計測] 2P gauntlet 10試合 + 4P gauntlet 3試合
  - P1 後: smoke → 本計測
  - P2 後: smoke → 本計測
  - P3 後: smoke → 本計測 (前フェーズ比で確認)
```

各実装後に smoke test (2P 2試合/対戦相手) → クラッシュゼロを確認してから本計測に進む。計測起点は直前フェーズの TrueSkill スナップショット。

---

## 参考: 外部エージェント別ロジック有無

| ロジック | pilkwang | sigmaborov-r | tamrazov | yuriygreben | mine |
|---------|---------|-------------|---------|------------|------|
| In-flight tracking | - | L916-1712 | - | - | **なし** |
| Doomed evacuation | L2274-2993 | L810-849 | - | - | **なし** |
| State machine | L allow_phase | L993-1021 | - | - | **なし** |
| Snipe mission | - | L1182-1256 | - | - | **なし** |
| Crash exploit | - | L1342-1406 | - | - | **なし** |
| Multi-source swarm | - | L1549-1656 | - | - | **なし** |
| Rear logistics | L3022-3074 | L1916-1987 | - | - | **なし** |
| Sun avoidance | - | - | partial | - | **あり** |
| Orbital intercept | - | - | - | - | **あり** |
| Fleet intercept | - | partial | - | - | **あり** |
