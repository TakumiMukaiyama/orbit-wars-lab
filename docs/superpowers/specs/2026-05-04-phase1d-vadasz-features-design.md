# Phase 1d: Vadasz 観察由来の5機能追加 設計

- 作成日: 2026-05-04
- 背景: LB1位 Vadasz の3試合リプレイをリバースエンジニアリングし、既実装との差分を特定
- 対象ファイル: `agents/mine/planet_intercept/src/targeting.py`, `policy.py`, `state.py`

## 0. 分析サマリー

Vadasz (submission 52287189, episodes 75807867 / 75828575 / 75828874) の行動を計測した結果:

| 指標 | 値 |
|------|----|
| 平均ゲーム長 | 134 / 173 / 126 ターン (500ターン前に全制圧) |
| 1ターンあたり平均フリート数 | 1.6-1.9 |
| フェーズ別ターゲット比率 (early/mid/late) | neut 77%/30%/10%, enemy 21%/39%/67% |
| 自惑星への移送比率 | 2% / 32% / 23% (中盤以降に logistics flow が顕在化) |

既実装との照合:

| 提案機能 | 既実装状況 | 追加差分 |
|---------|-----------|---------|
| 1. ROI最大化 | target_value(), expand_priority_score() あり | 同時並行占領・rival 合算 |
| 2. JIT防衛 | classify_defense(), enumerate_support_candidates() あり | 逆算送出・防衛放棄判断 |
| 3. 同時着弾 | enumerate_swarm_candidates() (2惑星) あり | N>2 拡張・overcap |
| 4. ロジスティクス | enumerate_reinforce_candidates() あり | 後方押し出し・容量ダンプ・玉突き |
| 5. 弱点露出 | enumerate_snipe_candidates() (behind限定) あり | 出撃直後スナイプ・ブリッジ優先 |

---

## 1. ROI最大化

### 1-A: 同時並行占領 (Concurrent Expansion)

**課題:** 各 `mine` 惑星が独立して value 最大候補を選ぶため、「A と B を同じターンに占領完了」する協調がない。

**実装:**
`enumerate_candidates()` に `concurrent_etas: set[int]` 引数を追加。今ターン既に発射済みフリートの ETA セットを渡し、候補の `my_eta` が近いときボーナスを加算する。

```python
# targeting.py enumerate_candidates() に引数追加
def enumerate_candidates(..., concurrent_etas: set[int] | None = None):
    ...
    for t in targets:
        ...
        if concurrent_etas:
            if any(abs(my_eta - e) <= CONCURRENT_WINDOW for e in concurrent_etas):
                value += CONCURRENT_BONUS
```

`policy.py` のループで `concurrent_etas` を蓄積して渡す:
```python
concurrent_etas: set[int] = set()
for mine in gs.my_planets:
    ...
    cands = enumerate_candidates(..., concurrent_etas=concurrent_etas)
    ...
    if picked:
        concurrent_etas.add(int(math.ceil(my_eta)))
```

定数:
- `CONCURRENT_WINDOW = 5` (ターン)
- `CONCURRENT_BONUS = 20.0`

---

### 1-B: Rival 合算の確認・補完

**課題:** `compute_rival_eta` は最速 1 プレイヤーの ETA のみ返す。複数 rival fleet が合算着弾するケースで必要艦数が過小評価される可能性がある。

**実装:** `state.py` の `build_game_state()` で enemy fleet の到着が `timelines` / `ledger` に全数反映されているか確認。反映済みであれば `ships_needed_to_capture_at()` は自動的に合算を考慮するため追加実装不要。未反映の場合は `_apply_fleet_arrivals()` に enemy fleet を追加する。

検証方法: `tests/test_state.py` に「同一ターゲットへ2本の enemy fleet が向かうケース」のテストを追加して確認。

---

## 2. JIT防衛

### 2-A: 逆算送出 (JIT Dispatch)

**課題:** `enumerate_support_candidates()` は `my_eta <= fall_turn` なら即送出。ギリギリまで手元に置いて他の攻撃に使う最適化がない。

**実装:** `enumerate_support_candidates()` に `current_turn: int` 引数を追加。

```python
def enumerate_support_candidates(..., current_turn: int = 0):
    ...
    # 出発すべきターン = fall_turn - ceil(my_eta) - JIT_MARGIN
    dispatch_turn = fall_turn - int(math.ceil(my_eta)) - JIT_MARGIN
    if current_turn < dispatch_turn:
        continue  # まだ出発不要
    ...
```

`policy.py` から `gs.step` を渡す。

定数:
- `JIT_MARGIN = 2` (推定誤差バッファ、ターン)

---

### 2-B: 防衛放棄の cost/value 判断

**課題:** threatened 状態でも「守るコストが生産性に見合わない」場合は doomed 扱いにして全艦避難すべきケースがある。

**実装:** `classify_defense()` 内で threatened 判定後に cost/value チェックを追加。

```python
# classify_defense() 内
if status == "threatened":
    defense_cost = reserve  # 守備に必要な艦数
    defense_value = mine.production * HOLD_HORIZON
    if defense_cost > defense_value * ABANDON_COST_RATIO:
        return "doomed", reserve, fall_turn
```

定数:
- `ABANDON_COST_RATIO = 1.5`

---

## 3. タイム・シンクロナイズ

### 3-A: N>2 多点同時着弾

**課題:** `enumerate_swarm_candidates()` は 2 惑星ペアのみ。3 惑星合算でないと占領できないターゲットに対応できない。

**実装:** `SwarmMission` を拡張し `src_c` (Optional) フィールドを追加。2 惑星で `needed` に届かない場合に 3 惑星目を探す。

```python
@dataclass
class SwarmMission:
    ...
    src_c: "Planet | None" = None
    ships_c: int = 0
    angle_c: float = 0.0
    eta_c: float = 0.0
```

`enumerate_swarm_candidates()` 内:
```python
if avail_a + avail_b < needed:
    # 3惑星目を探す
    for src_c, eta_c, angle_c in src_info[j+1:]:
        if eta_c - eta_a > eta_sync_tolerance:
            break
        avail_c = max(0, src_c.ships - reserve_c)
        if avail_a + avail_b + avail_c >= needed:
            # SwarmMission3 として追加
            ...
            break
```

計算量抑制: `available_sources` を `min(8, len(available_sources))` に上限設定。

`policy.py` の swarm 発射ループに `src_c` があれば3本目の move を追加。

---

### 3-B: Overcap アタック

**課題:** `ships_needed` は最小必要量。敵の増産・微量援軍を無視して確実に占領するための積み増しがない。

**実装:** `enumerate_swarm_candidates()` 内の `needed` 計算に乗数を適用。通常の単独攻撃は変えず swarm 時のみ適用。

```python
# swarm 内の needed 計算後
needed = int(math.ceil(needed * OVERCAP_FACTOR))
```

定数:
- `OVERCAP_FACTOR = 1.2`

---

## 4. ロジスティクス・パイプライン

### 4-A: 後方押し出し (Rear Push)

**課題:** reinforce は「attack不足惑星への補給」。後方の安全惑星が自発的に前線へ流す動作がない。

**実装:** `targeting.py` に `enumerate_rear_push_candidates()` を新設。

```python
def enumerate_rear_push_candidates(
    my_planets,
    all_planets,
    player: int,
    attack_cands_by_planet: dict,
    timelines: dict,
    reserve_of,
) -> Iterator[ReinforceMission]:
    enemy_planets = [p for p in all_planets if p.owner not in (player, NEUTRAL_OWNER)]

    for src in my_planets:
        # source: 全敵惑星への最短距離が閾値より遠い後方惑星
        min_enemy_dist = min(
            (math.hypot(src.x - e.x, src.y - e.y) for e in enemy_planets),
            default=math.inf,
        )
        if min_enemy_dist <= REAR_DISTANCE_THRESHOLD:
            continue
        avail = src.ships - reserve_of(src)
        if avail < REAR_MIN_SURPLUS:
            continue

        # target: attack候補が豊富な前線惑星
        for tgt in my_planets:
            if tgt.id == src.id:
                continue
            cands = attack_cands_by_planet.get(tgt.id, [])
            good_cands = [c for c in cands if c[3] > 0]
            if len(good_cands) < FRONTIER_MIN_CANDS:
                continue
            tgt_enemy_dist = min(
                (math.hypot(tgt.x - e.x, tgt.y - e.y) for e in enemy_planets),
                default=math.inf,
            )
            if tgt_enemy_dist >= min_enemy_dist:
                continue  # src より敵に近くない

            ships = min(avail, int(src.ships * REAR_PUSH_FRACTION))
            if ships <= 0:
                continue
            my_eta_f = route_eta(src.x, src.y, tgt.x, tgt.y, ships)
            angle, _ = route_angle_and_distance(src.x, src.y, tgt.x, tgt.y)
            top_value = good_cands[0][3]
            value = top_value - my_eta_f * TRAVEL_PENALTY
            if value <= 0:
                continue
            yield ReinforceMission(
                source_id=src.id, target_id=tgt.id, ships=ships,
                angle=angle, value=value, my_eta=max(1, int(math.ceil(my_eta_f))),
            )
```

`policy.py` の reinforce パスに追加:
```python
rear_push = list(enumerate_rear_push_candidates(...))
reinforce_missions = sorted(reinforce_missions + rear_push, key=lambda m: -m.value)
```

定数:
- `REAR_DISTANCE_THRESHOLD = 40.0`
- `REAR_MIN_SURPLUS = 20`
- `REAR_PUSH_FRACTION = 0.5`
- `FRONTIER_MIN_CANDS = 2`

---

### 4-B: 容量ダンプ (Capacity Dump)

**課題:** 惑星が max_capacity に達すると生産停止するが強制射出がない。

**前提確認:** `Planet` dataclass に `max_capacity` フィールドが存在するか、`state.py` / `utils.py` で確認。observation の planet 配列は `[id, owner, x, y, radius, ships, production]` の7フィールドで capacity は別途取得が必要。`initial_planets` と現在 `planets` を照合して radius から capacity を推定する必要がある可能性あり。

**実装:** `policy.py` の各 mine 惑星ループ先頭に追加。

```python
# capacity に近づいたら強制発射
if hasattr(mine, 'max_capacity') and mine.ships >= mine.max_capacity - mine.production * CAP_DUMP_MARGIN_TURNS:
    dump_target = _pick_dump_target(mine, gs)
    if dump_target is not None:
        moves.append([mine.id, dump_target.angle, mine.ships - reserve])
        continue
```

`_pick_dump_target(mine, gs)`: `attack_cands_by_planet[mine.id]` の value 最大ターゲット、なければ `gs.my_planets` の中で全敵惑星への最短距離が最小の惑星 (最前線)、なければ最寄り自惑星を返す。`policy.py` のローカル関数として定義。

定数:
- `CAP_DUMP_MARGIN_TURNS = 10`

---

### 4-C: 玉突き輸送 (Relay Transport) [段階実装]

**課題:** A から敵地への直線フリートのみ。A → B (前線自惑星) → 敵地の中継で B の防衛力を一時強化できる。

**段階実装方針:** 4-A / 4-B を先に投入してガントレットで効果確認後に実装判断する。

**設計概要:**
```python
def enumerate_relay_candidates(src, frontier_allies, all_planets, player, ...):
    for relay in frontier_allies:
        for target in enemy_and_neutral:
            relay_eta = route_eta(src, relay) + route_eta(relay, target)
            direct_eta = route_eta(src, target)
            if relay_eta <= direct_eta + RELAY_ETA_TOLERANCE:
                # src -> relay へ送出、relay の次ターン行動に期待
                ...
```

定数候補:
- `RELAY_ETA_TOLERANCE = 3`

---

## 5. 弱点露出

### 5-A: 出撃直後スナイプ (Post-Launch Snipe)

**課題:** 敵が自惑星から大量出撃した直後、その出撃元が手薄になるタイミングを検出していない。現在の snipe は「中立惑星への先着」のみ。

**前提確認:** `Fleet` dataclass に `from_planet_id` フィールドが存在するか確認。observation の fleet 配列は `[id, owner, x, y, angle, from_planet_id, ships]` の7フィールドのため、`utils.py` の `Fleet` に追加されているか確認。

**実装:** `targeting.py` に `enumerate_post_launch_snipe_candidates()` を新設。

```python
def enumerate_post_launch_snipe_candidates(
    my_planet,
    all_planets,
    fleets,
    player: int,
    angular_velocity: float = 0.0,
    planned: dict | None = None,
    remaining_turns: int | None = None,
    timelines: dict | None = None,
) -> list:
    planet_map = {p.id: p for p in all_planets}
    seen_origins: set[int] = set()

    for f in fleets:
        if f.owner == player:
            continue
        origin_id = getattr(f, 'from_planet_id', None)
        if origin_id is None or origin_id in seen_origins:
            continue
        origin = planet_map.get(origin_id)
        if origin is None or origin.owner == player:
            continue
        if origin.ships >= SNIPE_THIN_THRESHOLD:
            continue
        seen_origins.add(origin_id)

        # origin を通常 attack 候補と同じ value 式で評価し SNIPE_URGENCY_BONUS を加算
        # ships_needed = ships_budget(origin, my_eta=my_eta)
        # rival_eta = compute_rival_eta(origin, player, fleets, all_planets)
        # value = target_value(...) + SNIPE_URGENCY_BONUS
        out.append((origin, ships_needed, angle, value, float(my_eta)))

    return out
```

モード制限: behind のみ → **全モードに解禁**。

定数:
- `SNIPE_THIN_THRESHOLD = 15`
- `SNIPE_URGENCY_BONUS = 30.0`

---

### 5-B: ブリッジ惑星優先 (Bridge Planet Priority) [段階実装]

**課題:** 敵陣のどの惑星を落とせば補給路が途切れるか (articulation point) を考慮していない。

**段階実装方針:** 5-A を先に投入して効果確認後に実装判断する。

**設計概要:**
```python
def _bridge_bonus(target, enemy_planets) -> float:
    # target を除いた敵惑星グラフの連結成分数を計算
    # 連結成分が増えるほど高スコア
    graph = {p.id: [q for q in enemy_planets
                    if q.id != target.id and
                    math.hypot(p.x-q.x, p.y-q.y) <= BRIDGE_ADJACENCY_DIST]
             for p in enemy_planets if p.id != target.id}
    components = _count_components(graph)
    return BRIDGE_BONUS * max(0, components - 1)
```

定数候補:
- `BRIDGE_ADJACENCY_DIST = 50.0`
- `BRIDGE_BONUS = 25.0`

---

## 6. 実装順序と検証方針

| 優先 | 機能 | 実装箇所 | 検証 |
|------|------|---------|------|
| 1 | 4-B 容量ダンプ | policy.py | `max_capacity` フィールド確認後、ガントレット勝率 |
| 2 | 4-A 後方押し出し | targeting.py + policy.py | ガントレット勝率 + 艦船利用率 |
| 3 | 2-A JIT逆算送出 | targeting.py | ガントレット勝率 |
| 4 | 2-B 防衛放棄判断 | targeting.py | ガントレット勝率 |
| 5 | 5-A 出撃直後スナイプ | targeting.py + policy.py | `from_planet_id` フィールド確認後、ガントレット勝率 |
| 6 | 1-A 同時並行占領 | targeting.py + policy.py | ガントレット勝率 |
| 7 | 1-B rival合算確認 | state.py + tests | テスト追加のみ (既実装の可能性あり) |
| 8 | 3-A N>2 swarm | targeting.py | ガントレット勝率 |
| 9 | 3-B overcap | targeting.py | ガントレット勝率 |
| 10 | 4-C 玉突き輸送 | targeting.py | 4-A/4-B 効果確認後に判断 |
| 11 | 5-B ブリッジ優先 | targeting.py | 5-A 効果確認後に判断 |

運用:
- 1機能1commit。各機能投入後にガントレットを走らせ、勝率が下がれば即 revert。
- 定数は初期値で投入し、ガントレット結果を見てから調整する。
- `docs/bench/experiment-log.md` に各機能の before/after 勝率を記録する。

## 7. 未確認フィールド (実装開始前に確認必須)

| フィールド | 確認先 | 用途 |
|-----------|-------|------|
| `Planet.max_capacity` | `utils.py`, `state.py` | 4-B 容量ダンプ |
| `Fleet.from_planet_id` | `utils.py` | 5-A 出撃直後スナイプ |
| enemy fleet の timelines 反映 | `state.py` `build_game_state()` | 1-B rival合算 |
