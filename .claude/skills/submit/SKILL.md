---
name: submit
description: orbit-wars の Kaggle 提出を行うスキル。「Kaggle に提出」「submit したい」「提出スクリプト」などの依頼で使用。agents/mine/planet_intercept を tar.gz にまとめて kaggle CLI で提出する。
---

# submit

`agents/mine/planet_intercept` を Kaggle の orbit-wars コンペに提出する。

## 手順

### 1. コミットが完了しているか確認

提出前にコードが git にコミットされていることを確認する。未コミットがあれば先にコミットを促す。

```bash
git status
```

### 2. mise で提出

```bash
cd agents/mine/planet_intercept
MSG="<コメント>" mise run submit
```

`MSG` に gauntlet の WR や実装内容を入れる。例:

```
MSG="P7: Opening Expand (74.4% WR, +7.7pp vs P6)" mise run submit
```

### mise.toml の submit タスク内容

```toml
[tasks.submit]
run = """
tar --exclude='**/.DS_Store' --exclude='**/__pycache__' --exclude='**/*.pyc' -czf submission.tar.gz main.py src/
uv run kaggle competitions submit orbit-wars -f submission.tar.gz -m "${MSG:-submission}"
"""
```

含まれるファイル: `main.py`, `src/` 以下の全 .py ファイル

### 3. 提出履歴の確認

```bash
mise run submissions
```

### 4. リーダーボードの確認

```bash
mise run leaderboard
```

## コメントの書き方

```
P<フェーズ番号>: <機能名> (<gauntlet WR>%, <前フェーズ比 WR 増減>pp)
```

例: `P7: Opening Expand (74.4% WR, +7.7pp vs P6)`
