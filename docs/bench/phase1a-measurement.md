# Phase 1a 強さ計測

- 計測日: 2026-04-26
- ブランチ / HEAD: main @ ee815e4
- 対象: `agents/mine/planet_intercept` (Phase 1a ヒューリスティック: 目標価値 + 艦船予算 + 太陽回避)
- 環境: macOS darwin 24.6.0、Python 3.13.5、mode=fast (in-process)
- 計測前に `runs/trueskill.json` を `runs/trueskill.json.bak` に退避済

## コマンド

```bash
# 2P gauntlet (全 zoo, 各 10 試合)
uv run python -m orbit_wars_app.tournament gauntlet mine/planet_intercept \
  --bucket baselines,external --format 2p --games-per-pair 10 --seed 100 --mode fast

# 4P gauntlet (全 zoo, 各 3 試合)
uv run python -m orbit_wars_app.tournament gauntlet mine/planet_intercept \
  --bucket baselines,external --format 4p --games-per-pair 3 --seed 200 --mode fast
```

| 実行 ID | フォーマット | 試合数 | wallclock |
|---|---|---|---|
| 2026-04-25-002 | 2P | 90 | 224.7 s |
| 2026-04-25-003 | 4P | 252 | 2636.9 s (≒ 44 min) |

status 内訳: 全 342 試合 `ok`。crash/timeout/invalid_action は 0 件。

## 2P 勝率マトリクス (planet_intercept 視点)

| 相手 | W-L-D | 自スコア平均 | 敵スコア平均 | 平均ターン |
|---|---|---|---|---|
| baselines/random | 10-0-0 | 3004 | 0 | 130 |
| external/kashiwaba-rl | 10-0-0 | 5679 | 232 | 230 |
| baselines/nearest-sniper | 8-2-0 | 2872 | 1672 | 189 |
| baselines/starter | 3-7-0 | 763 | 5164 | 322 |
| external/pilkwang-structured | 0-10-0 | 0 | 5603 | 166 |
| external/sigmaborov-reinforce | 0-10-0 | 0 | 6232 | 167 |
| external/sigmaborov-starter | 0-10-0 | 0 | 6410 | 212 |
| external/tamrazov-starwars | 0-10-0 | 0 | 5528 | 182 |
| external/yuriygreben-architect | 0-10-0 | 0 | 5707 | 155 |

**合計: 31W / 59L / 0D (勝率 34.4%)**

注: external 上位 5 体 (pilkwang, sigmaborov-reinforce/starter, tamrazov, yuriygreben) に対しては **0/10 で自スコア 0 = 全惑星を奪われている**。

## 4P (9 体から 3 体ランダム抽出 × 3 試合)

- 単独 1 位率: 5/252 = **2.0%** (draws 0)
- 自分の最終艦船数 0 の試合: 240/252 = **95.2%**
- 平均ターン: 239

相手別の「その相手がいるとき planet_intercept が 1 位になった率」:

| 相手 | matches | my_wins_when_present |
|---|---|---|
| external/kashiwaba-rl | 84 | 5 (6.0%) |
| baselines/nearest-sniper | 84 | 4 (4.8%) |
| baselines/random | 84 | 4 (4.8%) |
| external/sigmaborov-starter | 84 | 1 (1.2%) |
| baselines/starter | 84 | 1 (1.2%) |
| external/pilkwang-structured | 84 | 0 |
| external/sigmaborov-reinforce | 84 | 0 |
| external/tamrazov-starwars | 84 | 0 |
| external/yuriygreben-architect | 84 | 0 |

## TrueSkill μ (計測後)

| agent | 2P μ | Δ | 4P μ | Δ |
|---|---|---|---|---|
| external/pilkwang-structured | 1075.4 | +2.4 | 675.3 | -2.4 |
| external/tamrazov-starwars | 1043.8 | +1.5 | 655.0 | (初) |
| external/yuriygreben-architect | 996.0 | +3.0 | 675.5 | (初) |
| external/sigmaborov-reinforce | 958.4 | +9.1 | 664.1 | (初) |
| external/sigmaborov-starter | 801.8 | +35.0 | 584.4 | (初) |
| baselines/starter | 769.9 | +23.9 | 608.9 | -3.1 |
| **mine/planet_intercept** | **681.2** | (初) | **595.7** | (初) |
| baselines/nearest-sniper | 598.9 | -8.0 | 578.1 | +4.0 |
| baselines/random | 462.2 | -7.4 | 573.9 | -0.3 |
| external/kashiwaba-rl | 422.0 | -6.7 | 570.7 | +13.0 |

現状 planet_intercept の 2P μ は zoo 中 7 位 (nearest-sniper と starter の間)。4P μ は 7 位 (baselines/starter より下、random/nearest-sniper と近い)。

## 敗北リプレイ所見 (2P gauntlet 上位 5 件)

リプレイごとに各ターンの「自分の惑星数 / 母星艦船合計 / フリート数 / フリート艦船合計」を抽出した。

### m024 vs baselines/starter (スコア差最大 18347)

| t | 惑星 | 母星艦船 | フリート | フリート艦船 |
|---|---|---|---|---|
| 50 | 6 | 104 | 43 | 334 |
| 75 | 10 | 194 | 92 | 627 |
| 100 | 10 | 110 | 160 | **1257** |
| 150 | 1 | 18 | 18 | 257 |
| 200 | 1 | 32 | 0 | 0 |

t=100 時点で総艦船 1367 中 1257 (92%) がフリートとして移動中。t=100→150 の 50 ターンで 10 惑星が 1 惑星まで崩壊した。相手 starter のカウンター侵攻を母星で受け止められていない。

### m064 vs external/sigmaborov-starter

| t | 惑星 | 母星艦船 | フリート | フリート艦船 |
|---|---|---|---|---|
| 75 | 7 | 145 | 147 | 675 |
| 100 | 7 | 128 | 224 | **1045** |
| 150 | 0 | 0 | 53 | 207 |

同じパターン: 100 ターンでフリート艦が母星艦の 8 倍を超えて全惑星を失陥。

### m001 vs baselines/nearest-sniper (2P で唯一 baseline への敗北の代表)

| t | 惑星 | 母星艦船 | フリート | フリート艦船 |
|---|---|---|---|---|
| 100 | 13 | 701 | 274 | 663 |
| 150 | 5 | 238 | 203 | 801 |
| 200 | 2 | 20 | 129 | 468 |
| 250 | 0 | 0 | 12 | 23 |

一時は 13 惑星 + 701 母星艦で優勢。そこから逆転される。相手のフリートが到着する前にさらなる攻勢をかけたが占領できず、結果として母星が空になり逆カウンターで全滅。

### m090 vs external/yuriygreben-architect (最速敗北 111t)

| t | 惑星 | 母星艦船 | フリート | フリート艦船 |
|---|---|---|---|---|
| 10 | 1 | 5 | 2 | 14 |
| 30 | 1 | 4 | 5 | 35 |
| 50 | 1 | 3 | 8 | 48 |
| 75 | 0 | 0 | 3 | 19 |

50 ターン経ってもホーム惑星 1 個のまま拡張できず、艦船を細切れに送り続けて母星が枯渇。序盤の惑星奪取テンポが完全に遅い。

### m050 vs external/pilkwang-structured (最速敗北 128t)

| t | 惑星 | 母星艦船 | フリート | フリート艦船 |
|---|---|---|---|---|
| 30 | 4 | 31 | 38 | 158 |
| 50 | 6 | 79 | 91 | 365 |
| 75 | 5 | 31 | 114 | 603 |
| 100 | 0 | 0 | 50 | 245 |

t=50 まではスコア互角だが、t=75 で母星艦 31、フリート 603 とバランスが極端に偏った直後に崩壊。

## m090 深掘り: targeting の挙動再現 (2026-04-26)

ユーザーから「近くの 18 艦惑星を放置して遠くの 6 艦惑星を歪んだ軌道で狙っていた」との目視観察があったため、リプレイの obs を parse_obs → enumerate_candidates → select_move に流し込んで、実際に planet_intercept 側で起きていた評価を再現した (コードは未変更)。

**t=1 (my_ships=10) の候補評価 (全 19 件):**

| idx | target | prod | tgt_ships | need | value | afford? |
|---|---|---|---|---|---|---|
| 0 | id=12 | 5 | 66 | 67 | +128.1 | no |
| 1 | id=0  | 5 | 28 | 29 | +153.0 | no |
| 2 | id=13 | 5 | 66 | 67 | +101.8 | no |
| ... | (prod=5 系 12 件全て need≥29) | | | | | no |
| 12 | id=4  | 4 | 18 | 19 |  +96.1 | no |
| 13 | **id=17** | 1 | 6 | 7 | -7.0 | **YES (picked)** |
| 14 | id=5  | 4 | 18 | 19 |   +1.6 | no |
| 15-16 | id=6,7 (prod=4, 18 艦) | 4 | 18 | 19 | -12.5..-19.0 | no |
| 17 | id=18 | 1 | 6 | 7 | -7.0 | YES |
| 18 | id=19 | 1 | 10 | 11 | -1.0 | no |

**実際の action ログ**: `t=2: [[16, -2.586, 7]]` → 目標 id=17 (南西方向、ボード中央の太陽を跨ぐので接線迂回発動 → 「歪んだ軌道」)

**発生していたこと:**
1. 母星 id=16 は ships=10 スタート。production=4 の 18 艦惑星 (id=4,5,6,7) は **need=19 で絶対届かない**。production=5 の 28 艦惑星 (id=0) は need=29、value=+153 で理論的最善だが届かない。
2. ships=10 で届く候補は **production=1 の 6 艦船惑星 2 つのみ** (id=17, id=18)。両方 value=-7.0 (後述)。
3. `enumerate_candidates` の sort は距離順なので近い id=17 が先に入り、`select_move` の strict `>` 比較で id=17 が picked される。距離自体の選択は正しい。
4. id=17 が南西方向で太陽を跨ぐため `geometry.tangent_waypoint` が発動して接線迂回 → 軌道が歪んで見える。

**本質的バグ**: 中立惑星 (rival_eta が有限値) の value が `production * max(0, rival_eta - my_eta) - ships_to_send` でほぼ常にマイナス値になる。targeting.py:42-51 の中立分岐 (`math.isinf(rival_eta)`) に入らないのは、`compute_rival_eta` が「敵惑星からの ETA」も計算対象に含めるため、中立惑星でも rival_eta が有限で返ってくるから。

```python
# 具体的な計算 (id=17 / id=18 とも)
# rival_eta ≒ 13-14 ターン (敵ホーム惑星からの到達), my_eta ≒ 11 ターン
# gain = 1 * max(0, 13 - 11) = 2
# value = 2 - 7 = -5 程度 (実際は -7.0 → gain=0 クランプ)
# → 中立惑星に「取るほうが得」という下駄が無い
```

その結果、**序盤は「仕方なく最高値」で負の value の近場 6 艦惑星を取りに行く** → 7 艦を送って母星 3 艦のまま → 到着時に相手 production が 13 ターン分増えて 6 艦 + 13 production = 19 艦に膨れて占領失敗 → m090 の t=30 時点「1 惑星 / フリート 5 / 合計 35 ships」の停滞。

## 共通の敗因パターン (数値ベース)

1. **母星の艦船過少**: 敗北試合の典型例で、中盤 (t=75-100) に総艦船の 80-95% がフリート中に集中。相手の迎撃 / カウンター侵攻が到着したときに母星に守備艦がほぼ残っていない。
2. **拡張テンポの遅さ**: yuriygreben 戦の m090 のように、50 ターン経ってもホーム 1 惑星のまま滞る試合が存在。惑星価値評価 or 艦船予算計算が「送れる条件」を満たさず待機している疑い。
3. **4P での壊滅率が 2P より高い**: 2P は kashiwaba/random には無傷で勝てるが、4P では自スコア 0 で終わる試合が 95%。複数の攻撃方向を同時にさばけていない (targeting が 1v1 前提で設計されている可能性)。

## Phase 1b / Phase 2 に向けた示唆 (観察ベース、想像の数字を使わない)

次の調査候補 (優先度順):

1. **中立惑星の value 評価を修正する** (m090 深掘りで確定したバグ) - `target_value` の gain 式 `production * max(0, rival_eta - my_eta)` が中立惑星で常に小さい値 / 0 にクランプされ、`value = gain - ships_to_send` が負になっている。修正方向の候補:
   - `rival_eta` の判定を「my_eta より確実に短いライバルが存在する場合のみ有効」に絞る (遠い敵惑星は脅威と見なさない)。
   - 中立惑星の base value に **到着後 N ターンの production 収益** (`production * expected_hold_turns - ships_to_send - my_eta * k`) を入れる。
   - `ships_budget` に到着時までの production 増分 `target.ships + target.production * my_eta + 1` を加算して「実際に占領できる艦船数」に揃える。
2. **母星守備の下限を select_move に組み込む** - 敗北 5 試合全てで中盤 (t=75-100) に母星艦が 0-110 に対しフリート 600-1257 艦という極端な偏り。`select_move(reserve=?)` の `reserve` 引数は既に用意されているが agent.py:24 の呼び出しで未指定 (デフォルト 0)。「送出後に残る艦 >= 最寄り敵惑星艦数 * 係数」のような動的 reserve を入れる。
3. **迎撃 (intercept) の実装** - Phase 1a は attack のみ。自分の惑星に向かう敵フリートへの迎撃送出を入れる (Phase 1b の既定スコープ)。
4. **4P での targeting 補正** - `compute_rival_eta` は現在「全非自分プレイヤー」から最小を取るが、4P では 3 人分合算される分、有利側惑星の value 評価が歪む可能性。「相手別に脅威度を個別評価」する改修余地あり。

上記は本計測レポート時点で数値的に裏付けが取れている観察のみ。Phase 2 のシミュレーション導入判断は、上記 1-4 の手当で勝率がどこまで伸びるかを先に見てから決める方針が無駄が少ない。

**最優先は 1**: m090 の再現で targeting.py:42-51 の設計が中立惑星を正しく評価できていないことがコード上で確定しており、これを直さない限りホーム周辺の拡張テンポが上がらない。2/3/4 はそれから。

## 未計測 / 次やること

- `--mode faithful` (Kaggle プロトコル模擬、subprocess+HTTP) での再計測。fast と faithful で勝率が大きくズレていないかの確認。
- 勝ち試合の分析 (何が効いているのか) - 本レポートは敗因偏重。
- planet_intercept の `agent.yaml` 追加 (現状 `has_yaml=false`, `tags=[]` で登録されている)。
