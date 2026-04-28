# Replay JSON 構造

`runs/<id>/replays/*.json` は Kaggle kaggle-environments 形式の replay。

## トップレベル

```python
{
  "id": str,
  "name": "orbit_wars",
  "configuration": {
    "episodeSteps": 500,
    "shipSpeed": float,
    "cometSpeed": float,
    "seed": int,
    ...
  },
  "rewards": [int, int],  # +1 / -1
  "statuses": ["DONE", "DONE"],
  "steps": [
    [  # step = list of per-agent states (len=2 for 2p, len=4 for 4p)
      {
        "action": [[src_planet_id, angle_rad, ships], ...],
        "observation": { ... },
        "status": "ACTIVE" | "DONE",
        "reward": int,
        "info": {}
      },
      ...
    ],
    ...
  ]
}
```

`len(steps)` は実際にプレイされた turn 数 (途中終了なら < episodeSteps)。

## Observation (各 step, 各 agent)

```python
{
  "step": int,
  "remainingOverageTime": float,
  "player": int,                 # this agent's index
  "planets": [ [id, owner, x, y, radius, ships, production], ... ],
  "fleets":  [ [id, owner, x, y, angle, ships, ???], ... ],
  "comets":  [ { "planet_ids": [...], "paths": [[[x,y],...],...], "path_index": int }, ... ],
  "comet_planet_ids": [...],
  "angular_velocity": float,
  "initial_planets": [...],
  "next_fleet_id": int
}
```

### Planet

| index | field | 備考 |
|---|---|---|
| 0 | id | |
| 1 | owner | -1=中立, 0/1/2/3=agent index |
| 2 | x | 0-100 |
| 3 | y | 0-100 |
| 4 | radius | |
| 5 | ships | |
| 6 | production | 静止惑星は高め、comet は特殊 |

### Fleet

| index | field | 備考 |
|---|---|---|
| 0 | id | |
| 1 | owner | 0/1/2/3 |
| 2 | x | |
| 3 | y | |
| 4 | angle | rad |
| 5 | ships | |
| 6 | (unknown) | 7 要素目の意味は未確認 |

### Action (step[i][agent_idx]["action"])

同 turn に発射された fleet のリスト: `[[source_planet_id, angle_rad, ships], ...]`。空なら `[]`。

## 物理定数 (公式実装より)

- Sun 中心: (50.0, 50.0)
- Sun radius: 約 8 (collision), fleet lifespan: ~400 turn
- 盤面: 100x100
- 座標系は y 軸が上向き

詳細は `docs/overview.md` や `agents/mine/planet_intercept/src/` を参照。
