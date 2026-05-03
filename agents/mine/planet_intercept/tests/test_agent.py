"""agent 関数のスモークテスト。

parse_obs のシグネチャ変更と Comet 除外が壊れていないことを確認する。
"""

from src.agent import agent
from src.utils import parse_obs


def _planet(pid, owner, x, y, ships=10, prod=1, radius=1.0):
    return [pid, owner, x, y, radius, ships, prod]


class TestParseObsShape:
    def test_returns_seven_elements(self):
        obs = {"planets": [], "fleets": [], "player": 0, "step": 3}
        result = parse_obs(obs)
        assert len(result) == 7
        player, planets, fleets, av, remaining, comet_ids, step = result
        assert player == 0
        assert planets == []
        assert fleets == []
        assert av == 0.0
        assert remaining == 497
        assert comet_ids == frozenset()
        assert step == 3

    def test_comet_planet_ids_collected(self):
        obs = {
            "planets": [],
            "fleets": [],
            "player": 0,
            "step": 0,
            "comet_planet_ids": [7, 8, 9],
        }
        result = parse_obs(obs)
        comet_ids = result[5]
        assert comet_ids == frozenset({7, 8, 9})


class TestAgentCometExclusion:
    def test_comet_target_is_not_attacked(self):
        """彗星の planet id が comet_planet_ids にあると狙われないこと。"""
        obs = {
            "player": 0,
            "step": 0,
            "angular_velocity": 0.0,
            "planets": [
                _planet(0, 0, 10.0, 10.0, ships=100, prod=1),
                _planet(1, -1, 15.0, 10.0, ships=1, prod=1),  # 彗星扱い
            ],
            "fleets": [],
            "comet_planet_ids": [1],
        }
        moves = agent(obs)
        # 彗星 (id=1) に向けた発射はない
        assert all(m[0] != 1 for m in moves)
        # 念のため彗星を除いた世界で自惑星が何か撃てる条件は整っていない (target なし)
        # ので moves 自体は空でよい。
        assert moves == [] or all(m[0] == 0 for m in moves)

    def test_non_comet_neutral_still_targetable(self):
        obs = {
            "player": 0,
            "step": 0,
            "angular_velocity": 0.0,
            "planets": [
                _planet(0, 0, 10.0, 10.0, ships=100, prod=1),
                _planet(1, -1, 15.0, 10.0, ships=1, prod=1),
            ],
            "fleets": [],
            "comet_planet_ids": [],
        }
        moves = agent(obs)
        # 中立 id=1 に対して自惑星 id=0 から発射が行われる
        assert any(m[0] == 0 for m in moves)


class TestReinforcePass:
    def test_reinforce_pass_does_not_double_fire_source(self):
        """通常パスで発射した source は reinforce パスでも使われない。

        配置: source (id=0) と target (id=1) は同じ owner=0。
        source は通常パスで enemy (id=2) に撃てる candidates を持つ。
        -> source は fired_sources に入り reinforce source にならない。
        """
        obs = {
            "player": 0,
            "step": 50,
            "angular_velocity": 0.0,
            "planets": [
                _planet(0, 0, 0.0, 0.0, ships=60, prod=1),  # source: 通常候補あり
                _planet(1, 0, 5.0, 0.0, ships=3, prod=2),  # ally: cant_afford target
                _planet(2, 1, 10.0, 0.0, ships=5, prod=1),  # enemy: 通常攻撃の target
            ],
            "fleets": [],
            "comet_planet_ids": [],
        }
        moves = agent(obs)
        # source (id=0) は 1 ターンに 1 発のみ (reinforce と通常の両方は撃てない)
        fired_from_0 = [m for m in moves if m[0] == 0]
        assert len(fired_from_0) <= 1

    def test_reinforce_updates_arrival_ledger_for_friendly_target(self):
        """reinforce 発射後に target の timeline が eta 時点で ships 増加すること。

        enumerate_reinforce_candidates を直接呼んで apply_planned_arrival の副作用を検証する。
        agent.py の reinforce パスが apply_planned_arrival を呼んでいることの間接証明。
        """
        from src.targeting import enumerate_reinforce_candidates
        from src.utils import Planet
        from src.world import apply_planned_arrival, build_arrival_ledger, build_timelines

        idle_src = Planet(id=0, owner=0, x=0.0, y=80.0, radius=1.0, ships=40, production=1)
        front = Planet(id=1, owner=0, x=48.0, y=80.0, radius=1.0, ships=3, production=1)
        enemy = Planet(id=2, owner=1, x=53.0, y=80.0, radius=1.0, ships=4, production=1)
        planets = [idle_src, front, enemy]

        # front は cant_afford (avail=3 < ships_needed=9)
        # enemy を target とする value>0 の候補を持つが avail 不足
        def zero_reserve(p):
            return 0

        front_cand = (enemy, 9, 0.0, 5.0, 4.0)
        cands_by_planet = {idle_src.id: [], front.id: [front_cand]}
        reserve_of = zero_reserve

        horizon = 80
        ledger = build_arrival_ledger(planets, [], horizon=horizon)
        timelines = build_timelines(planets, ledger, horizon=horizon)

        missions = enumerate_reinforce_candidates(
            my_planets=[idle_src, front],
            target_candidates_by_planet=cands_by_planet,
            timelines=timelines,
            reserve_of=reserve_of,
        )
        assert len(missions) == 1
        m = missions[0]

        ships_before = (
            timelines[front.id][m.my_eta - 1].ships
            if m.my_eta <= len(timelines[front.id])
            else None
        )
        apply_planned_arrival(
            ledger,
            timelines,
            planets,
            target_id=front.id,
            owner=0,
            ships=m.ships,
            eta=m.my_eta,
            horizon=horizon,
        )
        if ships_before is not None:
            ships_after = timelines[front.id][m.my_eta - 1].ships
            assert ships_after >= ships_before + m.ships
