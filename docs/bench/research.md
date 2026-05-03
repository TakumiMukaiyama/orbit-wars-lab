# Orbit Wars で使える先行研究と実装方針

## 結論

率直に言うと、このコンペは**最初から純粋な end-to-end 強化学習だけで勝ち切るより、先に強いヒューリスティック／探索ベースを作り、その上に模倣学習や自己対戦RLを重ねる方が現実的**です。理由は、Orbit Wars が entity["organization","Kaggle","data science platform"] のシミュレーション系コンペの中でも、**可変長アクション列**、**連続角度**、**連続2D幾何**、**同時手番**、**1秒制限**、**2人戦と4人戦の両対応**を同時に持っており、RLが難しい典型条件をかなり多く満たしているからです。その一方で、環境はフルオブザーバブル寄りで、seed により再現可能で、彗星の将来軌道も observation に含まれるため、正確な前向きシミュレータを作る価値が非常に高いです。さらに公式実装では最終的な艦船数で勝敗を決めつつ、報酬は**勝者 +1 / 非勝者 -1**の二値で与えられるので、スコア差最大化より**勝率最大化**が本質になります。citeturn40view0turn41view0turn42view3turn43search2

もっとも近い系譜は、entity["video_game","Planet Wars","google ai challenge 2010"] と、その元になった entity["video_game","Galcon","space strategy game"] です。ただし Orbit Wars はそこに、**太陽による飛行経路破壊**、**軌道惑星の移動**、**彗星という期限付き資源**、**惑星移動による sweep 衝突**、**4人戦**を加えており、古典的 Planet Wars よりも「到達時刻予測」と「安全な発射角の選択」がはるかに重要です。したがって、最も再利用価値が高いのは一つの先行研究ではなく、**Planet Wars 系のマクロ意思決定**、**Kaggle RTS 系の学習・蒸留の実装知見**、そして entity["video_game","microRTS","research rts environment"] や entity["video_game","StarCraft II","blizzard 2010"] に蓄積された**行動空間圧縮・自己対戦・リーグ学習・探索**を組み合わせるやり方です。citeturn45search0turn45search2turn15view0turn10view0turn33view0

## ゲーム構造の読み解き

Orbit Wars の公式仕様で特に重要なのは、環境が `episodeSteps=500`、`actTimeout=1`、`agents=[2,4]` で、彗星グループの `paths` と `path_index` が観測に入り、seed も設定に記録されることです。つまり、**同じ seed なら完全再現評価がしやすく、彗星だけは未来位置を正確に使った planning ができる**構造になっています。これは、探索・チューニング・学習のどれを選んでもかなり有利です。citeturn40view0turn6view1

一方で、難しさの本体は幾何側にあります。公式実装ではフリート移動時に**線分と太陽・惑星の連続衝突判定**をしており、さらにその後で**軌道惑星や彗星が動き、その sweep に巻き込まれたフリートも戦闘に入る**ようになっています。つまり、「今は通れる角度」でも、移動中や到着直前に死ぬケースがあり、静的距離だけで target を選ぶとかなり弱いです。艦数が増えるほど速度が上がる非線形速度式もあるため、**到達時刻は送る艦数に依存**します。これは Planet Wars よりも「どこへ送るか」だけでなく「何隻送るか」で到着可否が変わることを意味します。citeturn41view0turn42view3

もう一つ、見落としやすいのが目的関数です。環境内部では各プレイヤーの最終艦船数を集計して勝者を決めますが、提出エージェントが受け取る reward は**最大スコアのプレイヤーのみ +1、他は -1**です。4人戦では同点首位が複数いれば複数人が +1 になり得ます。したがって、評価関数も学習ターゲットも「期待艦船差」だけに寄せるとズレやすく、**勝率・首位確率・生存率**に寄せる方が仕様に合っています。citeturn42view3

公式 starter agent が「**静止惑星のみ**から近い敵を選び、半分の艦を送る」という非常に保守的な実装であることも示唆的です。これは、主催側のベースラインですら orbiting target interception を簡略化している、ということです。つまり、**静止惑星と彗星を上手く刈るだけでもかなり差別化できる余地**があります。citeturn42view3

## 直接近い先行研究

一番近いのはやはり entity["video_game","Planet Wars","google ai challenge 2010"] 系です。この系統は 2010 年の contest として広く使われ、planet conquering、ships in transit、simultaneous decisions という構造を持つ簡潔な RTS テストベッドとして扱われました。後続研究では、高速前向きモデルを持つ Planet Wars 変種が**統計的 forward planning**の試験場として使われ、1 秒未満の時間制約下での探索アルゴリズム検証に適していると報告されています。Orbit Wars もほぼ同じ理由で、**高速シミュレーションを中心に据えた bot 設計**と相性が良いと見てよいです。citeturn45search0turn45search2turn15view0

この系譜で Orbit Wars に特に刺さるのは、**map characterization** の考え方です。Planet Wars では、1秒という短い制限時間の中でマップを高速に特徴付けし、それに応じて specialized strategy を切り替える研究がありました。Orbit Wars でも、開幕数ターンで「静止惑星が近い map か」「軌道帯が強い map か」「太陽をまたぎやすいか」「彗星が取りやすい象限か」を判定し、**同一 policy ではなく map class ごとの policy**を持つのが自然です。これは 2人戦ではとても効きやすく、4人戦でも最低限の開幕方針選択として機能します。citeturn47search18

ヒューリスティックを hand-tune するだけでなく、**進化計算で重みや閾値を最適化する**という流れも Planet Wars ではかなり早くから存在しました。進化的パラメータチューニングでトップ20%に入った bot、遺伝的プログラミングで decision tree を合成した bot、4人対戦を意識した co-evolution、さらには expansion / defense / rebalancing を分けて蟻コロニー最適化で扱う研究まであります。Orbit Wars では「送船率」「防衛 reserve」「彗星優先度」「危険角度ペナルティ」「終盤 all-in 条件」など、調整すべき scalar が多いので、この流れはかなりそのまま使えます。citeturn15view1turn16search1turn16search3turn15view2

マップ生成側の研究も参考になります。Planet Wars では、**平衡性の高い map を進化的に生成する**研究があり、複数の playable and balanced maps が得られたと報告されています。Orbit Wars 自体は主催者実装で seed ベースの対称マップ生成を行っていますが、研究としては逆にこのアイデアを使って、**bot の弱点を突く seed を自分で発見する adversarial evaluation**ができます。つまり、公開環境で単に random seeds を回すだけではなく、「自 bot が苦手な map family を進化的に掘る」ことが有効です。citeturn47search0turn47search17

現時点の Orbit Wars 自体にも、公開 notebook はもう出始めています。検索で確認できる範囲でも、**“Tactical Fleet Control and Expansion”**、**“Sun-Dodging Baseline”**、**“Reinforcement Learning Tutorial”** が公開されています。ただし、Kaggle 側のページ制限のため、この調査では notebook 本文の詳細までは十分に読めず、ここで確実に言えるのは**早くも「幾何安全性」と「RL 基盤」の二方向で参加者が動き始めている**という点までです。citeturn49search0turn38search0turn38search1

## Kaggle と RTS 研究から抽出できる原則

Kaggle の RTS 風シミュレーション競技全体を見ると、**ルールベースが想像以上に強い**という共通点があります。2024年の winning microRTS agent 論文では、Kaggle の RTS-like simulation competitions として Halite、Lux AI、Kore、Lux AI Season 2 が挙げられ、**Halite、Kore、Lux AI Season 2 は rules-based agents が勝った**と整理されています。一方で、Lux AI Season 1 だけは RL 勝利でした。Orbit Wars は複雑ではあるものの、観測はかなり構造化され、環境は deterministic で、実時間制約が厳しいので、**初期勝ち筋は rules/hybrid 側に寄る**と見るのが自然です。citeturn10view0turn29search1

ただし、RL が通るときのパターンもかなり明確です。Lux AI Season 1 の優勝 write-up では、ResNet 系の fully convolutional body に対し、**IMPALA + UPGO + TD-lambda**、teacher policy との **KL regularization**、初期の **reward shaping** から後半の **sparse win/loss** への移行、そして **illegal action masking** が使われていました。これは Orbit Wars にそのまま翻訳できます。すなわち、最初は「中立惑星の確保」「生産差」「ホーム防衛」「彗星確保」などの dense rewards で立ち上げ、最終的には勝敗報酬に寄せる、という流れです。citeturn25view0turn25view1turn25view2

さらに RL を本番投入するときは、**単一ネットワークで全部を解く必要はない**ことも重要です。microRTS の competition-winning DRL では、自己対戦だけでなく既存強 bot への fine-tuning、map-specific specialization、そして compute budget に応じた複数 policy の使い分けが勝因として挙げられています。Lux AI Season 2 の上位 DRL 解法でも、速度制約を意識した DoubleCone 系 backbone や shaped-to-sparse の training schedule が重視されていました。Orbit Wars でも、**2人戦用・4人戦用の分離**、さらに「開幕」「中盤」「終盤」や map family ごとの specialist を持つ方が、単一万能 policy より現実的です。citeturn34search19turn29search1turn29search3

自己対戦の設計では、entity["organization","Google DeepMind","ai lab"] の AlphaStar 系が示した、**模倣学習で初期政策を作り、diverse league の中で counter-strategy を育てる**という流れがやはり強いです。Orbit Wars は 2人戦だけ見ればゼロ和に近いので league training と相性が良く、4人戦でも少なくとも opponent pool を多様化する価値は高いです。さらに programmatic strategy の世界では、PSRO 系統の Local Learner が、単一相手への best response を繰り返すよりも、**役に立つ opponent set を能動的に選んだ方が強い search signal が得られる**ことを示しています。Orbit Wars の自己対戦でも、**直近 checkpoint だけでなく、rush 型、greedy expand 型、comet hunter 型などを混ぜた相手プール**にするべきです。citeturn33view0turn30view0

探索の観点でも、再利用できる原則はかなりあります。RTS では branching factor が巨大なので、CMAB ベースの NaiveMCTS が branching factor の増大時に有利であること、script portfolio で行動候補を圧縮する Portfolio Greedy Search が medium-to-large scenarios で Alpha-Beta と UCT を上回ったこと、さらにその欠点を補う Nested-Greedy Search が μRTS で state of the art を超えたことが報告されています。Orbit Wars の行動空間も、各惑星から任意角度・任意隻数を撃てるので、そのままでは大きすぎます。したがって、**候補ターゲットと ships bucket をスクリプトで圧縮し、その上に root search を乗せる**のがかなり筋のよい設計です。citeturn31view2turn31view0turn31view1

最後に、invalid action masking は理論的にも実務的にも重要です。Huang と Ontañón は、masking が**正当な policy gradient**に対応し、invalid action が多いほど、penalty 方式よりもずっとスケールしやすいと示しました。Orbit Wars では、少なくとも「自分の惑星でない」「保有艦数が不足」「彗星切れ」「太陽直撃が確定」などで action 候補を強く減らせるので、RL をやるなら masking は必須級です。citeturn32view1

## ヒューリスティック案

ヒューリスティックで本気で勝ちに行くなら、核になるのは**正確な forward simulator**です。Orbit Wars は deterministic で、ターン順序も固定されており、彗星軌道は観測で与えられ、衝突判定も幾何的に明確です。したがって、「この角度で何隻送ると、何ターン後に、どの planet/comet/sun とどう干渉するか」を数十～数百候補だけでも正確に見積もれる bot は、単純 nearest-target bot をかなり上回れます。特にこのゲームでは、**target へ向かう線分が太陽を横切るか**、**到着前に target が動いて sweep してくるか**、**同時着弾で何勢力がぶつかるか**が重要で、どれも静的評価だけでは壊れます。citeturn41view0turn42view3

私なら評価関数を、最終スコアそのものではなく、**勝率近似**に寄せます。具体的には、現在の駐留艦 + in-flight 艦 + 近未来の期待生産をベースにしつつ、そこへ「今後 20〜60 ターンで安全に維持できる生産量」「守備 reserve を割った脆弱惑星数」「相手ホームへの到達 possibility」「彗星の取得期待値」を加減します。4人戦ではこれに加えて、**自分が1位になる確率**と**脱落しない確率**を別々に持った方がよいです。仕様上の reward が二値なので、終盤は艦数差を広げるより、「首位確保のための安全行動」に寄せるべきです。citeturn42view3

行動生成は、連続角度をそのまま探索しない方がよいです。現実的なのは、各自惑星ごとに  
**候補ターゲットの離散集合**を作り、そこから angle を計算する方式です。候補は、静止中立、軌道中立、敵前線、敵ホーム、自軍防衛、彗星 intercept の 6 系統で十分です。そのうえで ships は「最小占領」「安全占領」「半分」「全軍」「終盤 all-in」など 5〜8 bucket に切り、最大でも各 source から数十候補に圧縮します。そこに RTS 文献の script portfolio の発想を入れ、**expand / defend / punish / comet / kill-shot** の数本の script を作って、root で組み合わせ最適化するのがよいです。探索は CMAB か簡易 PGS/NGS 風の greedy assignment が候補になります。citeturn31view2turn31view0turn31view1

Orbit Wars 固有に強いヒューリスティックは、次のようなものです。  
**静止惑星優先の開幕**は、公式 starter agent も取っているので最初の baseline として妥当です。  
**太陽接触を避ける tangent-like 発射**は、現時点の public notebook 名から見ても競争ポイントです。  
**軌道惑星への lead shot**は、発射時点ではなく到着時点の座標へ照準する必要があります。  
**彗星の出現前待機**は、turn 50/150/250/350/450 直前に前線艦を厚くしておく設計です。  
**reserve discipline** は極めて重要で、所有惑星から出す艦数に下限を設けないと、同時多面着弾で一気に崩れます。citeturn42view3turn38search0

さらに実践的なのは、**map characterization + opponent typing** を開幕で回すことです。Planet Wars 研究の map characterization を Orbit Wars 流に作り直し、「静止惑星密度」「可採彗星距離」「太陽分断の強さ」「ホーム周辺の軌道帯の近さ」などを特徴量化し、方針を切り替えます。相手も数十ターン観測すれば、「最近傍貪欲」「静止惑星偏重」「突撃型」「溜め型」「彗星偏重」ぐらいには分類できます。これに応じて、**こちらの reserve、迎撃角度、彗星への参加率**を変えるだけでも対人強度は上がります。citeturn47search18turn30view0

最後に、パラメータ最適化は手でやり切らない方がいいです。この手の bot は「1つ1つのルールは正しいが、閾値が悪くて弱い」ことが非常に多いので、Planet Wars 系で成功例のある進化的チューニングをそのまま載せるべきです。私は少なくとも、**self-play リーグ上で 50〜200 個程度の scalar weight を最適化**する段階を挟みます。評価ノイズがあるので、CMA-ES でも NTBEA 系でもよいですが、要するに「ルールを捨てる」のではなく、**ルールを探索可能なパラメトリック policy にする**のが大事です。citeturn15view1turn18search1turn18search11

## 強化学習案

強化学習で一番難しいのは、**可変長の action list と連続 angle** です。ここをそのまま連続制御にするより、まずは action abstraction を入れた方がよいです。実装の第一候補は、**autoregressive macro policy** です。1ターンで最大 M 個まで launch を生成し、各 step で `(source planet) -> (target candidate) -> (ship bucket)` を選び、最後に STOP を出す方式です。angle は target candidate から決めるか、target line に対する小さな offset として出します。Lux AI や AlphaStar のように、複数の下位選択の joint distribution を作る設計は、この種の action decomposition と相性が良いです。citeturn25view0turn33view0

学習スケジュールは、Lux AI Season 1 と microRTS の成功例をかなりそのまま踏襲できます。具体的には、最初は  
**中立占領**、**生産差**、**ホーム存続**、**安全な彗星確保**、**敵ホーム圧力**  
の shaped reward で立ち上げ、途中から win/loss に anneal します。相手は self-play だけでなく、**固定 checkpoint 群 + 強いルール bot 群**を混ぜます。teacher KL や policy distillation を使って strategic cycling を抑えるのも有効です。microRTS で示されたように、単なる自己対戦よりも、**既存強敵への fine-tuning** や **map-specific specialization** が効く可能性が高いです。citeturn25view0turn25view2turn34search19turn29search1

ネットワーク表現は、grid CNN より**entity-centric**に寄せる方が自然です。Orbit Wars の状態はグリッド画像というより、planet / fleet / comet の集合データだからです。私は各 entity に対して、所有者、座標、半径、艦数、生産、軌道半径、角速度、将来位置サマリ、ホーム距離、太陽回避可否などを埋め込み、そこに相対位置を使った attention か graph message passing を重ねる設計を推します。これは先行研究というより設計判断ですが、multi-agent で relational structure が強い環境に GNN/attention が合うという方向性自体は MARL 文献でも一貫しています。citeturn20view0turn20view1

RL をやるなら、**2人戦と4人戦は別問題として扱う**べきです。2人戦はほぼゼロ和で PSRO/league/self-play の世界に乗せやすい一方、4人戦は kingmaking と third-party collapse が入り、報酬も非ゼロ和的になります。さらに Orbit Wars は 4人戦スタート地点の公平性のために対角線対称 group を選ぶ実装になっており、2人戦と4人戦では幾何もゲーム理論も違います。単一 policy にまとめるより、**最低でも 2p と 4p を分け、可能なら phase も分ける**方が安定します。citeturn40view0turn6view1turn42view3

最後に、強化学習を本番で使うなら inference constraint を軽視できません。Lux AI Season 2 や microRTS の上位 RL は、単に強いだけではなく、**時間内に動くように backbone を削り、複数の specialized policy から選ぶ**方向へ進んでいました。Orbit Wars も 1 秒しかないので、重い policy をそのまま出すより、**強い teacher を作って、小さい student へ distill する**方が実戦的です。純粋 PPO 一発より、`heuristic -> imitation -> self-play RL -> distillation` の順が堅いです。citeturn29search1turn34search19

## 実装ロードマップと限界

実装優先順位は、私は次の順を勧めます。  
まず **exact simulator + local ladder** です。あなたの summary と公式実装を合わせれば recreate は十分可能で、ここがないと後の比較が全部曖昧になります。seed 固定の reproducible benchmark を作り、2人戦・4人戦・各 phase 用にテスト seed 群を分けるべきです。citeturn40view0turn41view0turn42view3

次に **強いルール bot** を作ります。最低限、静止惑星開幕、太陽回避、lead shot、defensive reserve、彗星スケジューリング、終盤首位維持ロジックまでは入れたいです。そのうえで script portfolio を作り、自己対戦リーグで閾値と重みを進化的に回します。ここまでできると、たぶん RL の初期教師として十分強いものになります。citeturn15view1turn47search18turn31view0

その後に **模倣学習** を載せます。自作 heuristic 同士の replay をまず集めて behavior cloning し、競技が進んで公開試合や公開 notebook 由来の強い動作が増えてきたら、そこから policy distillation をかけます。AlphaStar もまず replay imitation から入りましたし、Kaggle 系でも imitation を土台にする流れは何度も出ています。citeturn33view0turn21view0

最後に **自己対戦 RL で詰める**のがよいです。ここで重要なのは、直近自分だけとの self-play ではなく、固定 snapshot 群・ルール bot 群・aggressive explorer 群を混ぜた league にすることです。2人戦から始めて、4人戦は別トラックで学習した方が事故が少ないです。Orbit Wars のように幾何が強いゲームでは、純粋 learning-to-play より、**学習で heuristic の穴を埋める**という捉え方の方が成功しやすいと私は見ます。citeturn30view0turn33view0turn34search19
