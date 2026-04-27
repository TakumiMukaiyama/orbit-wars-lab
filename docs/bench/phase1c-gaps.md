# Phase 1c 残ギャップ計測

Phase 1c の timeline / ledger 基盤に対して、ユーザー指摘の 3 つの残ギャップを各単独コミットで投入し、都度 2P 対戦 (9 相手 × 10 戦 × seed=42, focus=mine/planet_intercept) で勝率を計測する。劣化したら `git revert` で該当コミットだけ戻す。

## 計測コマンド (共通)

```bash
uv run python -m orbit_wars_app.tournament run \
  --agents mine/planet_intercept baselines/nearest-sniper baselines/random baselines/starter \
           external/kashiwaba-rl external/pilkwang-structured external/sigmaborov-reinforce \
           external/sigmaborov-starter external/tamrazov-starwars external/yuriygreben-architect \
  --games-per-pair 10 --mode fast --format 2p --seed 42 --focus mine/planet_intercept
```

単体テスト: `cd agents/mine/planet_intercept && uv run pytest -q`

## ベースライン (Phase 1c G0, 全ギャップ未適用)

- Run: `runs/2026-04-27-007`
- 単体テスト: 129 passed, 2 skipped

| 相手 | W-L-D | 勝率 |
|---|---|---|
| baselines/nearest-sniper | 7-3-0 | 70.0% |
| baselines/random | 10-0-0 | 100.0% |
| baselines/starter | 4-6-0 | 40.0% |
| external/kashiwaba-rl | 10-0-0 | 100.0% |
| external/pilkwang-structured | 1-9-0 | 10.0% |
| external/sigmaborov-reinforce | 0-10-0 | 0.0% |
| external/sigmaborov-starter | 1-9-0 | 10.0% |
| external/tamrazov-starwars | 0-10-0 | 0.0% |
| external/yuriygreben-architect | 0-10-0 | 0.0% |
| **TOTAL** | **33-57-0** | **36.7%** |

## G1: classify_defense を timeline 駆動に

- 変更: `targeting.py::classify_defense` に `timeline` 引数追加 (旧挙動は `timeline=None` で後方互換)。`agent.py` で `timelines.get(p.id)` を渡す。
- Run (AFTER): `runs/2026-04-27-008`
- 単体テスト: 132 passed, 2 skipped (TestClassifyDefense に timeline ケース 3 件追加)

| 相手 | Before (007) | After (008) | Δ (wins) |
|---|---|---|---|
| baselines/nearest-sniper | 7-3-0 (70.0%) | 9-1-0 (90.0%) | +2 |
| baselines/random | 10-0-0 (100.0%) | 10-0-0 (100.0%) | = |
| baselines/starter | 4-6-0 (40.0%) | 6-4-0 (60.0%) | +2 |
| external/kashiwaba-rl | 10-0-0 (100.0%) | 10-0-0 (100.0%) | = |
| external/pilkwang-structured | 1-9-0 (10.0%) | 0-10-0 (0.0%) | -1 |
| external/sigmaborov-reinforce | 0-10-0 (0.0%) | 0-10-0 (0.0%) | = |
| external/sigmaborov-starter | 1-9-0 (10.0%) | 1-9-0 (10.0%) | = |
| external/tamrazov-starwars | 0-10-0 (0.0%) | 1-9-0 (10.0%) | +1 |
| external/yuriygreben-architect | 0-10-0 (0.0%) | 0-10-0 (0.0%) | = |
| **TOTAL** | **33/90 (36.7%)** | **37/90 (41.1%)** | **+4 (+4.4pt)** |

判定: 全体 +4 勝、単独の大幅劣化なし → 採用 (G1 単独コミット予定)。

## G3: intercept の ships_needed を timeline 駆動に

- 変更: `enumerate_intercept_candidates` で `fall_turn = first_turn_lost` 時点の `state.ships + 1` を `ships_needed` とする。timeline 未提供時は従来の `f.ships + 1` フォールバック。`my_eta > fall_turn` の候補は明示的に除外。
- Run (AFTER): `runs/2026-04-27-009`
- 単体テスト: 134 passed, 2 skipped (TestEnumerateInterceptCandidates に 2 件追加)

| 相手 | After G1 (008) | After G1+G3 (009) | Δ (wins) |
|---|---|---|---|
| baselines/nearest-sniper | 9-1-0 (90.0%) | 8-2-0 (80.0%) | -1 |
| baselines/random | 10-0-0 (100.0%) | 10-0-0 (100.0%) | = |
| baselines/starter | 6-4-0 (60.0%) | 8-2-0 (80.0%) | +2 |
| external/kashiwaba-rl | 10-0-0 (100.0%) | 10-0-0 (100.0%) | = |
| external/pilkwang-structured | 0-10-0 (0.0%) | 0-10-0 (0.0%) | = |
| external/sigmaborov-reinforce | 0-10-0 (0.0%) | 0-10-0 (0.0%) | = |
| external/sigmaborov-starter | 1-9-0 (10.0%) | 2-8-0 (20.0%) | +1 |
| external/tamrazov-starwars | 1-9-0 (10.0%) | 0-10-0 (0.0%) | -1 |
| external/yuriygreben-architect | 0-10-0 (0.0%) | 0-10-0 (0.0%) | = |
| **TOTAL** | **37/90 (41.1%)** | **38/90 (42.2%)** | **+1 (+1.1pt)** |

判定: 全体 +1、starter +2 の改善が大きい。採用 (G3 単独コミット予定)。

## G2: 採用手を ledger/timeline に反映

- 変更:
  - `world.py` に `apply_planned_arrival(ledger, timelines, planets, target_id, owner, ships, eta, horizon)` を追加。eta 範囲外や ships<=0 は no-op。ledger は eta 昇順で保ち、timeline は `simulate_planet_timeline` で再構築。
  - 攻撃/迎撃候補タプルを `(target, ships_needed, angle, value, my_eta)` の 5-tuple に拡張。`select_move` は後方互換で 4/5-tuple どちらも受け付け、戻り値を `(target_id, angle, ships, my_eta)` に拡張。
  - `agent.py` は採用手を `apply_planned_arrival` で ledger/timelines に書き戻し、当該惑星が自軍なら `defense_status` も再 classify。
- Run (AFTER): `runs/2026-04-27-010`
- 単体テスト: 138 passed, 2 skipped (TestApplyPlannedArrival 4 件追加、既存 unpack は 5-tuple 対応に更新)

| 相手 | After G1+G3 (009) | After G1+G3+G2 (010) | Δ (wins) |
|---|---|---|---|
| baselines/nearest-sniper | 8-2-0 (80.0%) | 10-0-0 (100.0%) | +2 |
| baselines/random | 10-0-0 (100.0%) | 10-0-0 (100.0%) | = |
| baselines/starter | 8-2-0 (80.0%) | 5-5-0 (50.0%) | -3 |
| external/kashiwaba-rl | 10-0-0 (100.0%) | 10-0-0 (100.0%) | = |
| external/pilkwang-structured | 0-10-0 (0.0%) | 1-9-0 (10.0%) | +1 |
| external/sigmaborov-reinforce | 0-10-0 (0.0%) | 1-9-0 (10.0%) | +1 |
| external/sigmaborov-starter | 2-8-0 (20.0%) | 3-7-0 (30.0%) | +1 |
| external/tamrazov-starwars | 0-10-0 (0.0%) | 0-10-0 (0.0%) | = |
| external/yuriygreben-architect | 0-10-0 (0.0%) | 1-9-0 (10.0%) | +1 |
| **TOTAL** | **38/90 (42.2%)** | **41/90 (45.6%)** | **+3 (+3.4pt)** |

判定: 全体 +3 勝、弱い相手 (外部勢) に対する星取りが広がり、nearest-sniper は完勝。starter だけ -3 で後退 (連射抑止で攻撃手数が減った副作用と推定)。全体トレンドが改善なので採用。starter 特化の調整は Phase 1c 後の別タスクで検討。

## 3 ギャップ合計 (ベースライン比)

| 相手 | G0 (007) | G1+G3+G2 (010) | Δ (wins) |
|---|---|---|---|
| baselines/nearest-sniper | 7-3-0 (70.0%) | 10-0-0 (100.0%) | +3 |
| baselines/random | 10-0-0 (100.0%) | 10-0-0 (100.0%) | = |
| baselines/starter | 4-6-0 (40.0%) | 5-5-0 (50.0%) | +1 |
| external/kashiwaba-rl | 10-0-0 (100.0%) | 10-0-0 (100.0%) | = |
| external/pilkwang-structured | 1-9-0 (10.0%) | 1-9-0 (10.0%) | = |
| external/sigmaborov-reinforce | 0-10-0 (0.0%) | 1-9-0 (10.0%) | +1 |
| external/sigmaborov-starter | 1-9-0 (10.0%) | 3-7-0 (30.0%) | +2 |
| external/tamrazov-starwars | 0-10-0 (0.0%) | 0-10-0 (0.0%) | = |
| external/yuriygreben-architect | 0-10-0 (0.0%) | 1-9-0 (10.0%) | +1 |
| **TOTAL** | **33/90 (36.7%)** | **41/90 (45.6%)** | **+8 (+8.9pt)** |

## ロールバック単位

3 コミットが `main` に積まれている。劣化が観測されたギャップだけ `git revert` で戻せる:

```
d92b21e feat(agent): drive classify_defense with planet timeline      (G1)
9daf041 feat(targeting): timeline-driven intercept ships_needed       (G3)
<G2>    feat(agent): apply planned arrivals back into ledger/timeline (G2)
```

## P4: Intercept dedup + travel-penalty value

- 変更:
  - `targeting.py::enumerate_intercept_candidates` の value 式を `save_value - ships_needed - my_eta * TRAVEL_PENALTY` に変更 (近い自惑星から撃つほうが優先されるようにする)。
  - `agent.py` に `intercepted_ids: set[int]` を導入し、同一 defended planet への迎撃を 1 turn 1 本までに制限 (複数自惑星から細切れ 2-4 艦の迎撃が集まり攻撃手が消える副作用を抑える)。
  - ship_needed は G3 で timeline 駆動済みなのでここでは触らない。
- Run (AFTER): `runs/2026-04-27-011`
- 単体テスト: 140 passed, 2 skipped (`TestEnumerateInterceptCandidates` に `test_value_penalizes_travel_time` と `test_value_regression_timeline_ships_needed` を追加)

| 相手 | After G1+G3+G2 (010) | After +P4 (011) | Δ (wins) |
|---|---|---|---|
| baselines/nearest-sniper | 10-0-0 (100.0%) | 9-1-0 (90.0%) | -1 |
| baselines/random | 10-0-0 (100.0%) | 10-0-0 (100.0%) | = |
| baselines/starter | 5-5-0 (50.0%) | 9-1-0 (90.0%) | +4 |
| external/kashiwaba-rl | 10-0-0 (100.0%) | 10-0-0 (100.0%) | = |
| external/pilkwang-structured | 1-9-0 (10.0%) | 1-9-0 (10.0%) | = |
| external/sigmaborov-reinforce | 1-9-0 (10.0%) | 3-7-0 (30.0%) | +2 |
| external/sigmaborov-starter | 3-7-0 (30.0%) | 0-10-0 (0.0%) | -3 |
| external/tamrazov-starwars | 0-10-0 (0.0%) | 1-9-0 (10.0%) | +1 |
| external/yuriygreben-architect | 1-9-0 (10.0%) | 1-9-0 (10.0%) | = |
| **TOTAL** | **41/90 (45.6%)** | **44/90 (48.9%)** | **+3 (+3.3pt)** |

判定: 全体 +3 勝、starter に対して +4 と大きく改善。sigmaborov-starter は -3 で劣化しているが、「細切れ迎撃が消えて攻撃手が増えた」副作用が別形で出た可能性。全体トレンドは改善、基準 (≥41/90、random/kashiwaba-rl/nearest-sniper 維持) を満たすので採用。sigmaborov-starter への回帰は P5/P6 の材料として観察。

## 4 ギャップ合計 (ベースライン比)

| 相手 | G0 (007) | G1+G3+G2+P4 (011) | Δ (wins) |
|---|---|---|---|
| baselines/nearest-sniper | 7-3-0 (70.0%) | 9-1-0 (90.0%) | +2 |
| baselines/random | 10-0-0 (100.0%) | 10-0-0 (100.0%) | = |
| baselines/starter | 4-6-0 (40.0%) | 9-1-0 (90.0%) | +5 |
| external/kashiwaba-rl | 10-0-0 (100.0%) | 10-0-0 (100.0%) | = |
| external/pilkwang-structured | 1-9-0 (10.0%) | 1-9-0 (10.0%) | = |
| external/sigmaborov-reinforce | 0-10-0 (0.0%) | 3-7-0 (30.0%) | +3 |
| external/sigmaborov-starter | 1-9-0 (10.0%) | 0-10-0 (0.0%) | -1 |
| external/tamrazov-starwars | 0-10-0 (0.0%) | 1-9-0 (10.0%) | +1 |
| external/yuriygreben-architect | 0-10-0 (0.0%) | 1-9-0 (10.0%) | +1 |
| **TOTAL** | **33/90 (36.7%)** | **44/90 (48.9%)** | **+11 (+12.2pt)** |

## 次に実装すること

**P5: Snipe Mission** (`docs/bench/implement-plan.md` P5 準拠)

- `world.py` に `estimate_snipe_outcome(target, ledger, player, my_eta, ships_after_capture, horizon) -> (hold_turns, absorbed)` を追加。
- `targeting.py` に `enumerate_snipe_candidates(...)` を追加。中立 + ledger に敵 arrival あり + 自 eta < 敵最速 eta の条件で候補化。スコア: `production * hold_turns + absorbed - ships_needed - my_eta * TRAVEL_PENALTY`。
- `agent.py` で `all_cands = attack_cands + intercept_cands + snipe_cands` にマージ。
- 期待: `external/pilkwang-structured` / `external/tamrazov-starwars` / `external/yuriygreben-architect` のいずれかで +1 以上。

