# RL対応リファクタリング設計

## 背景と目的

現行の `planet_intercept` エージェントはルールベースのヒューリスティックで実装されている。
今後の模倣学習 (Behavioral Cloning) → 自己対戦RL → distillation というロードマップに対応するため、
コードを3層に分解してRLとヒューリスティックが共通インフラを使えるようにする。

**制約:**
- 提出用の `agent(obs)` の動作を変えない
- 1秒制限のため推論は軽量に保つ
- 既存の `geometry.py` / `utils.py` / `world.py` は変更しない

---

## アーキテクチャ概要

```
agent.py
  └─ HeuristicPolicy.act(game_state)
       └─ enumerate_candidates / select_move (targeting.py - 既存)

state.py         (新設) GameState + 特徴量ベクトル化
action_space.py  (新設) Candidate dataclass + ships_bucket離散化 + invalid mask
policy.py        (新設) Policy ABC + HeuristicPolicy + ReplayLogger
```

---

## Layer 1 - 状態表現 (`state.py`)

### 責務
現在 `agent.py` 内でターンごとに計算している複数の状態変数を1つの構造体に集約する。
これがネットワーク入力の唯一のソースになる。

### `GameState` dataclass

```python
@dataclass
class GameState:
    player: int
    planets: list[Planet]
    fleets: list[Fleet]
    angular_velocity: float
    remaining_turns: int
    step: int
    my_planets: list[Planet]
    mode: str                          # "behind" / "neutral" / "ahead"
    domination: float                  # [-1, 1]
    timelines: dict[int, list[PlanetState]]
    ledger: dict[int, list[Arrival]]
    defense_status: dict[int, tuple[str, int]]  # planet_id -> (status, reserve)
    horizon: int
    is_opening: bool
```

`build_game_state(obs) -> GameState` 関数を公開し、現行 `agent.py` の前処理ロジックをここに移す。

### 特徴量ベクトル

BCおよびRL用に固定サイズのnumpy vectorを返す関数を提供する。
可変長の惑星数に対応するため、各惑星ごとの特徴量と盤面全体の特徴量を分離する。

**`planet_features(p: Planet, gs: GameState, source: Planet | None) -> np.ndarray`**

| 特徴量 | 次元 | 説明 |
|-------|-----|------|
| 相対x, 相対y | 2 | sourceからの変位 (sourceがNoneなら(0,0)) |
| 距離 | 1 | source-target間 |
| owner_onehot | 5 | [mine, enemy, neutral, comet, other] |
| ships | 1 | 正規化済み艦数 |
| production | 1 | 1-5 |
| is_orbital | 1 | 軌道惑星フラグ |
| timeline_state | 3 | ETA=10/20/40 時点の (owner==me, owner==enemy, ships) の概要 |
| defense_status | 3 | [safe, threatened, doomed] one-hot |

計 **17次元/惑星**

**`global_features(gs: GameState) -> np.ndarray`**

| 特徴量 | 次元 |
|-------|-----|
| domination | 1 |
| remaining_turns / 500 | 1 |
| my_planet_count / 20 | 1 |
| is_opening | 1 |
| mode_onehot | 3 |

計 **7次元**

---

## Layer 2 - 行動空間抽象化 (`action_space.py`)

### 責務
候補列挙の出力を統一された `Candidate` dataclassに変換する。
ネットワークの出力空間と一致するように ships を離散 bucket で表現する。

### `Candidate` dataclass

```python
@dataclass
class Candidate:
    source_id: int
    target_id: int
    angle: float
    ships: int          # 実際に送る艦数
    ships_bucket: int   # 0-4の離散インデックス
    value: float        # ヒューリスティックが計算した価値 (teacher label用)
    my_eta: float
    kind: str           # "attack" / "intercept" / "support" / "snipe" / "reinforce"
```

### Ships bucket定義

```
bucket 0: ships_needed (最小占領数)
bucket 1: ships_needed * 1.5 (安全マージン)
bucket 2: avail // 2
bucket 3: avail * 3 // 4
bucket 4: avail (全力)
```

`avail = source.ships - reserve`

### Invalid action mask

```python
def build_invalid_mask(
    source: Planet,
    candidates: list[Candidate],
    reserve: int,
) -> np.ndarray  # shape: (len(candidates),) bool
```

マスク条件:
- `source.ships - reserve < ships` (艦数不足)
- `value <= 0` (価値なし)
- 太陽直撃 (既に geometry.py で除外済みだが念のため)

### 変換関数

```python
def candidates_from_heuristic(
    mine: Planet,
    raw_attack: list,
    raw_intercept: list,
    raw_support: list,
    raw_snipe: list,
    reserve: int,
) -> list[Candidate]
```

既存の `enumerate_*` の出力タプルを `Candidate` に変換する薄いラッパー。
既存コードへの変更不要。

---

## Layer 3 - Policy interface (`policy.py`)

### `Policy` ABC

```python
class Policy(ABC):
    @abstractmethod
    def act(self, gs: GameState) -> list[tuple[int, float, int]]:
        """[[planet_id, angle, ships], ...] を返す (提出フォーマットと同一)"""
```

### `HeuristicPolicy`

現行 `agent.py` の意思決定ロジックをそのまま移植。
`build_game_state` で生成した `GameState` を受け取り、既存の `enumerate_candidates` / `select_move` を呼ぶ。
`agent.py` は `HeuristicPolicy().act(build_game_state(obs))` を呼ぶだけになる。

### `ReplayLogger`

模倣学習用のデータ収集クラス。環境変数 `ORBIT_WARS_REPLAY_LOG` が設定されているときのみ動作する。

```python
class ReplayLogger:
    def log_turn(
        self,
        gs: GameState,
        candidates_by_source: dict[int, list[Candidate]],
        chosen: list[Candidate],
    ) -> None
```

**記録形式 (JSON Lines):**

```json
{
  "step": 42,
  "player": 0,
  "global_features": [...],
  "sources": [
    {
      "source_id": 3,
      "planet_features": [...],
      "candidates": [
        {"target_id": 7, "ships_bucket": 2, "ships": 14, "kind": "attack", "value": 23.5, "my_eta": 8.2},
        ...
      ],
      "chosen_idx": 1,
      "chosen_target_id": 7
    }
  ]
}
```

`chosen_idx` がBCの教師ラベルになる。候補が空だった（no-op）場合は `chosen_idx: null`。

---

## ファイル構成変更

```
src/
  __init__.py        (変更なし)
  agent.py           (変更: build_game_state + HeuristicPolicy を使うよう薄くする)
  state.py           (新設: GameState, build_game_state, planet_features, global_features)
  action_space.py    (新設: Candidate, candidates_from_heuristic, build_invalid_mask)
  policy.py          (新設: Policy ABC, HeuristicPolicy, ReplayLogger)
  targeting.py       (変更なし)
  world.py           (変更なし)
  geometry.py        (変更なし)
  utils.py           (変更なし)
  cand_log.py        (変更なし - 既存デバッグログは残す)
```

---

## 変更しないもの

- `targeting.py` の `enumerate_*` / `select_move` / 各係数定数 — BC教師の中身なので変えない
- `world.py` のシミュレーション関数
- `geometry.py` の幾何計算
- `agent(obs)` の外部インターフェース (main.py経由の提出フォーマット)

---

## テスト方針

既存の `tests/` は全て通ることを確認する (リグレッション防止)。
新設モジュールに対して:
- `test_state.py`: `build_game_state` が既存 `parse_obs` と同等な状態を返すこと
- `test_action_space.py`: `candidates_from_heuristic` が既存 `enumerate_candidates` の出力を正しく変換すること
- `test_policy.py`: `HeuristicPolicy.act(gs)` が旧 `agent(obs)` と同一の moves を返すこと (同一seed)

---

## 将来の拡張 (本設計のスコープ外)

- `RLPolicy`: `Policy` の実装として後から追加。`act` は同じインターフェース
- `RLPolicy.train_step`: BCロスの計算。`chosen_idx` をラベルとして使う
- ships_bucketの数やboundary値のチューニング
- 4人戦用の `global_features` 拡張
