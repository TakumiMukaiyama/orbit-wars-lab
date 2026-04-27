# 実装候補バックログ (2026-04-27)

Phase 1c 系の観察 (4P 敗北試合の目視、溜め込み → 何もしないターンの頻発) から
挙がった、まだ投入していない改修候補。実行順は「効果が大きそう & リスクが小さい」
を基準に並べる。各項目には計測と検証のフックも付けておく。

本バックログの前提で、直近入っている足場:

- `ORBIT_WARS_CAND_LOG=path` で候補列挙を JSON Lines 出力 (`src/cand_log.py`)
- Comet 除外 (`parse_obs.comet_planet_ids` + agent での pre-filter)
- `intercept_pos` の後方会合解 (最短 ETA 採用)

## P0: ログ取得と仮説検証 (ほぼ作業のみ)

| 項目 | 内容 | 目的 |
|---|---|---|
| 1試合ログ収集 | `ORBIT_WARS_CAND_LOG=runs/xxx/cand.jsonl` で 1 試合走らせる | 中立で詰まるか敵陣で詰まるかの判定材料 |
| 集計スクリプト | 「ターン×自惑星」ごとに `candidates が空 / 全 value<=0` の比率、picked=None の比率、target_owner 別の value 分布を出す簡易スクリプト | どこで詰まるかを可視化 |

検証基準: 「溜め込み発生」= 自艦 20+ かつ picked=None かつ next_turn も picked=None、を数える。
中立と敵陣のどちらが支配的かで P1/P2/P3 の優先順位を決める。

## P1: 静止自惑星の遊兵化対策 (本命)

**症状**: 外周の静止自惑星が 100+ 艦を溜め込んで発射しないターンが続く。
`target_value` で `production * HOLD_HORIZON - ships_to_send - my_eta * TRAVEL_PENALTY`
を計算したとき、遠征コスト (`ships_to_send` + `my_eta * 0.15`) が horizon 収益を上回って
value<=0 に沈むのが主因の仮説。

### P1-A: Reinforcement 候補の追加 (最推奨)

自軍同士の艦船移送を新候補として追加する。

- 発案: 余剰艦が貯まった静止自惑星から、前線に近い味方自惑星へ艦を流す手を加える
- 実装スケッチ:
  - `enumerate_reinforce_candidates(mine, my_planets, ...)` を新設
  - 候補条件: `mine.ships - reserve > THRESHOLD` かつ 受け手が攻撃距離圏内 (受け手の攻撃候補の my_eta が短い)
  - value は `received_ships * PRODUCTION_LEVERAGE - my_eta * TRAVEL_PENALTY` の暫定式
- 懸念: 敵の mass intercept を呼び込むと失艦リスク。最短路の segment_hits_sun は要チェック
- 計測: 2P ベンチで勝率 + 全体艦船数の時系列 (reinforce が実際に前線兵力を増やせているか)

### P1-B: TRAVEL_PENALTY の動的化

遊兵化の主因が `my_eta * 0.15` ペナルティだとわかった場合の次善策。

- 発案: 溜め込みが一定ターン続いたら penalty を一時的に下げる
- 実装スケッチ: `mine.ships` が閾値超のとき `TRAVEL_PENALTY` を 0 or 0.05 に落とす
- 懸念: 遠距離低 production 中立への無駄撃ちが増える。trigger 設計を慎重に
- 計測: 遠距離発射率 / ships 無駄撃ち率 vs 勝率

### P1-C: 遊兵監視モード

- 発案: 「X ターン連続で value<=0 しか出ていない自惑星」は強制的にベスト候補 (value 最大)
  を打つ、あるいは最寄り味方にフォールバック
- 実装スケッチ: agent 内で planet 単位の「連続無発射カウンタ」を session 的に持つか、
  timeline だけから推定する
- 懸念: state を持つと Kaggle 側で再現性が変わる。推定で済ませるなら timeline だけから

## P2: 候補選別の精度向上

### P2-A: source 側の遠征コスト別化

`enumerate_candidates` の sort_key は target 側の production/距離で優先度付けするが、
source 側の位置考慮がない。外周自惑星から中央軌道への候補が遠すぎて top_n=16 で
切れるのに、近傍高 production target は残るケースがある。

- 実装スケッチ: sort_key の priority に `- max(0, cur_dist - 30) * α` を足して近傍優遇
- 懸念: behind モードで遠距離攻撃の機会を奪いかねない

### P2-B: top_n=16 の見直し

外周自惑星が多い 4P 序盤では target が 30+ 個あり、top_n=16 で意図的に削る意味が薄い。

- 実装スケッチ: top_n を `min(32, len(targets))` に上げる。計算量は ledger が事前計算なので線形
- 計測: 1 ターン計算時間の変化

## P3: 迎撃 / スナイプの改善

### P3-A: Snipe の ahead/neutral 解禁

現状 `snipe_cands` は behind モードのみ。ahead でも「敵 fleet が中立を取る前に横から奪う」
のは有効なはず。

- 実装スケッチ: mode 判定を外すか、hold_turns 閾値を ahead 時は緩める
- 懸念: P5v2 で試して不採用になっている (docs/bench/experiment-log.md)。設計を読み直してから

### P3-B: 細切れ迎撃の再評価

`intercepted_ids` で同一 defended 惑星への迎撃を 1 turn 1 本に制限しているが、
大艦フリート相手だと 1 本では足りないケースがある。timeline 駆動で必要量を見てから
複数本出すオプション。

## P4: Comet 戦略 (将来)

現状は候補から除外しているだけ。ゲーム終盤で自軍 production を稼ぐ手として有効なら
再考する。楕円軌道予測と生存ターン推定が前提。

- 軌道の `paths` / `path_index` を使って彗星の残存ターンを推定
- 生存ターンが短いなら value に `production * min(hold_turns, lifetime)` を使う
- 実装前に「彗星占領が現在勝てている相手に対して無意味か有害か」をログで確認

## 実装と計測の運用

- 1 項目 1 commit。計測コマンド (2P round-robin × 10 games × seed=42) を毎回走らせ、
  劣化したら revert 前提
- 重要な観察は `docs/bench/experiment-log.md` に行を足す
- 仕組み系 (ログ足場、候補追加) と数値調整系 (閾値、penalty) は混ぜない

## 未決事項

- **反映順の合意**: まず P0 のログを取って詰まりの正体を特定する。その結果で P1-A / P1-B の
  どちらを先に当てるかを決める
- **Reinforcement の設計**: 受け手選定は「最短距離の自惑星」か「最も攻撃候補が豊富な自惑星」か
- **Snipe 再解禁**: 過去に不採用になった理由 (experiment-log.md 参照) を先に読む
