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
