# Reinforce Script (R2) 設計書

- 作成日: 2026-05-03
- 対象: `agents/mine/planet_intercept`
- 目的: 味方惑星間の ships 輸送 script (reinforce) を追加し、観察済みの「前線が cant_afford で仕事できない」構造問題を解消する

---

## 背景

### 定量分析

`runs/2026-04-28-007` (P6 後, 60/90 = 66.7% WR) で mine/planet_intercept が負けた 30 試合は全て zero_early (ホーム陥落, score=0) だった。競り負けは 0 件。

vs pilkwang-structured (8 敗) と vs yuriygreben-architect (9 敗) の 17 敗を `gauntlet-analyze` skill で分析した結果:

| 指標 | median | 含意 |
|---|---|---|
| first_loss_turn | t=53 | 最初の自惑星喪失 |
| planet_parity_lost | t=17 | 惑星数で負け始める |
| home_fall_turn | t=118 | ホーム陥落 |
| peak_incoming_to_mine | 23 fleets | 同時 incoming |
| peak_simul_arrivals | 5 | 同一ターン到着ピーク |
| sun_crossing_ratio | 1% | 太陽越えは主因ではない |

milestone:

```
t=25:    3 /  3     (互角)
t=50:    8 /  7     (mine 一時リード)
t=75:   10 / 15     (逆転)
t=100:   6 / 19     (壊滅的に差)
```

t=50→t=100 で mine の惑星が 10 → 6 に減少。**取った惑星を保持できていない**。

### 遊兵分析 (既存 experiment-log より)

`runs/2026-04-28-007` 30 敗における idle ships の分類:

| 分類 | 割合 |
|---|---|
| cant_afford (val>0 候補はあるが single planet で払えない) | 98.9% |
| all_val_leq0 (全候補 value<=0) | 1.1% |

value<=0 は主因ではない。**前線惑星が ships_needed を払えない**のが本質。

### 3 戦リプレイ目視 (Match 049, 087, 041)

- **049 vs pilkwang**: 複数ラインの同時圧力で飽和、前線が孤立・補給断絶
- **087 vs yuriygreben**: 占領直後に低 garrison で奪い返される (モグラ叩き)
- **041 vs pilkwang**: 占領後の ships 成長を待てず小出しにし、敵にまとめて落とされる

**共通項**: 占領した惑星を保持できない = **後方→前線の補給ライン不在**が構造問題。

### 関連する過去実験の制約 (docs/bench/experiment-log.md)

- **Partial send (revert 済み)**: orbit-wars は sequential combat のため、ships_needed 未満の小艦隊は先着順で吸収される
- **Swarm (不採用)**: single-source で発射しなかった惑星を消費 → 既存攻撃が共倒れ
- **Snipe v1/v2 (不採用)**: 候補マージで既存攻撃を value 勝ちで上書きし、前線兵力が減少
- **MIN_RESERVE / MAX_SEND_RATIO (不採用)**: 勝ちゲームの 44% の launch を殺した (固定閾値の文脈盲目)

reinforce 設計はこれら 3 つの失敗パターンを明示的に回避する必要がある。

---

## 長期戦略 (本 spec の位置付け)

最終形は 2 層:

```
Layer 1 (script menu): expand / attack / intercept / [reinforce] / swarm / snipe / kill_shot / ...
        ↓ 各 script が候補 or 予算を出す
Layer 2 (policy): 盤面からどの script をどれだけ動かすかを決める
                  フェーズ 1: rule-based (現状)
                  フェーズ 2: RL による policy
```

現コードは既に Layer 1 相当を関数分離で持っている (`enumerate_candidates`, `enumerate_intercept_candidates`, `enumerate_swarm_candidates`, `enumerate_snipe_candidates`)。本 spec は Layer 1 に **reinforce** 1 本を足すだけで、アーキテクチャ変更は伴わない。

---

## Scope

### In scope

- 新規関数 `enumerate_reinforce_candidates` の追加 (受け手は R2: 「攻撃候補を持つが cant_afford な自惑星」のみ)
- `agent.py` に reinforce 独立パスを追加 (既存候補処理の後)
- `world.apply_planned_arrival` を味方 owner で流用 (timeline 整合)
- テスト追加 (targeting, agent, world 各方向)
- `docs/bench/experiment-log.md` に計測結果を追記

Out of scope は Future Work 章に集約する。

---

## 設計決定サマリ

| # | 決定 | 根拠 |
|---|---|---|
| Target (受け手) | R2: `attack/intercept 候補で value>0 を持つ` かつ `avail < candidates[0].ships_needed` な自惑星 | 遊兵 98.9% cant_afford に直接対応。次ターンの攻撃に直結 |
| Source (送り手) | S3: `value>0 の通常候補を持たない自惑星` | 既存攻撃と競合しない (swarm 失敗の再発防止) |
| Ships 数 | Q2: `min(source.avail - reserve, target の最上位候補 ships_needed - target.avail)` | 受け手が next-turn に発射できる量を保証。source も完全枯渇させない |
| 競合処理 | M1: 独立パス (通常候補処理の後、別パスで実行) | value 競合ゼロ。reinforce は残余を埋めるだけ (snipe/swarm 失敗の再発防止) |
| 1 ターン上限 | source ごとに 1 本 (`reinforce_fired_sources` で管理) | M1 の自然な帰結。過剰発射の防止 |

---

## アーキテクチャ

### `targeting.py` (新規)

```python
@dataclass
class ReinforceMission:
    source_id: int
    target_id: int   # 味方惑星の id
    ships: int
    angle: float     # source -> target の直線角度
    value: float
    my_eta: int


def enumerate_reinforce_candidates(
    my_planets: list[Planet],
    target_candidates_by_planet: dict[int, list[AttackCandidate]],
    timelines: dict[int, PlanetTimeline],
    reserve_of: Callable[[Planet], int],
) -> list[ReinforceMission]:
    """
    R2 + S3 + Q2 + M1 の reinforce 候補列挙。

    target (受け手) 条件:
      - planet in my_planets
      - target_candidates_by_planet[planet.id] の最上位候補 top_c が存在し value>0
      - planet.ships - reserve_of(planet) < top_c.ships_needed
        (= cant_afford)

    source (送り手) 条件:
      - planet in my_planets
      - planet.id が target として選ばれた planet ではない
      - target_candidates_by_planet[planet.id] に value>0 の候補が存在しない
        (= 打つ手なし source)
      - planet.ships - reserve_of(planet) > 0

    ships 数:
      need = top_c.ships_needed - (target.ships - reserve_of(target))
      avail = source.ships - reserve_of(source)
      ships = min(avail, need)
      ships <= 0 の source/target 組は候補化しない

    value:
      value = ships * PRODUCTION_LEVERAGE - my_eta * TRAVEL_PENALTY
      PRODUCTION_LEVERAGE, TRAVEL_PENALTY は既存定数 (attack と同じスケール)

    my_eta:
      source -> target の直線距離 / fleet_speed(ships).
      sun crossing / 軌道惑星による経路歪みは Step 1 では考慮しない
      (初版では target が固定自惑星 = 動かないため距離は静的に計算可能)
    """
    ...
```

### `agent.py` (変更)

既存 `select_move` ループの**後**に reinforce パスを追加する。

```python
# 既存: 通常候補 (attack / intercept / swarm / snipe) の発射
fired_sources: set[int] = set()
for ... in select_move_loop(...):
    fired_sources.add(picked.source_id)

# 新規: reinforce パス
reinforce_missions = enumerate_reinforce_candidates(
    my_planets=my_planets,
    target_candidates_by_planet=target_candidates_by_planet,
    timelines=timelines,
    reserve_of=lambda p: defense_reserve(p, timelines[p.id], ...),
)
reinforce_fired_sources: set[int] = set()
for r in sorted(reinforce_missions, key=lambda m: -m.value):
    if r.source_id in fired_sources:
        continue
    if r.source_id in reinforce_fired_sources:
        continue
    if r.ships <= 0:
        continue
    emit_launch(r.source_id, r.target_id, r.ships, r.angle)
    apply_planned_arrival(
        ledger=ledger,
        timelines=timelines,
        planets=planets,
        target_id=r.target_id,
        owner=mine_player,
        ships=r.ships,
        eta=r.my_eta,
        horizon=horizon,
    )
    reinforce_fired_sources.add(r.source_id)
```

### Key invariants

1. **source が通常パスで使われた場合、reinforce には使わない** (`fired_sources` チェック)
2. **reinforce は value>0 候補を持たない惑星のみを source にする** → 定義上、既存攻撃と ships を奪い合わない
3. **1 source 1 本/ターン** (`reinforce_fired_sources` で強制)
4. **arrival ledger を更新** → 次ターンの通常候補 enumerate で reinforce 到着後の ships が正しく見える

---

## value 式とパラメータ

```
value = ships * PRODUCTION_LEVERAGE - my_eta * TRAVEL_PENALTY
```

- `ships`: 実送出数 (上記 Q2 の式で決まる)
- `my_eta`: source → target の直線 ETA
- `PRODUCTION_LEVERAGE`: 初期値は既存の neutral planet 占領時の `value` スケールと同等になるよう決める (= attack candidate の `save_value` 換算。実装時に `1.0` 基準で開始し、計測を見て調整)
- `TRAVEL_PENALTY`: 既存 attack 候補と同じ `0.15`

**注**: M1 (独立パス) のため、Step 1 では value の絶対値は発射判定に影響しない (候補が複数ある場合のソート順のみに使用)。そのため初期値は厳密チューニング不要。後に M2 (value 統合) に移行する際に再設計する。

---

## 実装ステップ (1 commit ごと)

1. **commit 1**: `targeting.py` に `ReinforceMission` dataclass と `enumerate_reinforce_candidates` を追加。関連テスト `TestEnumerateReinforceCandidates` (5 件) を追加。
2. **commit 2**: `agent.py` に reinforce 独立パスを追加。`apply_planned_arrival` の味方 owner 呼び出しを追加。agent 側テストを追加。

2 commit に分ける理由: テストのみで実装検証できる部分 (commit 1) と、agent loop に組み込む部分 (commit 2) を分けることで、gauntlet 劣化時の切り分けが容易になる。

---

## テスト

### `tests/test_targeting.py`

- `test_reinforce_source_excluded_when_has_value_candidate`
  source 側が value>0 の通常候補を持つとき、その惑星は reinforce source にならない
- `test_reinforce_target_only_when_cant_afford`
  target の `avail >= ships_needed` のとき、その惑星は reinforce target にならない
- `test_reinforce_ships_matches_target_need`
  ships 量 = `min(source.avail, target.ships_needed - target.avail)` を満たす
- `test_reinforce_ships_zero_when_target_fully_funded`
  target.avail >= ships_needed なら ships = 0 (候補化されない)
- `test_reinforce_target_excluded_when_top_candidate_value_nonpositive`
  target の最上位候補が value<=0 のとき候補化されない (= 攻撃候補は「あるが価値がない」ケース)

### `tests/test_agent.py`

- `test_reinforce_pass_does_not_double_fire_source`
  通常パスで発射した source は reinforce でも使われない (`fired_sources` チェック)
- `test_reinforce_updates_arrival_ledger_for_friendly_target`
  reinforce 発射後、target 自惑星の timeline ships が `eta` 時点で `+ ships` になっている

### 期待されるテスト件数

既存 171 passed, 2 skipped → **178 passed, 2 skipped** を目標 (7 件追加)。

---

## 計測と採用基準

### 比較 baseline

- `runs/2026-04-28-007` (P6 後, 60/90 = 66.7% WR, 最新ピーク)

### gauntlet コマンド

```bash
uv run python -m orbit_wars_app.tournament run \
  --agents mine/planet_intercept baselines/nearest-sniper baselines/random baselines/starter \
           external/kashiwaba-rl external/pilkwang-structured external/sigmaborov-reinforce \
           external/sigmaborov-starter external/tamrazov-starwars external/yuriygreben-architect \
  --games-per-pair 10 --mode fast --format 2p --seed 42 --focus mine/planet_intercept
```

### 採用基準 (既存 experiment-log の運用に合わせる)

- 全体 WR が 60/90 を下回らない
- 特定相手への **-3 勝以上の劣化がない**
- 成功シグナル: vs yuriygreben-architect (現 1-9) と vs pilkwang-structured (現 2-8) の **いずれかで +2 勝以上**

### 劣化時のアクション

- 全体劣化: `git revert` で commit 2 (agent 側) のみ戻す。commit 1 の dataclass と関数は残す
- commit 1 も戻したい場合は 2 commit まとめて revert

### Expected failure modes と切り分け方針

| 劣化パターン | 兆候 | 切り分け手段 |
|---|---|---|
| 中継中の reinforce fleet が敵迎撃で消耗 | reinforce 発射数は増えたが target の次ターン攻撃が増えない | replay で reinforce fleet の軌跡確認。発生時は Step 1b で sun/迎撃チェック追加 |
| source が予想外に枯渇 | 通常攻撃の発射数が減る | `fired_sources` チェックが機能しているか unit test で確認 |
| reinforce target が reinforce 到着前に落ちる | target の `home_fall_turn` が reinforce eta より早い | enumerate で `timelines[target].fall_turn` が eta 未満なら候補除外 (Step 1b) |

---

## 期待効果 (仮説)

- **vs pilkwang-structured**: 観察 049 の「前線孤立」が緩和 → +1〜3 勝
- **vs yuriygreben-architect**: 観察 087 の「占領直後奪い返し」が部分緩和 (完全には R1 が必要) → +1〜2 勝
- **全体 WR**: +3〜7pp (60/90 → 63-67/90 程度)

計測結果に応じた次手は Future Work 章の分岐ロジック表を参照。

---

## Non-goals (本 spec の境界)

- value 式の厳密チューニング (M1 のため発射判定に影響しない)
- sun crossing / 迎撃リスクでの送信抑制 (初版では無視、計測で無駄撃ちが見えたら Step 1b で追加)
- 4P format 対応 (2P で成立した後に別途検証)
- RL phase への移行準備 (本 spec は rule-based で完結、Layer 2 は Future Work 参照)

---

## Future Work

本 spec の計測結果に応じて、次に着手する順序を以下に定める。

### 分岐ロジック

| 本 spec の結果 | 次の一手 |
|---|---|
| 採用 (+2pp 以上) かつ vs yuriygreben or pilkwang で +2 勝以上 | **Step 2 (R1)** に進む |
| 採用だが +2pp 未満 / 特定相手の改善が弱い | **Step 3 (D: 距離ペナルティ 2 乗化)** を先行し、その後 Step 2 |
| 不採用 (revert) | **Step 3 (D)** を先行。本 spec の失敗モード (expected failure modes 表) を元に reinforce 再設計は保留 |

### Step 2: R1 — 脆い直近占領への補給 (別 spec)

- **動機**: リプレイ 087 (yuriygreben Step 116+) で観察された「占領直後の低 garrison 惑星が奪い返される」問題
- **本 spec との差分**: 受け手条件に「占領後 N ターン以内」かつ「garrison < 閾値」を追加。source/ships/M1 は流用
- **想定期間**: 本 spec 採用後、計測が安定したら着手

### Step 3: D — 距離ペナルティ 2 乗化 (別 spec)

- **動機**: リプレイ 041/087 で観察された「遠距離発射による戦力浮遊」
- **変更点**: 既存 value 式の `my_eta * TRAVEL_PENALTY` (線形) を `my_eta^2 * TRAVEL_PENALTY_QUAD` もしくは既存に 2 乗項を加算
- **本 spec との関係**: reinforce 自身の value 式もこの影響を受けるため、Step 2 より先に入ると reinforce の value スケール再調整が必要になる可能性あり

### Step 4 以降 (順不同、P11 portfolio 化までの材料)

- **swarm 再投入**: reinforce で ships 循環が改善した状態で、P6 時の「ships 余裕チェック」を追加して再挑戦
- **snipe 再投入**: 同上、専用予算枠を作る設計で再挑戦
- **JIT defense の複数本化** (backlog P3-B): peak_simul=5 対応。intercepted_ids を timeline 駆動の必要量ぴったりに変更
- **counter-snipe**: 自陣攻撃検出時に敵の手薄へ逆撃、新 script 追加
- **opening expand 改善** (backlog P7): planet_parity_lost 対策

### 最終ゴール (Layer 2 移行, 現時点で未着手)

- **script portfolio + greedy assignment** (backlog P11): 上記 Layer 1 メニューが揃ったら、policy が盤面特徴量から script 配分を選ぶ層を追加
- **CMA-ES での scalar weight tuning** (backlog P14): portfolio 化後、self-play で weights を最適化
- **RL phase**: portfolio の action 空間 (script id × 予算) を学習対象にする

本 spec はこの最終ゴールへの第一歩として、「未実装だった補給ライン」という構造ギャップを埋める。
