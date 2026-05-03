import json
import math
import os
import tempfile

import pytest

from src.action_space import Candidate
from src.policy import HeuristicPolicy, ReplayLogger
from src.state import build_game_state


def _make_obs(step=50):
    return {
        "player": 0,
        "planets": [
            [0, 0,  20.0, 20.0, 1.0, 50, 2],
            [1, -1, 70.0, 70.0, 1.0, 10, 1],
            [2, 1,  80.0, 80.0, 1.0, 20, 3],
        ],
        "fleets": [],
        "angular_velocity": 0.0,
        "step": step,
        "comet_planet_ids": [],
    }


def test_heuristic_policy_returns_list():
    obs = _make_obs()
    gs = build_game_state(obs)
    policy = HeuristicPolicy()
    moves = policy.act(gs)
    assert isinstance(moves, list)


def test_heuristic_policy_move_format():
    obs = _make_obs()
    gs = build_game_state(obs)
    moves = HeuristicPolicy().act(gs)
    for m in moves:
        assert len(m) == 3
        planet_id, angle, ships = m
        assert isinstance(planet_id, int)
        assert isinstance(angle, float)
        assert isinstance(ships, int)
        assert ships > 0


def test_heuristic_policy_matches_original_agent():
    """HeuristicPolicy.act が旧 agent(obs) と同一 moves を返すこと。"""
    from src.agent import agent as original_agent
    obs = _make_obs()
    expected = original_agent(obs)
    gs = build_game_state(obs)
    got = HeuristicPolicy().act(gs)
    assert got == expected


def test_heuristic_policy_no_planets():
    obs = _make_obs()
    obs["planets"] = [
        [1, -1, 70.0, 70.0, 1.0, 10, 1],
    ]
    gs = build_game_state(obs)
    moves = HeuristicPolicy().act(gs)
    assert moves == []


def test_replay_logger_disabled_by_default(tmp_path):
    obs = _make_obs()
    gs = build_game_state(obs)
    logger = ReplayLogger()
    # 環境変数未設定なら no-op
    assert not logger.is_enabled()


def test_replay_logger_writes_jsonl(tmp_path, monkeypatch):
    log_path = tmp_path / "replay.jsonl"
    monkeypatch.setenv("ORBIT_WARS_REPLAY_LOG", str(log_path))

    obs = _make_obs()
    gs = build_game_state(obs)
    policy = HeuristicPolicy()
    logger = ReplayLogger()

    assert logger.is_enabled()

    candidates_by_source = policy.last_candidates_by_source
    chosen = policy.last_chosen
    logger.log_turn(gs, candidates_by_source, chosen)

    lines = log_path.read_text().strip().split("\n")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["step"] == gs.step
    assert record["player"] == gs.player
    assert "global_features" in record
    assert "sources" in record


def test_replay_logger_chosen_idx_is_correct(tmp_path, monkeypatch):
    log_path = tmp_path / "replay.jsonl"
    monkeypatch.setenv("ORBIT_WARS_REPLAY_LOG", str(log_path))

    obs = _make_obs()
    gs = build_game_state(obs)
    policy = HeuristicPolicy()
    policy.act(gs)

    logger = ReplayLogger()
    logger.log_turn(gs, policy.last_candidates_by_source, policy.last_chosen)

    record = json.loads(log_path.read_text().strip())
    for src_record in record["sources"]:
        if src_record["chosen_target_id"] is not None:
            assert src_record["chosen_idx"] is not None
            assert 0 <= src_record["chosen_idx"] < len(src_record["candidates"])
