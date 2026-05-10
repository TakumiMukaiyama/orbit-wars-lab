# 9 ルール準拠リファクタリング: 機能棚卸しと方針

意思決定の主軸を「領土拡張による Total Growth 最大化」に統一し、
ROI (Recovery Time) 最小化を共通の評価軸とする。

phase は中立惑星数の比率で `early` / `mid` / `late` に分割する
(従来の `is_opening` (turn=40) と `mode` (戦力比) は廃止)。

## 採用する 9 ルール

| # | ルール | 一言 |
|---|---|---|
| 1 | ROI 最小化 + 同時着弾 | RecoveryTime = ships/prod + travel を最小化 |
| 2 | ジャストサイズ射出 | Cost(B) + 1 のみ。余りは次の最良 ROI へ |
| 3 | 中央高出力への最短攻撃 | 序盤に中央 +3 / +5 を狙う (ROI 計算で自然に優先される) |
| 4 | JIT 防衛 | 援軍は最遠惑星から「直前」に到着させる |
| 5 | 出撃元スナイプ | 敵の大艦隊出撃 = 出撃元の守備力激減を狙う |
| 6 | 玉突き輸送 | 後方→中継→前線 |
| 7 | Cap 回避 | ships >= cap*0.9 で強制射出 |
| 8 | 同期マルチ着弾 | swarm: 着弾時刻を 1-2 turn 以内に揃える |
| 9 | 敵生産ライン分断 | 敵中心惑星を狙う **(今回スコープ外: 別途検討)** |

## phase 定義 (案)

```
neutral_ratio = neutral_count / total_planets
phase = "early" if neutral_ratio >= 0.5
        "mid"   if neutral_ratio >= 0.15
        "late"  otherwise
```

- early: 中立が半分以上。拡張競争が中心。Cap dump 早め、JIT margin 小さめ。
- mid: 中立がほぼ取り終わった状態。網と snipe で削る。
- late: 中立が枯れた飽和段階。swarm と chokepoint。

閾値は要計測 (Step 4 で確定)。

## 既存機能 vs 9 ルール対応表

### 残す (必要)

| 機能 / 関数 | 該当ルール | 備考 |
|---|---|---|
| `enumerate_candidates` | ① ② ③ | target_value を ROI 式に再設計 (Step 5) |
| `ships_needed_to_capture_at` / `ships_budget` | ② | 既に正しい |
| `enumerate_intercept_candidates` | ④ | JIT margin は phase 連動に |
| `enumerate_post_launch_snipe_candidates` | ⑤ | snipe 系を 1 関数に統合 |
| `enumerate_rear_push_candidates` | ⑥ | rear distance 閾値は phase 連動に |
| `enumerate_reinforce_candidates` | ⑥ | rear push と統合可能か検討 |
| `_pick_dump_target` / `CAP_DUMP_MARGIN_TURNS` | ⑦ | 優先順位を「最近接敵」「容量空き味方」に整理 |
| `enumerate_swarm_candidates` | ⑧ | ETA tolerance を phase 連動に |
| `enumerate_support_candidates` | ④ + ⑥ | JIT 化と整理 |
| `FOCUS_BONUS_PER_PLANNED_SHIP` | ① 同時着弾 | swarm 誘導用 |
| `CONCURRENT_BONUS` | ① 同時着弾 | swarm 誘導用 |
| `estimate_hold_turns` | ① | ROI 式の分母 (実質生産) 計算で必要 |

### 削除 (9 ルール非該当または重複)

| 機能 / 定数 | 削除理由 |
|---|---|
| `BEHIND_THRESHOLD` / `AHEAD_THRESHOLD` / `mode` 全体 | 戦略主軸を拡張に統一 → 戦力比 mode 分岐は不要 |
| `enumerate_snipe_candidates` (mode=behind 専用) | post_launch_snipe に統合 |
| `MAX_EXPAND_PER_TURN = 2` | ルール② (余りは次の ROI へ) と矛盾 |
| `OVEREXTEND_*` 一式 (4 定数 + `_overextend_factor`) | phase 判定で代替できる |
| `is_opening` の二重管理 (`OPENING_TURNS=40` / `CENTRAL_OPENING_TURNS=200` / `ORBITAL_OPENING_TURNS=160` / `PROD_URGENCY_TURNS=100`) | phase 単一変数に統合 |
| `HOLD_HORIZON` / `HOLD_HORIZON_BEHIND` | ROI 式 (Step 5) に統合 → 不要 |
| `TRAVEL_PENALTY` / `TRAVEL_PENALTY_QUAD` | ROI 式の travel_time 項に統合 → 不要 |
| `CENTRAL_BONUS_MAX` / `CENTRAL_REF_RADIUS` | ROI が中央高 prod を自然に優先するので冗長 |
| `STATIC_HIGH_PROD_BONUS` | 同上 (production が ROI 分母として効く) |
| `PROD_URGENCY_K` / `PROD_URGENCY_TURNS` | 同上 |
| `INNER_ORBITAL_BONUS` / `INNER_ORBITAL_RADIUS` | orbital 惑星は ROI 計算で自然に評価可能 |
| `ASSET_HORIZON = 120.0` | snipe の hold 計算で使われるだけ → ROI 統合で不要 |
| `THREAT_MARGIN = 0.0` | 0 のため事実上 no-op |
| `HIGH_PROD_RESERVE` / `HIGH_PROD_THRESHOLD` | top_n 救済枠 → ROI 統合後は冗長 |
| `policy.py` の swarm 二重呼び出し | バグ (291-330 と 370-404 が両方走る) |
| doomed `evac` 撤退 (policy.py:130-146) | 生産源を捨てるロジック → 9 ルールに該当しない |
| `MAX_EXPAND_PER_TURN` ガード (policy.py:230-237) | ルール② と矛盾 |

### RL 関連 (削除)

memory 方針「RL は当面スコープ外」に従い、模倣学習用コードを丸ごと削除する。

| ファイル | 役割 | 削除可否 |
|---|---|---|
| `src/policy.py` | HeuristicPolicy / ReplayLogger | **削除**: agent.py に直接インライン化 |
| `src/state.py` | GameState + 特徴量 (planet_features, global_features) | **特徴量関数を削除**。GameState の state 集約役割は agent.py 内ローカル関数 or 軽量 dataclass に統合 |
| `src/action_space.py` | Candidate, candidates_from_heuristic | **削除** |
| `src/cand_log.py` | replay 候補ログ | **削除** |
| `tests/test_policy.py` | HeuristicPolicy のテスト | **削除** |
| `tests/test_state.py` | GameState のテスト | **削除 or build_game_state 相当だけ残す** |
| `tests/test_action_space.py` | Candidate のテスト | **削除** |
| 環境変数 `ORBIT_WARS_REPLAY_LOG` | replay logger フラグ | **削除** |

## 作業手順 (再掲)

1. **Step 1** ✅ この文書 (棚卸し)
2. **Step 2** swarm 二重呼び出しバグ修正 → 計測ベースライン
3. **Step 3a** RL 関連削除 → 計測
4. **Step 3b** 9 ルール非該当機能削除 → 計測
5. **Step 4** phase = neutral_ratio 切替 → 計測
6. **Step 5** target_value を ROI 式 (RecoveryTime) に再設計 → 計測
7. **Step 6** 最終 gauntlet + experiment-log 記録 + submit

各 Step 後に 270 戦 gauntlet を回し、WR が下がった場合は原因を特定する。
