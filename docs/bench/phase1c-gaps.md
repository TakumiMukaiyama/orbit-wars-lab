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

## P5 試行: Snipe Mission (不採用・未コミット)

- 試行内容:
  - `world.py` に `estimate_snipe_outcome(target, ledger, player, my_eta, ships_after_capture, horizon) -> (hold_turns, absorbed)` を追加し、占領後 horizon までの保持ターン数と吸収敵 ships を推定。
  - `targeting.py` に `enumerate_snipe_candidates` を追加。中立 + ledger に敵 arrival あり + 自 eta < 敵最速 eta の条件で候補化し、スコア `production * hold_turns + absorbed - ships_needed - my_eta * TRAVEL_PENALTY`。
  - `agent.py` で `all_cands = attack_cands + intercept_cands + snipe_cands` にマージ。
- Run (AFTER): `runs/2026-04-27-012`
- 単体テスト: 148 passed, 2 skipped (`TestEstimateSnipeOutcome` 4 件 + `TestEnumerateSnipeCandidates` 4 件)

| 相手 | After +P4 (011) | After +P4+P5 (012) | Δ (wins) |
|---|---|---|---|
| baselines/nearest-sniper | 9-1-0 (90.0%) | 9-1-0 (90.0%) | = |
| baselines/random | 10-0-0 (100.0%) | 10-0-0 (100.0%) | = |
| baselines/starter | 9-1-0 (90.0%) | 7-3-0 (70.0%) | -2 |
| external/kashiwaba-rl | 10-0-0 (100.0%) | 10-0-0 (100.0%) | = |
| external/pilkwang-structured | 1-9-0 (10.0%) | 0-10-0 (0.0%) | -1 |
| external/sigmaborov-reinforce | 3-7-0 (30.0%) | 0-10-0 (0.0%) | -3 |
| external/sigmaborov-starter | 0-10-0 (0.0%) | 3-7-0 (30.0%) | +3 |
| external/tamrazov-starwars | 1-9-0 (10.0%) | 0-10-0 (0.0%) | -1 |
| external/yuriygreben-architect | 1-9-0 (10.0%) | 1-9-0 (10.0%) | = |
| **TOTAL** | **44/90 (48.9%)** | **40/90 (44.4%)** | **-4 (-4.4pt)** |

判定: 全体 -4 勝、基準「-3 以上の劣化なら revert」を超えるため**不採用**。`git restore` で未コミットの実装を破棄し、ユニットテストごと戻した。

原因メモ (次回リトライ時の参考):
- sigmaborov-reinforce に +3 だったのが -3 に急落。snipe 候補が attack 候補を value 勝負で上書きし、序盤に「占領はしたが hold しきれない中立」に先行投資して主力を削られたと推測。
- `estimate_snipe_outcome` で失陥時の `absorbed` を "失陥直前の garrison" として計上している箇所が過大評価。失陥は実質マイナスなのに、absorbed ≥ 0 でスコアがプラス寄りになる。
- 再挑戦の方針: (a) 失陥シナリオでは `absorbed = 0` にする、(b) スコアから `hold_turns` が horizon 未満のとき `-K * (my_eta)` のような penalty を追加、(c) snipe は starter-like 相手 (sigmaborov-starter 系) には効くので、domination mode が `behind` のときだけ活性化する条件付き導入を検討。

## 次に実装すること

**P6: Multi-source Swarm** (`docs/bench/implement-plan.md` P6 準拠) を次に試す。

- 目的: 1 つの自惑星では足りない target を、複数自惑星から近い ETA で同時攻略する。
- 実装方針: target ごとに source options を列挙し、ETA 差 `<= 2-3` の source 組合せを探し、合計 send cap が `ships_needed_to_capture_at(target, joint_eta)` を超えるなら mission 化。Phase 1 では 2-source だけでよい。
- 期待: `external/pilkwang-structured` / `external/tamrazov-starwars` / `external/yuriygreben-architect` の 0-10% 層に対して +1〜+2 勝。これらはいずれも swarm を既に持っていて、single-source 攻撃だけでは削り負けている可能性が高い。

P5 は P6 の後に `estimate_snipe_outcome` の penalty 設計を練り直してから再挑戦する。

## P6: Multi-source Swarm (不採用・revert 済み)

- 試行内容:
  - `targeting.py` に `SwarmMission` dataclass と `ETA_SYNC_TOLERANCE=3` を追加。
  - `enumerate_swarm_candidates(my_planets, ...)` を実装。各ソース単独では `ships_needed` を満たせないが 2-source 合算なら満たせるターゲットを探し、ETA 差 ≤ 3 の source ペアを SwarmMission に変換。
  - `agent.py` でシングルソースループ後に `fired_sources` 管理のスウォームパスを追加。
- Run (AFTER): `runs/2026-04-27-013`
- 単体テスト: 144 passed, 2 skipped (`TestEnumerateSwarmCandidates` 4 件追加)

| 相手 | After +P4 (011) | After +P4+P6 (013) | Δ (wins) |
|---|---|---|---|
| baselines/nearest-sniper | 9-1-0 (90.0%) | 9-1-0 (90.0%) | = |
| baselines/random | 10-0-0 (100.0%) | 10-0-0 (100.0%) | = |
| baselines/starter | 9-1-0 (90.0%) | 6-4-0 (60.0%) | -3 |
| external/kashiwaba-rl | 10-0-0 (100.0%) | 10-0-0 (100.0%) | = |
| external/pilkwang-structured | 1-9-0 (10.0%) | 1-9-0 (10.0%) | = |
| external/sigmaborov-reinforce | 3-7-0 (30.0%) | 0-10-0 (0.0%) | -3 |
| external/sigmaborov-starter | 0-10-0 (0.0%) | 2-8-0 (20.0%) | +2 |
| external/tamrazov-starwars | 1-9-0 (10.0%) | 0-10-0 (0.0%) | = |
| external/yuriygreben-architect | 1-9-0 (10.0%) | 0-10-0 (0.0%) | = |
| **TOTAL** | **44/90 (48.9%)** | **38/90 (42.2%)** | **-6 (-6.7pt)** |

判定: 全体 -6 勝、基準 (≥41/90) を大きく下回るため**不採用**。`git revert` でリバート済み。`targeting.py` の `SwarmMission` / `enumerate_swarm_candidates` は残存 (テストも維持)。

原因メモ (次回リトライ時の参考):
- starter -3、sigmaborov-reinforce -3 の劣化が主因。スウォームパスが single-source ループで発射済みでない惑星 (ships 温存中の惑星) を2本同時に消費し、single-source 攻撃手が減少した。
- 具体的には「シングルソースループで発射しなかった惑星」= 防衛予備 or 価値の低い手しかない惑星 をスウォームで一気に使い、結果 ships 不足に陥ると推定。
- 再挑戦の方針: (a) swarm は `domination=ahead` のときだけ活性化 (ships 余裕がある状況限定)、(b) value 閾値を高めに設定して質の低い mission は弾く、(c) swarm 発動条件に「両 source の ships が `ships_needed * 2` 以上」などの余裕チェックを追加。

