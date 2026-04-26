# Phase 1b 強さ計測

- 計測日: 2026-04-26
- ブランチ / HEAD: main (Phase 1b 変更は未コミット、`agents/mine/planet_intercept/src/{targeting,agent,geometry}.py` を改修)
- 対象: `agents/mine/planet_intercept` (Phase 1b: 中立 value 修正 + 母星 reserve + 迎撃 + 4P rival_eta 基盤)
- 環境: macOS darwin 24.6.0、Python 3.13.5、mode=fast (in-process)
- TS 起点: `runs/trueskill.json.phase1a` (Phase 1a 計測後の状態) を起点にして本計測、Δ は Phase 1a 比

## Phase 1b の変更サマリ

1. **A-1 中立惑星 value 修正**: `target_value` に `target_owner` 引数を追加し、中立惑星は `production * HOLD_HORIZON - ships_to_send - my_eta * TRAVEL_PENALTY` (HOLD_HORIZON=20, TRAVEL_PENALTY=0)。rival が先着する脅威下では gain 式に縮退。
2. **A-2 母星守備 reserve**: `estimate_reserve` が自惑星へ向かう敵フリート ships 合計を reserve として返す。`my_planet_count <= 1` なら reserve=0 (序盤攻勢優先)。
3. **A-3 迎撃 intercept**: `enumerate_intercept_candidates` を追加し、attack 候補と同じリストに統合して `select_move` に渡す。`geometry.fleet_intercept_point` が二次方程式で最短 ETA 迎撃点を算出。
4. **A-4 4P rival_eta 基盤**: `compute_rival_eta_per_player` (dict 返し) を新設し、`compute_rival_eta` は後方互換ラッパー化。Phase 1c 以降の近接ペナルティ式の素地作り (Phase 1b 時点では呼び出し挙動は不変)。

## コマンド

```bash
# 2P gauntlet (全 zoo, 各 10 試合) - Phase 1a と同一
.venv/bin/python -m orbit_wars_app.tournament gauntlet mine/planet_intercept \
  --bucket baselines,external --format 2p --games-per-pair 10 --seed 100 --mode fast

# 4P gauntlet (全 zoo, 各 3 試合) - Phase 1a と同一
.venv/bin/python -m orbit_wars_app.tournament gauntlet mine/planet_intercept \
  --bucket baselines,external --format 4p --games-per-pair 3 --seed 200 --mode fast
```

| 実行 ID | フォーマット | 試合数 | wallclock |
|---|---|---|---|
| 2026-04-26-003 | 2P | 90 | 285.2 s (4:45) |
| 2026-04-26-004 | 4P | 252 | 2984.4 s (49:44) |

status 内訳: 全 342 試合 `ok`。crash/timeout/invalid_action は 0 件。

単体テスト: `.venv/bin/pytest agents/mine/planet_intercept/tests/` で 55 件全パス (0.03 s)。

## 2P 勝率マトリクス (planet_intercept 視点、Phase 1a 比)

| 相手 | Phase 1a | Phase 1b | Δ | 自スコア平均 | 敵スコア平均 | 平均ターン |
|---|---|---|---|---|---|---|
| baselines/random | 10-0-0 | 10-0-0 | = | 2139 | 0 | 151 |
| external/kashiwaba-rl | 10-0-0 | 10-0-0 | = | 9114 | 427 | 263 |
| baselines/nearest-sniper | 8-2-0 | 8-2-0 | = | 2261 | 1304 | 247 |
| baselines/starter | 3-7-0 | **4-6-0** | +1W | 886 | 2855 | 303 |
| external/pilkwang-structured | 0-10-0 | **1-9-0** | +1W | 180 | 5521 | 160 |
| external/sigmaborov-reinforce | 0-10-0 | 0-10-0 | = | 0 | 4638 | 168 |
| external/sigmaborov-starter | 0-10-0 | **1-9-0** | +1W | 256 | 5687 | 232 |
| external/tamrazov-starwars | 0-10-0 | 0-10-0 | = | 0 | 4627 | 167 |
| external/yuriygreben-architect | 0-10-0 | 0-10-0 | = | 0 | 4522 | 161 |

**合計: 34W / 56L / 0D (勝率 37.8%) / Phase 1a: 31W-59L-0D, 34.4% / Δ = +3W (+3.4 pt)**

改善が出た相手: `baselines/starter` (+1), `external/pilkwang-structured` (+1, 初勝利), `external/sigmaborov-starter` (+1, 初勝利)。
`baselines/random`, `kashiwaba-rl`, `nearest-sniper` の既存勝ち試合は維持 (D-1 懸念回避)。
`sigmaborov-reinforce`, `tamrazov`, `yuriygreben` 相手は依然 0-10 で自スコア 0 のまま。

対 kashiwaba-rl の自スコア平均が 5679 → 9114 と大幅上昇 (敵が崩壊した後も production が積みあがっているため)。2P は序盤拡張テンポが明確に改善している兆候。

## 4P (9 体から 3 体ランダム抽出 × 3 試合)

| 指標 | Phase 1a | Phase 1b | Δ |
|---|---|---|---|
| 単独 1 位率 | 2.0% (5/252) | **1.2% (3/252)** | -0.8 pt |
| 自最終スコア 0 率 | 95.2% (240/252) | **97.2% (245/252)** | +2.0 pt |
| 平均ターン | 239 | 243.7 | +4.7 |

**4P では改悪**。Phase 1b の変更は 4P では効いていないどころか単独 1 位率が下がり、自スコア 0 で終わる試合が増加。

相手別「その相手がいるとき planet_intercept が 1 位になった率」:

| 相手 | matches | Phase 1a my_wins | Phase 1b my_wins | Δ |
|---|---|---|---|---|
| external/kashiwaba-rl | 84 | 5 (6.0%) | **3 (3.6%)** | -2 |
| baselines/nearest-sniper | 84 | 4 (4.8%) | **0 (0.0%)** | -4 |
| baselines/random | 84 | 4 (4.8%) | **3 (3.6%)** | -1 |
| external/sigmaborov-starter | 84 | 1 (1.2%) | 0 (0.0%) | -1 |
| baselines/starter | 84 | 1 (1.2%) | **3 (3.6%)** | +2 |
| external/pilkwang-structured | 84 | 0 | 0 | = |
| external/sigmaborov-reinforce | 84 | 0 | 0 | = |
| external/tamrazov-starwars | 84 | 0 | 0 | = |
| external/yuriygreben-architect | 84 | 0 | 0 | = |

- `nearest-sniper` が同卓 → Phase 1a は 4/84 勝てていたが Phase 1b は 0/84。4P で弱い相手に勝てなくなっている。
- `baselines/starter` 同卓は Phase 1a 1/84 → 3/84 と改善。中立 value 修正が kick しているシナリオもある。

## TrueSkill μ (Phase 1a 後起点、本計測後)

| agent | 2P μ Phase 1a | 2P μ Phase 1b | Δ 2P | 4P μ Phase 1a | 4P μ Phase 1b | Δ 4P |
|---|---|---|---|---|---|---|
| external/pilkwang-structured | 1075.4 | 1059.0 | -16.3 | 675.3 | 667.4 | -7.9 |
| external/tamrazov-starwars | 1043.8 | 1046.4 | +2.5 | 655.0 | 650.4 | -4.6 |
| external/yuriygreben-architect | 996.0 | 1000.7 | +4.7 | 675.5 | 681.9 | +6.4 |
| external/sigmaborov-reinforce | 958.4 | 966.9 | +8.5 | 664.1 | 665.6 | +1.6 |
| external/sigmaborov-starter | 801.8 | 813.9 | +12.2 | 584.4 | 591.9 | +7.6 |
| baselines/starter | 769.9 | 755.9 | -14.0 | 608.9 | 601.8 | -7.1 |
| **mine/planet_intercept** | **681.2** | **707.2** | **+25.9** | **595.7** | **596.7** | +1.0 |
| baselines/nearest-sniper | 598.9 | 590.0 | -8.9 | 578.1 | 578.5 | +0.3 |
| baselines/random | 462.2 | 450.0 | -12.1 | 573.9 | 574.6 | +0.6 |
| external/kashiwaba-rl | 422.0 | 413.4 | -8.6 | 570.7 | 575.0 | +4.3 |

planet_intercept は **2P μ +25.9** と大きく上昇 (zoo 内順位は 7 位から 6 位へ、baselines/starter を抜いた形)。
**4P μ +1.0** とほぼ変わらず、順位も 7 位のまま。

## 敗北リプレイ所見

### m054 vs external/sigmaborov-reinforce (Phase 1b の最速敗北 116t)

| t | 惑星 | 母星艦船 | フリート | フリート艦船 |
|---|---|---|---|---|
| 1 | 1 | 10 | 0 | 0 |
| 10 | 1 | 6 | 2 | 22 |
| 30 | 3 | 16 | 5 | 37 |
| 50 | 3 | 25 | 24 | **163** |
| 75 | 3 | 44 | 15 | 85 |
| 100 | 0 | 0 | 5 | 24 |

- Phase 1a の m090 (yuriygreben 戦で t=50 にホーム 1 個、35 艦のまま停滞) との対比: **t=30 に 3 惑星まで展開できている** (m090 は 1 惑星のまま)。中立 value 修正が序盤拡張には効いている。
- しかし t=50 でフリート艦 163 vs 母星艦 25 (総艦船の 87%) という偏りは Phase 1a と同じ。A-2 の reserve は incoming fleet 分しか確保しない設計なので、「向かって来ない将来脅威」には無防備。
- t=100 で 0 惑星。116t で敗北。

### m083 vs external/yuriygreben-architect (126t)

| t | 惑星 | 母星艦船 | フリート | フリート艦船 |
|---|---|---|---|---|
| 1 | 1 | 10 | 0 | 0 |
| 10 | 1 | 10 | 4 | 18 |
| 30 | 1 | 5 | 13 | 55 |
| 50 | 3 | 23 | 18 | 97 |
| 75 | 2 | 93 | 18 | 114 |
| 100 | 0 | 0 | 9 | 70 |

- **t=75 で母星艦 93** (Phase 1a の m090 相当 (母星艦 3) から大きく改善)。拡張とアクションのバランスは Phase 1a より健全。
- それでも t=100 で 0 惑星。相手 yuriygreben の集中侵攻を捌けていない。A-3 迎撃は t=75-100 の区間で十分な送出できていないか、ships_needed が enemy fleet ships+1 で過大になり発動していない可能性。

### m090 相当 (Phase 1a バグ再現ケース) の消滅

Phase 1a の m090 は「t=50 まで 1 惑星のまま拡張できず、艦船を細切れに送り続けて敗北」するパターンだった。Phase 1b 同条件相手 (yuriygreben) の敗北 m083 を見る限り、t=30 で 1 惑星 → t=50 で 3 惑星と拡張テンポは回復。targeting.py の中立 value 負値バグ は解消された。

## Phase 1a 比の評価

### 効いたもの

- **A-1 中立惑星 value 修正**: 2P で明確に効果。external 上位 5 体のうち 2 体 (pilkwang, sigmaborov-starter) に初勝利。敗北試合でも序盤 t=30 時点で複数惑星に展開できるようになり、m090 型の停滞は消滅。TrueSkill 2P Δ +25.9 が支持。
- **A-2 母星 reserve**: 少なくとも既存勝ち試合 (random, kashiwaba-rl, nearest-sniper) を崩していない。D-1 懸念は回避。

### 効いていない or 悪化したもの

- **A-3 迎撃**: 敗北試合の t=75-100 の急崩壊パターンは温存されている。迎撃候補が列挙されていても value が attack 候補と競合して選ばれていない、または ships_needed が過大で発動しない疑い。
- **A-4 4P 対応 (基盤のみ)**: 4P は単独 1 位率 2.0 → 1.2%、自スコア 0 率 95.2 → 97.2% と両指標が悪化。`compute_rival_eta_per_player` は計算値自体は 2P と同じ (min を取るラッパー経由) なので、Phase 1b の 4P 悪化の原因は A-4 ではなく **他の改修 (A-1 の中立 value インフレ、A-3 の迎撃誤発動)** が 4P で逆効果な可能性が高い。
  - 特に A-1 は「3 人から 1 人狙われる 4P」で中立惑星を積極的に取りに行く挙動が、他プレイヤーの侵攻を引き寄せて敗戦を早めている可能性。

## 未計測 / 次にやること

### 即対応 (Phase 1b 修正パッチ案)

1. **4P での中立 value 抑制**: `target_value` で「他プレイヤー数」を受け取り、4P では中立 future_income に減衰係数をかける。現行の `compute_rival_eta_per_player` を使えば他プレイヤー数の情報は既に取れる。
2. **迎撃の実発動状況を計測**: リプレイの action ログから「t ターンで送られた fleet が attack か intercept か」を分類してログに出す。迎撃が本当に 0 回なのか、発動しているが勝敗に寄与していないのかを切り分け。

### Phase 1c 候補

1. **迎撃発動条件の緩和**: `ships_needed = f.ships + 1` は厳密撃退閾値だが、敵 fleet を減衰させるだけでも価値がある設計 (partial intercept) に変更。
2. **4P 近接ペナルティ (A-4 オプション B)**: `compute_rival_eta_per_player` が既にあるので、2 番手以下の eta が my_eta より短いときに gain にペナルティをかける式を有効化して再計測。
3. **`HOLD_HORIZON` / `incoming_coef` の感度分析**: smoke 複数実行で 10/20/30 や 0.8/1.0/1.2 を比較。
4. **勝ち試合の分析**: 今回は敗因偏重。m044 (pilkwang 初勝利) や m065 (sigmaborov-starter 初勝利) の動きを追って、中立 value 修正が具体的にどこで効いたかを記録。

**最優先は 4P の悪化原因の切り分け**: A-1 が 4P で逆効果という仮説を、`HOLD_HORIZON=10` (より控えめ) で再計測して検証する。2P 勝率を維持したまま 4P 単独 1 位率が Phase 1a 水準 (2.0%) に戻るなら仮説が裏付けられる。
