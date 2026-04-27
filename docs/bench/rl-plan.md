# Rule-based μ=1000+ と強化学習の段階的実装計画 (2026-04-27)

## 目的

Phase 0 の Rule-based 強化で TrueSkill μ=1000+ (external 強豪4体に対する WR 50%+) に到達し、
その過程で得られるリプレイとインフラを使って段階的に学習ベース (supervised → RL) に拡張する。

## 現在地

- `mine/planet_intercept` 現 μ=752 (n=1885)
- external 強豪 4 体 (pilkwang, sigmaborov-reinforce, tamrazov, yuriy) 合計 WR: 13/40 = **32%**
- 目標: **WR 50% 以上、μ=1000+** 到達で Phase 0 完了、Phase 1 着手の判定ライン

## 大方針

```
Phase 0: Rule-based μ=1000+        [P0-P6]
  ↓
Phase 1: 特徴量ログ基盤             [E1-E3]  (Phase 0 の後半と並行可)
  ↓
Phase 2a: LightGBM 盤面評価        [M-GBM-1..3]
Phase 2b: PyTorch 盤面評価          [M-NN-1..3]   (並行で両方試す)
  ↓
Phase 3: RL 方針学習               [RL-1..4]
```

---

## Phase 0: Rule-based μ=1000+ 実装計画

### 済みの改修

| ID | 項目 | 状態 |
|---|---|---|
| P0 | 会合点の速度不整合修正 | 完了 (commit 5bcaa53) |
| P1 | 同盟支援候補 (enumerate_support_candidates) | 完了 (commit 5bcaa53) |
| P2 | 過拡張ペナルティ | 完了 (commit 5bcaa53) |
| P3 | swarm tolerance 緩和 + focus bonus | 完了 (commit af8179f) |
| P4 | 敵高生産地フィルタ強化 | 完了 (commit 5037ba5) |
| P5 | 中央性ボーナス | 完了 (commit 5bcaa53) |

### 残る改修: P6 forward-sim board_value

**狙い**: 「1手ごとに局所 value を最大化」→「盤面価値の増分を最大化」に切り替え。

```python
def board_value(planets, fleets, player, timelines, horizon=25):
    v = 0.0
    for p in planets:
        state = state_at(timelines[p.id], horizon)
        if state and state.owner == player:
            v += state.ships + state.production * 20.0
        elif state and state.owner not in (player, NEUTRAL_OWNER):
            v -= state.ships + state.production * 20.0
    # 特徴量加点
    my_planets = [p for p in planets if p.owner == player]
    v += W_CENTRAL * central_share(my_planets)
    v -= W_FRONTLINE * frontline_pressure(my_planets, planets, player)
    v -= W_IDLE * idle_ship_ratio(my_planets)
    v += W_PROD_GAP * (my_production_sum - opp_production_sum)
    return v

# agent.py 内:
v_now = board_value(planets, fleets, player, timelines, horizon=25)
for cand in all_cands:
    apply_planned_arrival(ledger, timelines, planets, target_id=cand[0].id,
                          owner=player, ships=cand[1], eta=..., horizon=horizon)
    v_after = board_value(planets, fleets, player, timelines, horizon=25)
    delta = v_after - v_now
    revert_planned_arrival(...)  # undo
    cand.value = cand.local_value * ALPHA + delta * (1 - ALPHA)
```

**コスト見積もり**: 1 候補 ≈ 0.5 ms × 128 候補 = 64 ms/turn (現状の 13.5 ms に +48 ms、1 秒予算に対して余裕)

**実装量**: 100-150 行 (apply/revert の undo ロジックが重い)

**測定基準**:
- pilkwang / yuriy / tamrazov / sigmaborov-reinforce 各 10 戦で WR 50%+ を達成すれば Phase 0 完了

### Phase 0 まとめ

- 各 P ごとに必ず gauntlet で WR 差分を計測、効果が負なら rollback してパラメータ調整
- 調整対象パラメータ (優先順):
  - P5: `CENTRAL_BONUS_MAX=40` (強すぎるかも、20-60 で grid search)
  - P2: `OVEREXTEND_DOM_WINDOW=0.15` (0.1-0.3)
  - P3: `ETA_SYNC_TOLERANCE=8` (5-12)
  - P6: `ALPHA` (board_value と local_value のブレンド比、0.3-0.7)

---

## Phase 1: 特徴量ログ基盤

### E1: feature_extraction.py

`orbit_wars_app/feature_extraction.py` を新設。既存リプレイから以下を抽出:

```python
def extract_turn_features(obs, player, angular_velocity) -> dict:
    return {
        # global
        "step": ...,
        "remaining_turns": ...,
        # ships & production
        "my_total_ships": ...,
        "opp_total_ships": ...,
        "my_production": ...,
        "opp_production": ...,
        "neutral_planet_count": ...,
        # ratios
        "ships_ratio": my_total_ships / (my_total_ships + opp_total_ships + 1),
        "production_ratio": ...,
        # board shape
        "my_planet_count": ...,
        "opp_planet_count": ...,
        "my_central_share": ...,  # r<30 の割合
        "my_angular_spread_deg": ...,
        # dynamics
        "my_idle_ship_ratio": ...,  # ships > 20*production
        "my_expansion_rate_10t": ...,  # 直近10ターンの惑星数変化
        "opp_expansion_rate_10t": ...,
        "frontline_pressure": ...,  # 自惑星ごとの近傍敵ships総和
        # categorical (one-hot)
        "phase_early": step < 80,
        "phase_mid": 80 <= step < 300,
        "phase_late": step >= 300,
    }
```

per-planet 特徴量は別テーブルに (Phase 2 で使う):

```python
def extract_planet_features(planet, obs, player, angular_velocity) -> dict:
    return {
        "planet_id", "owner_enc" (one-hot or -1/0/1),
        "ships", "production", "radius",
        "r_from_center", "is_orbital",
        "dist_to_nearest_my", "dist_to_nearest_opp",
        "incoming_my_ships_total", "incoming_opp_ships_total",
        "incoming_my_min_eta", "incoming_opp_min_eta",
        "is_frontline",  # 近傍(距離<25)に敵惑星あり
        "will_flip_turns",  # simulate_planet_timeline で failt する turn (なければ 200)
    }
```

### E2: scripts/build_feature_dataset.py

```bash
uv run python scripts/build_feature_dataset.py \
    --runs runs/ \
    --output data/features.parquet \
    --output-planets data/planet_features.parquet
```

出力:
- `data/features.parquet`: 1 行 = 1 試合 × 1 ターン × 1 プレイヤー、~840k サンプル
- `data/planet_features.parquet`: 1 行 = 1 試合 × 1 ターン × 1 惑星、~20M サンプル (大きめなので Phase 2b 用)

### E3: 可視化ノートブック

Jupyter Notebook で勝ち試合・負け試合の特徴量分布を比較:
- my_central_share の時系列 (勝ち: 0.3+, 負け: 0.15- が予想)
- my_expansion_rate_10t の分布
- idle_ship_ratio

**成果**:
- 手書き board_value の重みチューニングの根拠
- Phase 2 の教師データ

**実装量**: 250-300 行 + Notebook

---

## Phase 2a: LightGBM 盤面評価

### M-GBM-1: データ準備

```python
import pandas as pd
from sklearn.model_selection import GroupKFold

df = pd.read_parquet('data/features.parquet')
# 1 game = 1 group (同一 game の複数 turn が train/valid にまたがらないように)
groups = df['game_id']
gkf = GroupKFold(n_splits=5)

# 教師信号: 連続値回帰 (勝敗+進捗)
# y = 1 if win else -1 を turn 進行で線形補間せず、単純に final_winner として使う
# (試合途中で逆転を学習させるため全ターンに同じラベルを与える)
y = df['final_winner_is_me'].astype(int)
```

### M-GBM-2: 学習

```python
import lightgbm as lgb

model = lgb.LGBMClassifier(
    n_estimators=500,
    learning_rate=0.05,
    num_leaves=31,
    min_child_samples=50,
    reg_alpha=0.1,
    reg_lambda=0.1,
)
model.fit(X_train, y_train, eval_set=[(X_valid, y_valid)], callbacks=[lgb.early_stopping(20)])
# numpy ベース推論への変換
model.booster_.save_model('agents/mine/v2-gbm/model.txt')
```

### M-GBM-3: 推論ラッパー

```python
# agents/mine/v2-gbm/src/board_net.py
import lightgbm as lgb

_MODEL = lgb.Booster(model_file=str(Path(__file__).parent / 'model.txt'))

def learned_board_value(obs, player, angular_velocity):
    features = extract_turn_features(obs, player, angular_velocity)
    x = np.array([features[k] for k in FEATURE_ORDER]).reshape(1, -1)
    return float(_MODEL.predict(x)[0])  # logit or probability

# agent.py 内で USE_LEARNED_BOARD_VALUE フラグで手書き版と切替可能に
```

### A/B テスト手順

```bash
# 学習モデル版
cp -r agents/mine/planet_intercept agents/mine/v2-gbm
# ↑ USE_LEARNED_BOARD_VALUE=True で手書き board_value を学習モデルに差し替え
uv run python -m orbit_wars_app.tournament head-to-head \
    mine/planet_intercept mine/v2-gbm --games 30
```

---

## Phase 2b: PyTorch 盤面評価 (並行で比較)

### M-NN-1: モデル設計

```python
import torch
import torch.nn as nn

class BoardValueNet(nn.Module):
    def __init__(self, global_dim=30, planet_dim=12, n_planets=40, hidden=64):
        super().__init__()
        # Per-planet encoder (DeepSet)
        self.planet_enc = nn.Sequential(
            nn.Linear(planet_dim, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden), nn.ReLU(),
        )
        # Global + aggregated planet → value
        self.head = nn.Sequential(
            nn.Linear(global_dim + hidden, hidden), nn.ReLU(),
            nn.Linear(hidden, 1),
        )

    def forward(self, global_feat, planet_feats, planet_mask):
        # planet_feats: (B, n_planets, planet_dim), planet_mask: (B, n_planets)
        h = self.planet_enc(planet_feats)  # (B, n_planets, hidden)
        h = (h * planet_mask.unsqueeze(-1)).sum(1) / planet_mask.sum(1, keepdim=True)
        return self.head(torch.cat([global_feat, h], dim=-1))
```

### M-NN-2: 学習

```python
# scripts/train_value_net_torch.py
import torch
from torch.utils.data import DataLoader

model = BoardValueNet()
opt = torch.optim.AdamW(model.parameters(), lr=1e-3)
criterion = nn.BCEWithLogitsLoss()

for epoch in range(50):
    for global_f, planet_f, mask, y in train_loader:
        logit = model(global_f, planet_f, mask)
        loss = criterion(logit.squeeze(-1), y)
        opt.zero_grad(); loss.backward(); opt.step()
    # validation WR など計測
```

### M-NN-3: 推論ラッパー (CPU)

```python
# agents/mine/v2-torch/src/board_net.py
import torch
import numpy as np

_MODEL = BoardValueNet()
_MODEL.load_state_dict(torch.load('model.pt'))
_MODEL.eval()

@torch.no_grad()
def learned_board_value(obs, player, angular_velocity):
    gf, pf, mask = extract_features_tensor(obs, player, angular_velocity)
    logit = _MODEL(gf, pf, mask)
    return float(torch.sigmoid(logit).item())
```

### LightGBM vs PyTorch 比較の観点

| 観点 | LightGBM | PyTorch MLP + DeepSet |
|---|---|---|
| 推論速度 | 0.5 ms | 1-3 ms |
| 特徴量エンジニアリング | 手動必須 | 自動獲得しやすい |
| モデルサイズ | ~1-2 MB | 100 KB-1 MB |
| Kaggle 提出 | 依存追加必要 | torch 必要 (重い) |
| Phase 3 への拡張性 | ない (stateless) | high (policy head 追加で直行) |
| チューニング容易性 | 高 (CLI 1コマンド) | 中 (hyperparam 多い) |

**推奨順序**: 先に LightGBM で baseline 確立 → PyTorch で上回れるか検証 → 上回ったら Phase 3 へ、上回らなかったら LightGBM 採用で Phase 0 の board_value チューニングに戻る

---

## Phase 3: RL (方針学習)

### 2 案併記

#### 案 A (本命): per-planet policy 学習

**構造**:
```
候補生成 (rule-based): enumerate_candidates → 候補 k 個
policy net: (planet_features, candidate_features) → 候補ごとのスコア
argmax → 1 候補選択
```

- 行動空間 = 候補数 (可変、~5-15) → discrete classification
- 状態 = (自惑星特徴量, 候補特徴量, 盤面特徴量)
- value head は Phase 2 を流用

#### 案 B (代替): モード選択 policy

**構造**:
```
mode_policy: board_features → one of {EXPAND, DEFEND, ATTACK, HARASS, CONSOLIDATE, BREAKTHROUGH}
sub_policy (rule-based): mode に応じた候補生成 + ships 配分
  EXPAND:     enumerate_candidates で中立優先
  DEFEND:     enumerate_support_candidates + enumerate_intercept_candidates
  ATTACK:     enumerate_candidates で敵惑星優先 + focus_bonus 強め
  HARASS:     敵の薄い前線 (ships < 10) を狙う
  CONSOLIDATE: reinforce (backlog P1-A) を優先
  BREAKTHROUGH: swarm を強制発動
```

**懸念 (前回議論した通り)**:
- per-planet と粒度が合わない (ある惑星は EXPAND、別の惑星は DEFEND が自然)
- モード間の切替コスト (ターン境界での flip flop)

**採用判断**: 案 A で進めるが、案 B を比較用 baseline として軽く実装しておくと「grand strategy」の粒度が本当に per-planet で良いかの答え合わせができる

### RL-1: self-play インフラ

```python
# scripts/self_play.py
def self_play_match(policy_model, opponent_model, seed):
    env = make("orbit_wars", debug=False)
    # (model, obs) -> action のラッパーを kaggle env の UrlAgent と同じ形で用意
    env.run([policy_wrapper(policy_model), policy_wrapper(opponent_model)])
    return env.toJSON()

def collect_trajectories(n_games):
    # 並列 self-play
    with Pool(4) as pool:
        replays = pool.map(self_play_match_one, range(n_games))
    return replays
```

### RL-2: PPO 学習

**報酬設計** (前回議論反映):
```python
# dense reward を避け、終局時 ±1 のみ discount で逆伝播
gamma = 0.99
returns[t] = final_reward * gamma ** (T - t)
```

**教師データ**:
- Phase 2 のリプレイで policy を pretrain (behavioral cloning)
- その後 self-play でファインチューニング

### RL-3: 評価 & swap

```python
def evaluate_swap(new_model, old_model, n_games=50):
    wins = sum(1 for _ in range(n_games) if self_play_match(new_model, old_model).winner == 0)
    return wins / n_games > 0.55
```

### RL-4: 外部 bot への汎化確認

self-play だけだと局所最適の risk があるので、以下でサニティチェック:
- pilkwang / yuriy / tamrazov / sigmaborov-reinforce に対する 2P gauntlet WR
- WR が self-play swap 後に**下がる**なら局所最適に陥った合図 → rollback

### 計算リソース見積もり

- 1 試合 self-play ≈ 7 秒 (2 agent fast mode)
- 並列 4, 100 試合/iteration ≈ 3 分
- 学習 1 iteration ≈ 2 分
- 1 iteration サイクル 5-7 分 × 50 iter = 4-6 時間
- 夜通し運用なら 2-3 日で policy 収束見込み

---

## やらないこと (scope-out)

以下は検討の結果、**現段階では採用しない**:

1. **画像ベース盤面入力 (CNN)**: 構造化データで十分
2. **AlphaZero 風 MCTS**: 1 秒予算で有意な rollout 数 (100+) は確保不可
3. **Transformer 系の attention policy**: overkill、MLP+DeepSet で十分
4. **Imitation learning from 外部リプレイ**: Kaggle LB の trajectory は入手困難、mine 含む自前 replay で十分

---

## 成功基準 (judgement rubric)

| Phase | 判定 | 基準 |
|---|---|---|
| Phase 0 | pass | external 強豪4 に対する合計 WR >= 50% (現 32%) |
| Phase 1 | pass | 840k サンプルの parquet が生成され、可視化で勝負分布が分離 |
| Phase 2 | pass | LightGBM または PyTorch 版が手書き版に h2h で 55%+ |
| Phase 3 | pass | self-play 50 iter 後、pretrain 版に対して h2h で 60%+ かつ 外部4 の WR が落ちない |

各 Phase で基準未達なら**そこで止めて原因分析**、前 Phase に戻って改善。
