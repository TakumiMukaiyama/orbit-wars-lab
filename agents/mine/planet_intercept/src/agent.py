"""Phase 1c エージェント: HeuristicPolicy + ReplayLogger ラッパー。"""

from .policy import HeuristicPolicy, ReplayLogger
from .state import build_game_state

_policy = HeuristicPolicy()
_logger = ReplayLogger()


def agent(obs):
    gs = build_game_state(obs)
    moves = _policy.act(gs)
    if _logger.is_enabled():
        _logger.log_turn(gs, _policy.last_candidates_by_source, _policy.last_chosen)
    return moves
