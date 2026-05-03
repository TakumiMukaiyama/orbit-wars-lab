import math
import pytest
from src.state import GameState, build_game_state


def _make_obs(step=10, remaining_turns=490):
    return {
        "player": 0,
        "planets": [
            [0, 0, 20.0, 20.0, 1.0, 30, 2],   # mine
            [1, -1, 70.0, 70.0, 1.0, 10, 1],   # neutral
            [2, 1, 80.0, 80.0, 1.0, 20, 3],    # enemy
        ],
        "fleets": [],
        "angular_velocity": 0.0,
        "step": step,
        "comet_planet_ids": [],
    }


def test_build_game_state_basic():
    obs = _make_obs()
    gs = build_game_state(obs)
    assert gs.player == 0
    assert gs.remaining_turns == 490
    assert gs.step == 10
    assert len(gs.my_planets) == 1
    assert gs.my_planets[0].id == 0


def test_build_game_state_mode_neutral():
    obs = _make_obs()
    gs = build_game_state(obs)
    # my_total=30, enemy_total=20 -> dom=(30-20)/(30+20)=0.2 -> neutral
    assert gs.mode == "neutral"
    assert math.isclose(gs.domination, 0.2)


def test_build_game_state_mode_ahead():
    obs = _make_obs()
    obs["planets"][0][5] = 200  # mine.ships=200
    gs = build_game_state(obs)
    assert gs.mode == "ahead"


def test_build_game_state_mode_behind():
    obs = _make_obs()
    obs["planets"][2][5] = 200  # enemy.ships=200
    gs = build_game_state(obs)
    assert gs.mode == "behind"


def test_build_game_state_timelines_exist():
    obs = _make_obs()
    gs = build_game_state(obs)
    for p in gs.planets:
        assert p.id in gs.timelines


def test_build_game_state_defense_status_keys():
    obs = _make_obs()
    gs = build_game_state(obs)
    for p in gs.my_planets:
        assert p.id in gs.defense_status
        status, reserve = gs.defense_status[p.id]
        assert status in ("safe", "threatened", "doomed")
        assert reserve >= 0


def test_build_game_state_is_opening():
    obs_early = _make_obs(step=5, remaining_turns=495)
    obs_late = _make_obs(step=100, remaining_turns=400)
    assert build_game_state(obs_early).is_opening is True
    assert build_game_state(obs_late).is_opening is False
