# 敗因指標の定義

`analyze_loss.py` / `diagnose_batch.py` が抽出する指標の定義と読み方。

## 終了系指標

### `home_fall_turn`

mine owner の所有 planet 数が **0 になった最初の turn**。

- 値が 100 turn 台: 速攻で崩された。開幕 defense / expand が競り負け
- 値が 200-300 turn: 中盤までは持ちこたえたが徐々に削られた
- `None`: 500 turn 完走。`total_turns < episode_steps` なら何らかのバグ

### `first_loss_turn`

mine が所有 planet を **初めて 1 つでも失った turn**。

`home_fall_turn` との差が小さいほど、崩れ始めから陥落までが急峻 (= 防衛が間に合わなかった)。

### `planet_parity_lost_turn`

`mine_planets < opp_planets` が初めて成立する turn。

`first_loss_turn` より早い場合、**自惑星を失ったわけではなく相手が先行 expand した** ことを意味する。median が 10-20 turn と極めて早い場合、開幕 expand の速度/方向選択で負けている。

## 圧力系指標

### `peak_incoming_to_mine`

任意 1 turn で mine 所有 planet に向かっている敵 fleet 数の最大値。

target 推定は fleet の angle と planet の相対位置で行う heuristic なので ±1-2 件の誤差はあり得る。

- 値が 10-20: 通常の攻勢
- 値が 30+: 一斉攻撃型。defense reserve が追いつかない可能性

### `peak_simultaneous_arrivals`

「同じ mine planet に向かう敵 fleet のうち、ETA を 2 turn バケットに分けて最多のバケットに何件入るか」。

- 値が 4-5: 通常
- 値が 8+: **同時着弾で一点突破されている**。multi-source swarm に近い攻撃を食らっているので、対症療法として defense forward-sim が要る

## 発射品質指標

### `mine_sun_crossings`

mine が発射した fleet のうち、**発射直後 30 単位以内に sun 周辺 (中心 (50,50), 半径 10) を横切るもの** の数。sun radius は公式値 ~8 より大きめに取って near-miss も拾う。

### `sun_crossing_ratio`

`mine_sun_crossings / mine_launches_total`。

- ratio < 3%: 太陽回避は機能している
- ratio > 10%: 太陽回避に穴があり、fleet が溶けている

## Milestone

`t=0, 25, 50, 75, 100, 150, 200, 300` (存在する範囲) における:

- `mine_planets` / `opp_planets`: 所有 planet 数
- `mine_ships` / `opp_ships`: 駐留 ships 合計 (fleet は含まない)
- `mine_fleet_ships` / `opp_fleet_ships`: 飛行中 fleet の ships 合計

読み方:

- t=25 で既に `mine_planets < opp_planets` なら **開幕 expand で負けている**
- t=50-75 で ships 比が 1:2 以上に開いていれば **生産で負けている → 高 production 惑星を取れていない**
- t=100 で planet 数が 1:2 なら事実上詰み

## 読み解き方の例

`diagnose_batch.py` の median 出力が次のとき:

```
planet_parity_lost     median=17
first_loss_turn        median=52
home_fall_turn         median=149
peak_simul_arrivals    median=6
sun_crossing_ratio(%)  median=1
```

読み:

- 17 turn で planet 数が逆転 → **開幕 expand が競り負け** (最大の問題)
- 52 turn で自惑星初敗北 → parity 逆転から 35 turn 後に本格的な防衛失敗
- 149 turn でホーム陥落 → 中盤で既に不利だった展開を挽回できなかった
- peak_simul=6 は中程度で致命ではない
- sun_crossing 1% は問題ではない (太陽回避は OK)

含意: 優先課題は **開幕 (t<25) の expand 方向選択と速度**。Map Characterization / Opening policy が効く可能性が高い。
