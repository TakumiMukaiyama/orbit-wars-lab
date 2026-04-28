# Phase 1c+ ロジックギャップ分析と実装計画

- 作成日: 2026-04-26
- 更新日: 2026-04-28
- 対象: `agents/mine/planet_intercept` vs baseline / external agents
- 目的: Phase 1b/1c 実装と 2P gauntlet 結果を踏まえ、次に実装すべき改善を整理する

---

## 現状サマリ

`mine/planet_intercept` は P6 (forward-sim board_value + multi-source swarm) まで実装し、2P gauntlet で 66.7% WR (60-30) に到達した。直近の gauntlet 結果: `runs/2026-04-28-001` (P6 後)。

現在 mine にあるもの:

- 太陽回避の近似ルーティング
- 軌道惑星の intercept 位置推定
- 中立/敵 target value (production asset scoring 込み)
- defense reserve (timeline ベース)
- fleet intercept 候補 (timeline 接続済み)
- doomed 判定 + 退避
- domination mode (`behind` / `neutral` / `ahead`)
- P0: 無駄撃ち抑制
- arrival ledger + timeline simulation (world.py)
- multi-source swarm (2-source)
- P6: forward-sim `board_value` による snipe mission scoring

上位 external が持っているが mine にないもの:

- comet future path / lifetime 評価 (彗星専用 intercept)
- map characterization (開幕マップ分類 + policy 切り替え)
- opponent typing (敵行動パターン分類 + 対応変更)
- script portfolio / greedy assignment による組み合わせ探索
- rear-to-front logistics
- crash exploit (4P 敵同士衝突横取り)
- scalar weight の進化的チューニング (CMA-ES)

---

## 直近実験結果

### P0: wasteful launch 抑制

実装内容:

- 中立惑星は到着まで production しないため、`ships_budget` で ETA 中の production 増分を足さない
- 既送艦で足りている候補は候補から除外
- `value <= 0` の手は送らない

2P gauntlet (`seed=42`, 90 matches):

| run | 内容 | W-L |
|---|---|---|
| `2026-04-26-012` | P0 前 | 23-67 |
| `2026-04-27-001` | P0 後 | **26-64** |

評価: 採用。無駄撃ちを減らし、2P で +3W。

### P1 試行: existing in-flight tracking

広い版:

- 既存自フリートを「進行方向上で最も近い非自惑星」に planned としてカウント

結果:

| run | 内容 | W-L |
|---|---|---|
| `2026-04-27-001` | P0 後 | 26-64 |
| `2026-04-27-002` | 広い P1 | **23-67** |

リプレイ所見:

- `nearest-sniper` match 003 で P0 は勝利、広い P1 は敗北
- P1 は敵惑星にも過大に planned を割り当て、攻撃候補を潰した
- 結果として `intercept` 小艦隊が大量発生し、t=75 以降に惑星数を逆転された

中立限定版:

- planned 対象を中立惑星のみに限定
- fleet 現在位置から対象までが sun crossing なら除外

結果:

| run | 内容 | W-L |
|---|---|---|
| `2026-04-27-001` | P0 後 | 26-64 |
| `2026-04-27-003` | 中立限定 P1 | **24-66** |

評価: まだ P0 より弱い。P1 は単独 heuristic ではなく、arrival ledger / timeline simulation の上に実装すべき。

---

## 優先度テーブル

| 優先度 | 施策 | 目的 | 実装コスト | 状態 |
|---|---|---|---|---|
| P0 | Wasteful Launch Guard | 過大送出・1艦スパム・負 value 発射を止める | 小 | 採用済み |
| P1 | Arrival Ledger | fleet 到着予定を惑星別に正しく集約する | 中 | 採用済み |
| P2 | Timeline Simulation | 将来 owner/ships/fall turn を予測する | 中 | 採用済み |
| P3 | Budget/Defense を timeline 化 | ships_needed / reserve / doomed を同じ未来モデルに統一 | 中 | 採用済み |
| P4 | Intercept 調整 | 迎撃 spam を抑え、守る価値/必要量を改善 | 小-中 | 採用済み |
| P5 | Snipe Mission | 敵 fleet 到着前の中立先取り | 中 | 採用済み |
| P6 | Multi-source Swarm + forward-sim board_value | 複数拠点の同時着弾 / snipe scoring 強化 | 大 | 採用済み (66.7% WR) |
| **P7** | **Opening Expand 改善** | **開幕 t=0-50 の惑星選択と ships 配分を直接改善し、planet parity 逆転を防ぐ** | **中** | **次に実装** |
| P8 | Comet Intercept | 彗星の future path / lifetime を使った確実な彗星確保 | 中 | P7 後 |
| P9 | Map Characterization | 開幕マップ分類 (静止惑星密度/太陽遮蔽/彗星距離) + policy 切り替え | 中 | P8 後 |
| P10 | Opponent Typing | 相手の行動を数十ターンで分類し reserve / 参加率を変える | 中 | P9 後 |
| P11 | Script Portfolio + Greedy Assign | expand / defend / comet / kill-shot の組み合わせ探索 | 大 | P9-P10 後 |
| P12 | Rear-to-Front Logistics | 後方艦船を前線へ流す | 中 | P11 後 |
| P13 | Crash Exploit | 4P の敵同士衝突を横取り | 大 | 4P 対応 |
| P14 | CMA-ES Weight Tuning | scalar weight を自己対戦リーグで進化的に最適化 | 大 | P11 後 |

重要な方針:

**P7 (Opening Expand 改善) を次の実装ターゲットにする。**  
gauntlet 解析 (`runs/2026-04-28-001`, 30 敗) で、敗戦 median の planet 数逆転が **t=17** と判明。彗星・太陽超えは問題ではなく、開幕 t=0-50 の expand 候補選択または ships 配分で先行されることが主因。Comet Intercept (旧 P7) は彗星寄与率が低いため P8 に繰り下げ。

---

## P7: Opening Expand 改善

### 問題の根拠

gauntlet 解析 (`runs/2026-04-28-001`) での 30 敗の median:

| milestone | mine | opp |
|---|---|---|
| t=25 | 3 planets | 2 planets |
| t=50 | 6 planets | 7 planets |
| t=100 | 8 planets | 16 planets |

planet 数逆転が **median t=17** で起きており、t=50 には既に差が開いている。太陽回避・同時着弾は問題ではない。

### 何をするか

開幕 t=0-50 で相手より多くの惑星を確保するため、以下を改善する:

1. **expand 候補の優先順位** - 競合リスクを込みにした候補スコアリング
   - 相手ホームから近い中立惑星は競合確率が高い: ETA 差が小さいほどスコアを上げる (先取り価値)
   - 相手の既存 fleet heading を見て、自分が先着できる候補だけを expand 対象にする

2. **ships 配分の最小化** - 中立取得に過剰な ships を送らない
   - `ships_needed = neutral.ships + 1` を遵守し、余った ships を次の expand に回す
   - 開幕 30 ターン以内は defense reserve を抑え expand 優先に切り替える

3. **expand ターゲット数の上限** - 1 ターンに送れる expand を絞る
   - 複数の同時 expand が分散して全部負けるパターンを防ぐ
   - 1 ターンあたり expand 発射を `max_expand_per_turn` (初期値 2) で制限

### 実装方針

`targeting.py` の変更:

```python
OPENING_TURNS = 40          # opening phase の長さ
MAX_EXPAND_PER_TURN = 2     # 1 ターンあたり expand 上限

def expand_priority_score(
    target: Planet,
    source: Planet,
    opp_eta: int | None,   # 相手の最速 ETA (None なら競合なし)
    eta: int,
) -> float:
    """開幕 expand での候補スコア。opp_eta が近いほど高く加点。"""
    ...
```

`agent.py` の変更:

- `current_turn < OPENING_TURNS` のとき `defense_reserve_rate` を 50% に下げる
- expand 候補が `max_expand_per_turn` を超えたら score 上位のみ発射

### テスト

- `opp_eta` が自 `eta` より小さいとき候補が除外される
- score は競合なし < 競合あり (競合ありの方が加点される)
- opening phase での reserve が非 opening より低い

### 評価指標

採用基準:

- 2P gauntlet (P6 後 `60-30`) を下回らない
- gauntlet 解析で median `planet_parity_lost_turn` が 17 より遅くなる

---

## P8: Comet Intercept

### 何をするか

観測に含まれる `paths` / `path_index` を使い、彗星の将来位置を正確に予測する。これにより:

- 現在は単に「彗星の現在位置へ向けて発射」しているが、到着時の位置へ lead shot する
- lifetime が切れる直前の彗星を無駄に追わない
- arrival ledger に彗星の出現・消滅を組み込み、timeline の精度を上げる

### 実装方針

`world.py` に追加:

```python
def comet_position_at(comet: Comet, future_turn: int) -> tuple[float, float] | None:
    """path_index + future_turn から彗星座標を返す。lifetime 切れなら None。"""
    ...

def comet_lifetime_remaining(comet: Comet, current_turn: int) -> int:
    """現在ターンから何ターン後に消えるか。"""
    ...
```

`targeting.py` の変更:

- 彗星への発射角を「現在位置」から「ETA 後の future position」へ変更
- ETA 算出時、fleet speed は通常通りだが、到着位置が動く分を反復で収束させる
- `comet_lifetime_remaining(comet, current_turn) < eta` なら候補から除外
- P5 Snipe の条件に彗星 lifetime チェックを追加

### テスト

- `comet_position_at` が正しいターンの座標を返す
- lifetime を超えたターンで None を返す
- targeting で ETA > lifetime の彗星が候補から除外される
- lead shot の到着角が現在位置ではなく将来位置を指す

### 評価指標

採用基準:

- 2P gauntlet (P7 後相当) を下回らない
- 彗星絡みのリプレイで「到着時に彗星消滅で空振り」が減っている

---

## P9: Map Characterization

### 何をするか

開幕 0-20 ターンでマップ特徴量を計算し、方針を切り替える。

研究では Planet Wars 系で有効とされており、Orbit Wars でも「静止惑星密度」「軌道帯強度」「太陽遮蔽の強さ」「彗星の取りやすさ」が方針に影響する。

### 特徴量候補

```text
static_planet_ratio   = 静止惑星数 / 全惑星数
inner_orbital_count   = radius < R_threshold の軌道惑星数
sun_blocking_score    = 自ホーム - 敵ホーム間の太陽との near-miss 角度
comet_proximity_score = 最初の彗星出現ターンと自ホームからの距離
```

### 方針切り替え候補

| マップクラス | 方針 |
|---|---|
| 静止惑星豊富 | 序盤は外周静止惑星を速攻、彗星参加は控えめ |
| 軌道帯支配 | 内側軌道惑星を opening で取り、production を固める |
| 太陽遮蔽強 | 迂回コストを加えた route evaluation を厳格化 |
| 彗星近距離 | 彗星 turn 50 前に front line を厚くする |

実装コスト: 小 (特徴量計算は数式のみ、方針は既存 `domination_mode` + `opening_bonus` の拡張)

---

## P10: Opponent Typing

### 何をするか

相手の過去 30-50 ターンの行動から、戦略タイプを推定し、こちらの reserve / 彗星参加率 / 迎撃積極度を変える。

### タイプ候補

| タイプ | 検出シグナル | 対応 |
|---|---|---|
| nearest-greedy | 常に近傍を刈る / reserve ほぼゼロ | 敵の手薄な後方を突く |
| expansion turtle | 静止惑星を固める / fleet 展開が遅い | 彗星争いに専念して production 差を作る |
| comet hunter | 彗星に毎回早期参入 | 彗星到着直前に先取り snipe |
| all-in rusher | 序盤に大部隊を送る | defense reserve を厚くして受け、後半 counter |

実装コスト: 小-中 (観測データ集計のみ、enemy fleet 先の追跡で実現可能)

---

## P11: Script Portfolio + Greedy Assignment

### 何をするか

research.md が示す Portfolio Greedy Search の考え方を Orbit Wars に適用する。

各ターン、以下の script を並列に評価し、得点が最も高い組み合わせを選ぶ:

| スクリプト名 | 内容 |
|---|---|
| expand | 近傍中立惑星を最小 ships で確保 |
| defend | timeline 上で落ちる自惑星へ必要量だけ送る |
| comet | 彗星 future position へ lead shot |
| snipe | 敵 fleet 到着前の中立先取り |
| kill_shot | 敵ホームへの swarm |
| logistic | 後方艦船を前線へ流す |

各惑星から 1 つの script を割り当てる greedy assignment を基本とし、P14 の CMA-ES tuning でスコア重みを最適化する。

実装コスト: 大 (現行 `enumerate_candidates` を script 駆動に書き換え)

---

## P12: Rear-to-Front Logistics

(P11 の script "logistic" として実装する。)

### 実装方針

timeline 後に以下で候補化する。

- source は `attack_budget` が十分あり、敵から遠い惑星
- target は敵惑星/中立/高 production threatened に近い自惑星
- logistic send は capture より低優先だが、何も攻撃候補がないときに発動

---

## P13: Crash Exploit

(4P 専用。)

### 何をするか

4P で複数敵 owner の arrival が同一惑星に近い turn で集まる場合、敵同士の戦闘後に少数艦で横取りする。

### 条件

- `arrival_ledger[target.id]` に複数 enemy owner が存在
- ETA 差が `<= 2`
- timeline 上、敵同士衝突後の ships が小さい
- 自 ETA が衝突直後に合う

Phase 2 で実装。2P には効かない。

---

## P14: CMA-ES Weight Tuning

### 何をするか

ルールは正しいが閾値が悪くて弱い、という状況を防ぐため、scalar weight を自己対戦リーグで進化的に最適化する。

research.md が指摘する通り、Planet Wars 系では「送船率」「防衛 reserve」「彗星優先度」「危険角度ペナルティ」などの scalar が多く、手動チューニングには限界がある。

### 対象パラメータ候補

```text
defense_reserve_rate    # 防衛に確保する ships の割合
comet_priority_weight   # 彗星 vs 通常惑星のスコア比率
asset_bonus_threshold   # production asset bonus の閾値
logistic_trigger_ships  # logistics を発動する後方 ships 閾値
opening_bonus_turns     # opening bonus を付ける序盤ターン数
snipe_eta_margin        # snipe で self_eta < enemy_eta の余裕ターン数
```

### 実装方針

- P11 script portfolio が完成してから実施
- CMA-ES (python `cma` パッケージ) で 50-200 個の weight を探索
- 評価: 自己対戦リーグ (固定 checkpoint 群 + ルール bot 群) での勝率
- 評価ノイズが高いため、各評価は複数 seed で平均を取る

---

## P1: Arrival Ledger

### 役割

既存 fleet を惑星別の到着イベントに変換する。

```python
@dataclass(frozen=True)
class Arrival:
    eta: int
    owner: int
    ships: int
```

出力イメージ:

```python
{
    12: [
        Arrival(eta=5, owner=1, ships=30),
        Arrival(eta=8, owner=0, ships=45),
    ],
    17: [
        Arrival(eta=11, owner=2, ships=20),
    ],
}
```

### 実装方針

新規ファイル候補:

- `agents/mine/planet_intercept/src/world.py`

最小 API:

```python
from dataclasses import dataclass

from .utils import Fleet, Planet

@dataclass(frozen=True)
class Arrival:
    eta: int
    owner: int
    ships: int

def build_arrival_ledger(
    planets: list[Planet],
    fleets: list[Fleet],
    horizon: int = 80,
) -> dict[int, list[Arrival]]:
    ...
```

初期版の制約:

- 静止惑星を優先して正確化
- 軌道惑星は現行 `fleet_heading_to` 相当の近似でよいが、結果が怪しければ除外
- `segment_hits_sun(f.x, f.y, target.x, target.y)` は除外
- out-of-bounds になりそうな fleet は除外
- 同一直線上に複数惑星がある場合は、forward distance が最小の惑星だけに到着すると扱う

### テスト

- 自 fleet が直線上の中立惑星に ledger 登録される
- enemy fleet も ledger 登録される
- 太陽を跨ぐ fleet は ledger 登録されない
- 同一直線上の手前惑星だけが登録される
- horizon 外の arrival は除外される

---

## P2: Timeline Simulation

### 役割

arrival ledger を使い、各惑星の未来 owner / ships をターンごとに予測する。

これにより以下を同じモデルで判断できる:

- 到着時に何隻必要か
- 既存味方 fleet で足りるか
- 自惑星が何ターン後に落ちるか
- reinforcement が何隻必要か
- snipe 可能か

### 実装方針

`world.py` に追加:

```python
@dataclass(frozen=True)
class PlanetState:
    turn: int
    owner: int
    ships: int

def simulate_planet_timeline(
    planet: Planet,
    arrivals: list[Arrival],
    horizon: int = 80,
) -> list[PlanetState]:
    ...
```

戦闘解決は `docs/overview.md` のルールに合わせる:

1. 同一 turn の arrival を owner 別に合算
2. 最大攻撃勢力と 2 位勢力を相殺
3. 残った攻撃勢力が planet owner と同じなら加算
4. 別 owner なら駐留艦と戦闘し、上回れば占領

注意:

- 中立惑星は production しない
- 所有惑星のみ毎ターン production
- comet は lifetime を持つため Phase 1 では通常 planet として扱い、Phase 2 で lifetime 対応

### テスト

- 所有惑星が production で増える
- 中立惑星は production しない
- 敵 arrival が駐留艦を上回ると owner が変わる
- 同 turn の複数攻撃 owner が相殺される
- 既存味方 arrival が防衛に加算される
- `first_turn_lost()` が正しい turn を返す

---

## P3: Budget / Defense の timeline 化

### 現状の問題

現在の `ships_budget` は簡易式:

- 中立: `target.ships + 1`
- 所有敵: `target.ships + production * eta + 1`
- planned は ships 合計のみで arrival turn を持たない

現在の `classify_defense` も簡易式:

- 15 turn 以内に向かっている敵 fleet の ships 合計だけを見る
- 既存味方 fleet、production、同時 arrival、複数敵相殺を見ない

### 実装方針

`targeting.py` の budget 計算を timeline 参照に置換する。

```python
def ships_needed_to_capture_at(
    planet: Planet,
    ledger: dict[int, list[Arrival]],
    player: int,
    eta: int,
) -> int:
    ...
```

defense も timeline から判定する。

```python
def first_turn_lost(
    planet: Planet,
    timeline: list[PlanetState],
    player: int,
) -> int | None:
    ...
```

`agent.py` の turn 先頭で:

1. `ledger = build_arrival_ledger(planets, fleets)`
2. `timelines = {p.id: simulate_planet_timeline(p, ledger.get(p.id, []))}`
3. `enumerate_candidates(..., ledger=ledger, timelines=timelines)`
4. action 採用時は `ledger[target.id].append(Arrival(eta, player, ships))`

### 評価指標

P3 後は P0 後を基準に比較する。

- 2P seed 42 gauntlet: `26-64` を下回らない
- `nearest-sniper`: `3-7` 以上
- `random`: `10-0` 維持
- `kashiwaba-rl`: `10-0` 維持
- 上位 external に 1 勝以上が出れば改善

---

## P4: Intercept 調整

### 現状の問題

P1 試行中のリプレイで、攻撃候補が消えた後に intercept が大量発生した。

典型:

- 多数の自惑星から同一 threatened 惑星へ 2-4 ships の小艦隊を送る
- 攻撃を止めてしまい、敵に planets 数で逆転される

### 実装方針

timeline 導入後、迎撃候補は以下に限定する。

- `first_turn_lost` が horizon 内にある惑星のみ
- defended planet の production が高い、または front line に近い
- 既に同じ defended planet へ reinforcement/intercept planned がある場合は追加しない
- `value = prevented_loss - ships - travel_penalty` に変更

最小改善:

- 同一 defended planet への intercept は 1 turn 1 本まで
- `ships_needed = f.ships + 1` ではなく、timeline 上の不足分を使う

---

## P5: Snipe Mission

### 何をするか

敵 fleet が中立惑星へ向かっているとき、自分が敵より先に占領し、敵 fleet を防衛側として受ける。

### ledger/timeline 後の実装

条件:

- target owner は neutral
- ledger[target.id] に enemy arrival がある
- 自 ETA が最初の enemy ETA より短い
- 自 arrival 後、enemy arrival を受けても保持できる

mission score:

```text
score = production * hold_turns + enemy_ships_absorbed - ships_sent - eta_penalty
```

---

## P6: Multi-source Swarm

### 何をするか

1 つの自惑星では足りない target を、複数自惑星から近い ETA で同時攻略する。

### timeline 後の実装

1. 各 target に対し source options を列挙
2. ETA 差が `<= 2-3` の source 組み合わせを探す
3. 合計 send cap が `ships_needed_to_capture_at(target, joint_eta)` を超えるなら mission 化
4. mission 採用時に ledger に複数 arrival を追加

Phase 1 では 2-source だけでよい。3-source は Phase 2。

---

## P7: Crash Exploit

### 何をするか

4P で複数敵 owner の arrival が同一惑星に近い turn で集まる場合、敵同士の戦闘後に少数艦で横取りする。

### ledger/timeline 後の実装

条件:

- `arrival_ledger[target.id]` に複数 enemy owner が存在
- ETA 差が `<= 2`
- timeline 上、敵同士衝突後の ships が小さい
- 自 ETA が衝突直後に合う

Phase 2 で実装。2P には効かないため、Phase 1c では後回し。

---

## P8: Rear-to-Front Logistics

### 何をするか

後方自惑星に溜まった ships を、前線または threatened 高 production 惑星へ送る。

### 実装方針

timeline 後に以下で候補化する。

- source は `attack_budget` が十分あり、敵から遠い惑星
- target は敵惑星/中立/高 production threatened に近い自惑星
- logistic send は capture より低優先だが、何も攻撃候補がないときに発動

---

## 外部エージェントとの差分表

| 機能 | mine | baseline | sigmaborov / pilkwang / tamrazov / yuriygreben |
|---|---|---|---|
| 近傍 target への攻撃 | あり | あり | あり |
| 太陽回避 | 近似あり | ほぼなし | あり |
| 軌道惑星 prediction | あり | なし | あり |
| comet lifetime / future path | ほぼなし | なし | あり |
| arrival ledger | なし | なし | あり |
| timeline simulation | なし | なし | あり |
| planned commitments | 簡易/試行中 | なし | arrival turn 付きであり |
| defense reserve | 簡易 | なし | timeline ベース |
| doomed evacuation | 簡易 | なし | rescue / salvage / recapture あり |
| snipe | なし | なし | あり |
| multi-source swarm | なし | なし | あり |
| crash exploit | なし | なし | あり |
| rear logistics | なし | なし | あり |

---

## 実装ロードマップ (P7 以降)

### Step 7: Opening Expand 改善 (P7)

- `targeting.py` に `expand_priority_score` を追加 (競合 ETA を加味したスコア)
- opening phase での `defense_reserve_rate` を下げる
- `max_expand_per_turn` で 1 ターンあたり expand 上限を設ける
- gauntlet 計測: P6 後 `60-30` を下回らない
- gauntlet 解析: median `planet_parity_lost_turn` が 17 より遅くなる

### Step 8: Comet Intercept (P8)

- `world.py` に `comet_position_at` / `comet_lifetime_remaining` を追加
- `targeting.py` の彗星発射角を future position へ変更
- lifetime 切れ候補の除外ロジック追加
- テスト追加 (`tests/test_world.py` に comet 系を追記)
- gauntlet 計測: P7 後を下回らない

### Step 9: Map Characterization (P9)

- `world.py` または新規 `map_features.py` に特徴量計算を追加
- `agent.py` の turn 0 で分類し、domination_mode / opening_bonus を切り替え

### Step 10: Opponent Typing (P10)

- `agent.py` 内に敵行動ログを保持するクラスを追加
- 30-50 ターン後から typing 結果を参照して reserve / comet 参加率を変える

### Step 11: Script Portfolio (P11)

- `targeting.py` を script 駆動に書き換え
- `expand` / `defend` / `comet` / `snipe` / `kill_shot` / `logistic` を実装
- greedy assignment でターンごとに組み合わせを選ぶ

### Step 12: CMA-ES Tuning (P14)

- P11 完成後に `tune/cma_es_tune.py` を作成
- `cma` パッケージで scalar weight を探索
- 自己対戦リーグ評価 (複数 seed 平均)

### 計測コマンド (共通)

```bash
uv run pytest agents/mine/planet_intercept/tests -q
uv run python -m orbit_wars_app.tournament gauntlet mine/planet_intercept \
  --bucket baselines,external --format 2p --games-per-pair 10 --seed 42 --mode fast
```

採用基準 (P7 以降の各 step):

- P6 後 `60-30` (66.7% WR) を下回らない
- `random` / `kashiwaba-rl` の 10-0 を維持
- 上位 external への勝率が改善している

---

## 判断メモ

今回の P1 失敗からの教訓:

- 「既存 fleet をどこかに向かっているとみなして ships を差し引く」だけでは危険
- arrival turn と future owner を持たない planned は、攻撃候補を過剰に消す
- defense/intercept は攻撃と同じ score 空間で競わせる必要がある
- arrival ledger / timeline simulation を先に入れる方が、後続機能の実装コストを下げる

---

## 実装ログ

### Group 1: Arrival ledger / timeline / 攻撃 budget 接続

- 追加: `src/world.py`
- 追加: `tests/test_world.py`
- 接続: `enumerate_candidates(..., timelines=...)`
- 目的: 既存 in-flight fleet と生産後の future state を見て、capture に必要な ships を見積もる
- テスト: `127 passed, 2 skipped`
- 2P gauntlet: `runs/2026-04-27-004`
- 結果: `27-63`

P0 後 `runs/2026-04-27-001` の `26-64` からは +1W。`nearest-sniper` と `starter` は改善したが、`sigmaborov-starter` の 1 勝を失った。

### Group 2: defense / intercept の timeline 接続

- 接続: `enumerate_intercept_candidates(..., timelines=...)`
- 目的: timeline 上で保持できる自惑星への迎撃候補を出さず、実際に落ちる惑星へ絞る
- テスト: `129 passed, 2 skipped`
- 2P gauntlet: `runs/2026-04-27-005`
- 結果: `31-59`

P0 後から +5W、Group 1 から +4W。`nearest-sniper` は `8-2` まで改善し、上位層への平均 ships も 0 から残るケースが増えた。一方で `starter` は `1-9` に悪化したため、次グループでは序盤展開を壊していないかを見る。

### Group 3: production asset scoring / opening orbital priority

- 接続: `target_value(..., remaining_turns, is_orbital, orbital_radius)`
- 目的: `starter` 型の「外側静止高productionを確保して500ターン粘る」勝ち筋に対抗する
- 変更:
  - 序盤の内側軌道惑星に opening bonus
  - production 4以上の静止惑星に asset bonus
  - 敵所有惑星も future production asset として正値評価
  - 実戦時の候補 pre-sort を production / inner orbital / static high production 優先へ変更
- テスト: `129 passed, 2 skipped`
- starter head-to-head: `runs/2026-04-27-006`
- starter 結果: `4-6`
- 2P gauntlet: `runs/2026-04-27-007`
- gauntlet 結果: `33-57`

Group 2 の `31-59` から +2W。`starter` は `1-9` から `4-6` に改善。`nearest-sniper` は `8-2` から `7-3`、`tamrazov-starwars` は `1-9` から `0-10` に落ちたため、副作用はある。現時点では total が改善し、問題視していた starter 型への耐性も上がったので採用寄り。

### Group 7: Opening Expand 改善 (P7)

- 追加: `OPENING_TURNS=40`, `MAX_EXPAND_PER_TURN=2`, `CONTENTION_BONUS_MAX=60` in `targeting.py`
- 追加: `expand_priority_score` in `targeting.py` (競合 ETA を加味したボーナス/フィルタ)
- 追加: `enumerate_candidates` に `is_opening` パラメータ (競合相手が先着する中立候補を除外、競合ありに加点)
- 追加: `agent.py` で opening phase 判定 + defense_reserve // 2 + expand_fired_this_turn カウント
- テスト: `171 passed, 2 skipped`
- 2P gauntlet: `runs/2026-04-28-002`
- 結果: `67-23` (74.4% WR)

P6 後 `60-30` から +7W (+7.7pp)。採用基準クリア。

| 相手 | P7 後 | P6 後 |
|---|---|---|
| nearest-sniper | 10-0 | 10-0 |
| random | 10-0 | 10-0 |
| starter | 10-0 | 10-0 |
| kashiwaba-rl | 10-0 | 10-0 |
| pilkwang-structured | 5-5 | 5-5 |
| sigmaborov-reinforce | 4-6 | 4-6 |
| sigmaborov-starter | 9-1 | 10-0 |
| tamrazov-starwars | 5-5 | 5-5 |
| yuriygreben-architect | 4-6 | 5-5 |

注: `sigmaborov-starter` が 10-0 → 9-1 にやや後退し、`yuriygreben-architect` が 5-5 → 4-6 に後退したが、他 opponent で取り返し総合 +7W。

---

### Group 4-6: forward-sim board_value + multi-source swarm (P6)

- 追加: `estimate_hold_turns` in `world.py`
- 追加: multi-source swarm (2-source) in `targeting.py`
- 追加: forward-sim `board_value` in `targeting.py` (P6 snipe scoring)
- 目的: snipe mission のスコアを timeline + hold_turns で正確に見積もる / 1惑星では取れない目標を 2拠点同時攻略
- テスト: 全 pass
- 2P gauntlet: `runs/2026-04-28-001` (c7cff67 時点)
- 結果: `60-30` (66.7% WR)

Group 3 の `33-57` から大幅改善 (+27W)。上位外部エージェントへの勝率も改善。
