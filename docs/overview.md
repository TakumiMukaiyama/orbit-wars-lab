# Orbit Wars - コンペティション概要

## 基本情報

| 項目 | 内容 |
|------|------|
| コンペ名 | Orbit Wars |
| 種別 | Featured |
| 賞金 | $50,000 |
| 締切 | 2026-06-23 |
| URL | https://www.kaggle.com/competitions/orbit-wars |

## タスク概要

100x100の連続2D空間でAIエージェントを戦わせるリアルタイムストラテジーゲーム。2人または4人対戦。
プレイヤーは惑星にフリートを送り込んで占領し、最終的に最も多くの艦船を保有した者が勝利する。

- ゲーム時間: 500ターン
- 勝利条件: ゲーム終了時に最多艦船数（惑星の駐留艦 + フリートの艦）を持つプレイヤー
- 早期終了: 1人（または0人）だけが惑星とフリートを持つ状態になったとき

## ボードレイアウト

- **ボードサイズ**: 100x100の連続空間（原点は左上）
- **太陽**: 中心(50, 50)に位置、半径10。フリートが太陽を横切ると破壊される
- **対称性**: 惑星・彗星はすべて4重鏡面対称に配置される - (x,y), (100-x,y), (x,100-y), (100-x,100-y)

## ゲーム要素

### 惑星 (Planets)

データ形式: `[id, owner, x, y, radius, ships, production]`

| フィールド | 説明 |
|-----------|------|
| `owner` | プレイヤーID (0-3)、または中立の場合 -1 |
| `radius` | 生産量に依存: `1 + ln(production)` |
| `production` | 1-5の整数。毎ターン、所有惑星はこの数だけ艦船を生産 |
| `ships` | 現在の駐留艦数 (5-99でスタート、低め寄り) |

**惑星の種類:**
- **軌道惑星**: `orbital_radius + planet_radius < 50` の惑星は太陽の周りを周回する (0.025-0.05 rad/turn)
- **静止惑星**: 中心から遠い惑星は動かない
- マップには20-40の惑星(4-fold対称の5-10グループ)が存在
- 静止グループが少なくとも3つ、軌道グループが少なくとも1つ保証される

**ホーム惑星:**
- ランダムに1グループがスタート惑星として選ばれる
- 2人対戦: 対角の惑星(Q1とQ4)からスタート
- 4人対戦: 各プレイヤーがグループから1つずつ
- ホーム惑星の初期艦船数: 10

### フリート (Fleets)

データ形式: `[id, owner, x, y, angle, from_planet_id, ships]`

**速度の計算:**
```
speed = 1.0 + (maxSpeed - 1.0) * (log(ships) / log(1000)) ^ 1.5
```
- 1隻: 1.0 units/turn
- ~500隻: ~5 units/turn
- ~1000隻: 最大6.0 units/turn

**フリートの消滅条件:**
- ボードの範囲外に出る
- 太陽を横切る
- 惑星と衝突する (戦闘が発生)

### 彗星 (Comets)

太陽周りの楕円軌道を飛ぶ一時的な天体。ターン50, 150, 250, 350, 450に4つ1グループで出現。

- 半径: 1.0 (固定)
- 生産量: 1 ship/turn (所有時)
- 速度: 4.0 units/turn (デフォルト)
- ボードから出ると艦船ごと消滅

`comets` フィールドにフルトラジェクトリ(`paths`)と現在位置(`path_index`)が含まれ、将来位置の予測が可能。

## ターン処理順序

1. **彗星期限切れ**: ボードを出た彗星を除去
2. **彗星スポーン**: 指定ターンに新グループを出現
3. **フリート発射**: 全プレイヤーのアクションを処理し新フリートを生成
4. **生産**: 全所有惑星（彗星含む）が艦船を生産
5. **フリート移動**: 全フリートを移動。範囲外・太陽衝突・惑星衝突を確認
6. **惑星回転・彗星移動**: 軌道惑星が回転、彗星が進行。移動した惑星/彗星に巻き込まれたフリートは戦闘へ
7. **戦闘解決**: キューされた惑星戦闘を一括解決

## 戦闘ルール

1. 到着フリートをオーナーでグループ化し、同オーナーの艦船を合算
2. 最大勢力と2番目の勢力が戦闘。差分が生き残る
3. 生き残り攻撃者がいる場合:
   - 同オーナー: 駐留艦に加算
   - 別オーナー: 駐留艦と戦闘。攻撃側が上回れば惑星を占領し余剰艦が駐留
4. 2つの攻撃勢力が同数の場合、全攻撃艦が消滅

## エージェントインターフェース

### Observation (入力)

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `planets` | `[[id, owner, x, y, radius, ships, production], ...]` | 全惑星（彗星含む） |
| `fleets` | `[[id, owner, x, y, angle, from_planet_id, ships], ...]` | 全フリート |
| `player` | `int` | 自分のプレイヤーID (0-3) |
| `angular_velocity` | `float` | 惑星の回転速度 (rad/turn) |
| `initial_planets` | `[[id, owner, x, y, radius, ships, production], ...]` | ゲーム開始時の惑星位置 |
| `comets` | `[{planet_ids, paths, path_index}, ...]` | 彗星グループデータ |
| `comet_planet_ids` | `[int, ...]` | 彗星のplanets ID一覧 |
| `remainingOverageTime` | `float` | 残りオーバータイム予算（秒） |

### Action (出力)

```python
[[from_planet_id, direction_angle, num_ships], ...]
```

- `from_planet_id`: 自分が所有する惑星ID
- `direction_angle`: 方向角 (ラジアン、0=右、π/2=下)
- `num_ships`: 送る艦船数（整数）
- アクションなしは `[]` を返す

## 設定パラメータ

| パラメータ | デフォルト | 説明 |
|-----------|---------|------|
| `episodeSteps` | 500 | 最大ターン数 |
| `actTimeout` | 1 | ターンあたりの制限時間（秒） |
| `shipSpeed` | 6.0 | フリートの最大速度 |
| `sunRadius` | 10.0 | 太陽の半径 |
| `boardSize` | 100.0 | ボードのサイズ |
| `cometSpeed` | 4.0 | 彗星の速度 (units/turn) |

## サンプルエージェント

```python
import math
from kaggle_environments.envs.orbit_wars.orbit_wars import Planet, Fleet

def agent(obs):
    player = obs.get("player", 0) if isinstance(obs, dict) else obs.player
    raw_planets = obs.get("planets", []) if isinstance(obs, dict) else obs.planets
    planets = [Planet(*p) for p in raw_planets]

    my_planets = [p for p in planets if p.owner == player]
    targets = [p for p in planets if p.owner != player]

    moves = []
    for mine in my_planets:
        nearest = min(targets, key=lambda t: math.hypot(mine.x - t.x, mine.y - t.y))
        ships_needed = nearest.ships + 1
        if mine.ships >= ships_needed:
            angle = math.atan2(nearest.y - mine.y, nearest.x - mine.x)
            moves.append([mine.id, angle, ships_needed])

    return moves
```

## 提出方法

```bash
# 単一ファイル
kaggle competitions submit orbit-wars -f main.py -m "コメント"

# 複数ファイル
tar -czf submission.tar.gz main.py helper.py
kaggle competitions submit orbit-wars -f submission.tar.gz -m "コメント"
```

`main.py` のルートに `agent` 関数が必要。

## ローカルテスト

```python
from kaggle_environments import make

env = make("orbit_wars", debug=True)
env.run(["main.py", "random"])

final = env.steps[-1]
for i, s in enumerate(final):
    print(f"Player {i}: reward={s.reward}, status={s.status}")

# Jupyterで可視化
env.render(mode="ipython", width=800, height=600)
```
