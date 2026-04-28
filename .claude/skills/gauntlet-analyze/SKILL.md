---
name: gauntlet-analyze
description: orbit-wars-lab の gauntlet run 結果と replay を定量分析して敗因を特定するスキル。runs/RUN_ID/results.json の W-L 集計、相手別内訳、敗北リプレイから home_fall_turn / planet_parity_lost / peak_incoming_fleets / sun_crossing_ratio などを抽出する。「run X の敗因を分析して」「bench 結果を定量化」「この run の 30 敗を分類して」「replay を解析」などの依頼で使用。
---

# gauntlet-analyze

orbit-wars-lab プロジェクトで、tournament gauntlet の結果と replay JSON を解析し、mine エージェントの敗因を定量的に特定する。

## 使い方

### 1. run 全体の集計

相手別 W-L と敗北 match のメタデータ (seed / turns / score) を一覧化する。

```bash
python3 .claude/skills/gauntlet-analyze/scripts/summarize_run.py runs/<run-id>
```

オプション:

- `--target AGENT_ID` (default: `mine/planet_intercept`)
- `--json` 機械読み取り用 JSON 出力

**出力の outcomes 分類:**

- `win`: 勝利
- `zero_early`: turns < episodeSteps (途中でホーム陥落)
- `blowout_full`: 500turn 完走かつ ratio < 0.1 (完敗)
- `close_full`: 500turn 完走かつ ratio >= 0.1 (競り負け)

敗因分析は `zero_early` が多いか `close_full` が多いかで方向が分かれる。

### 2. 個別 replay の深掘り

1 件の replay から敗因指標を抽出する。

```bash
python3 .claude/skills/gauntlet-analyze/scripts/analyze_loss.py \
  runs/<run-id>/replays/<NNN>-mine_planet_intercept__vs__<opp>.json
```

抽出される指標は [references/metrics.md](references/metrics.md) を参照。

### 3. run 内の全敗北を一括分析

```bash
python3 .claude/skills/gauntlet-analyze/scripts/diagnose_batch.py runs/<run-id>
```

オプション:

- `--opponent REGEX` 相手を絞る (例: `--opponent tamrazov`)
- `--limit N` 先頭 N 件のみ
- `--json` 全 record を JSON で出力

出力内容:

1. 全敗戦にわたる指標の分布 (min / median / mean / max)
2. 敗戦ごとの 1 行サマリ表
3. Milestone (t=0,25,50,75,100,150,200,300) 時点の両者 planet 数 / ships 数中央値

**注意**: `diagnose_batch.py` は同ディレクトリの `analyze_loss.py` を `import` する。スクリプトディレクトリ内で実行するか `PYTHONPATH` を通す。

## 典型ワークフロー

1. `summarize_run.py runs/<latest>` で全体 W-L と outcomes 分類を見る
2. `zero_early` が多ければ `diagnose_batch.py` で 30 敗全体の median を取る
3. median が示す主要敗因 (例: `planet_parity_lost` が 10 turn 台なら開幕競り負け、`peak_simul_arrivals` が 10+ なら同時着弾崩壊) から仮説を立てる
4. 仮説を検証するため、外れ値の match (median から大きく離れた件) 2-3 件を `analyze_loss.py` で個別確認
5. 必要なら replay の生 observation を特定 turn 付近で読む

## 実行前の確認

- `runs/<id>/results.json` と `runs/<id>/replays/` が揃っているか
- target agent の ID (`mine/planet_intercept` が既定)
- 新規 agent を比較する場合は `--target` で指定

## 詳細リファレンス

- [references/metrics.md](references/metrics.md): 各指標の定義、典型値、読み方
- [references/replay_schema.md](references/replay_schema.md): replay JSON の構造 (planet / fleet / action の形式)
