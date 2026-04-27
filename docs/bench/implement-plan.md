# Phase 1c+ ロジックギャップ分析と実装計画

- 作成日: 2026-04-26
- 更新日: 2026-04-27
- 対象: `agents/mine/planet_intercept` vs baseline / external agents
- 目的: Phase 1b/1c 実装と 2P gauntlet 結果を踏まえ、次に実装すべき改善を整理する

---

## 現状サマリ

`mine/planet_intercept` は baseline よりは強いが、上位 external と比べると「未来の到着イベントを使った全体計画」が弱い。

現在 mine にあるもの:

- 太陽回避の近似ルーティング
- 軌道惑星の intercept 位置推定
- 中立/敵 target value
- defense reserve
- fleet intercept 候補
- doomed 判定 + 退避
- domination mode (`behind` / `neutral` / `ahead`)
- P0 修正: 無駄撃ち抑制

上位 external が共通して持つもの:

- `arrival_ledger`: fleet 到着予定の惑星別 ledger
- `timeline_simulation`: 将来 owner / ships / fall turn の予測
- `planned_commitments`: 送出予定を arrival turn 付きで管理
- mission planner: `capture` / `reinforce` / `rescue` / `recapture` / `snipe` / `swarm` / `crash_exploit`
- comet-aware future position / lifetime 評価
- 4P の multi-enemy defense / enemy crash exploit

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

## 新しい優先度

| 優先度 | 施策 | 目的 | 実装コスト | 状態 |
|---|---|---|---|---|
| P0 | Wasteful Launch Guard | 過大送出・1艦スパム・負 value 発射を止める | 小 | 採用済み |
| P1 | Arrival Ledger | fleet 到着予定を惑星別に正しく集約する | 中 | 次に実装 |
| P2 | Timeline Simulation | 将来 owner/ships/fall turn を予測する | 中 | P1 とセット |
| P3 | Budget/Defense を timeline 化 | ships_needed / reserve / doomed を同じ未来モデルに統一 | 中 | P2 後 |
| P4 | Intercept 調整 | 迎撃 spam を抑え、守る価値/必要量を改善 | 小-中 | P3 後 |
| P5 | Snipe Mission | 敵 fleet 到着前の中立先取り | 中 | ledger 後 |
| P6 | Multi-source Swarm | 複数拠点の同時着弾 | 大 | timeline 後 |
| P7 | Crash Exploit | 4P の敵同士衝突を横取り | 大 | 4P 対応 |
| P8 | Rear-to-Front Logistics | 後方艦船を前線へ流す | 中 | Phase 2 |

重要な方針:

**P1/P2 を先に作る。**  
planned tracking, defense, snipe, swarm, crash exploit はすべて arrival ledger / timeline simulation の上で実装しないと、今回の P1 のように誤推定で悪化しやすい。

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

## 実装ロードマップ

### Step 0: P1 試行の扱いを決める

現状の中立限定 planned は `24-66` で P0 より弱い。採用するならさらに絞る。基本方針は:

- P0 コミットは維持
- P1 heuristic はそのまま push しない
- ledger/timeline 実装時に planned を再導入

### Step 1: `world.py` 追加

- `Arrival`
- `PlanetState`
- `build_arrival_ledger`
- `resolve_battle`
- `simulate_planet_timeline`
- `first_turn_lost`
- `ships_needed_to_capture_at`

### Step 2: tests 追加

- `tests/test_world.py`
- 静止惑星 ledger
- sun crossing 除外
- production
- battle resolution
- fall turn
- capture budget

### Step 3: targeting 接続

- `enumerate_candidates` に `ledger` / `timelines` を渡す
- `ships_budget` の代わりに `ships_needed_to_capture_at`
- action 採用時に `Arrival(eta, player, ships)` を ledger に追加

### Step 4: defense 接続

- `classify_defense` を timeline 参照へ変更
- doomed / threatened / safe を `first_turn_lost` ベースにする
- intercept は timeline 上の不足分だけ送る

### Step 5: 計測

最低限:

```bash
uv run pytest agents/mine/planet_intercept/tests -q
uv run python -m orbit_wars_app.tournament gauntlet mine/planet_intercept \
  --bucket baselines,external --format 2p --games-per-pair 10 --seed 42 --mode fast
```

採用基準:

- P0 後 `26-64` を下回らない
- `random` / `kashiwaba-rl` の 10-0 を維持
- `nearest-sniper` / `starter` が P0 後より悪化しない

余力があれば:

```bash
uv run python -m orbit_wars_app.tournament gauntlet mine/planet_intercept \
  --bucket baselines,external --format 4p --games-per-pair 3 --seed 200 --mode fast
```

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
