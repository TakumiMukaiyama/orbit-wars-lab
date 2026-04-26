# Phase 1a ベンチ結果

- 計測日: 2026-04-25
- 環境: macOS darwin 24.6.0、Python 3.13.5、kaggle-environments 1.28.1
- コマンド: `uv run python scripts/bench_sim.py --games 3`
- 対戦: `baselines/v0_nearest.py` (nearest-sniper) 同士の 2P

## エージェント呼び出し時間 (v0 nearest-sniper)

| 指標 | 値 |
|------|-----|
| サンプル数 | 2760 (3試合 × 2 player × ~460 turn) |
| 平均 | 0.041 ms |
| 中央値 | 0.025 ms |
| p95 | 0.033 ms |
| 最大 | 46.421 ms |
| actTimeout 超過 (>1000 ms) | 0 / 2760 |

最大 46 ms は初手のコールドスタート含む。以降は 0.03 ms 前後で安定。

## 試合 wallclock

| 指標 | 値 |
|------|-----|
| 試合数 | 3 |
| 平均 | 3.32 s |
| 中央値 | 2.87 s |
| 最大 | 5.40 s |
| ターン数 | 382-499 (早期終了含む) |

## Phase 2 設計への含意

- actTimeout 1000 ms に対し v0 の実測は最大 46 ms。**約 20 倍の予算余裕**がある。
- 試合 wallclock が 3 秒前後なので、200 試合の評価バッチは 10-15 分で完了する見込み (シリアル実行)。
- シミュレータステップ時間は `env.step` 側に含まれるため分離計測していない。Phase 2 の自作 simulator を作った時点で numpy 版の 1 step 時間を別途ベンチする。
- 現状の予算感で、Phase 2 の greedy rollout は 1 step あたり ~1 ms 未満に収めれば `自惑星10 × 候補20 × D=15` ≒ 3000 step = 3 ms / 呼び出しで actTimeout に収まる想定。ただし Python 実装が実測何倍遅いかは Phase 2a 開始時に再計測する。

## 未計測事項 (Phase 2a 以降で測る)

- 自作 simulator の 1 step 時間 (現状は kaggle-environments の env.step を使うしかない)
- 4P 試合の wallclock
- 中盤以降の "フリート多" な状況でのエージェント呼び出し時間の劣化
