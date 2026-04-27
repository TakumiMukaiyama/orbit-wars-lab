"""Future arrival ledger and per-planet timeline simulation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math

from .geometry import segment_hits_sun
from .utils import Fleet, Planet, fleet_speed

NEUTRAL_OWNER = -1


@dataclass(frozen=True)
class Arrival:
    eta: int
    owner: int
    ships: int


@dataclass(frozen=True)
class PlanetState:
    turn: int
    owner: int
    ships: int


def _fleet_forward_distance(fleet: Fleet, planet: Planet) -> float:
    dx = planet.x - fleet.x
    dy = planet.y - fleet.y
    return math.cos(fleet.angle) * dx + math.sin(fleet.angle) * dy


def _fleet_perpendicular_distance(fleet: Fleet, planet: Planet) -> float:
    dx = planet.x - fleet.x
    dy = planet.y - fleet.y
    return abs(-math.sin(fleet.angle) * dx + math.cos(fleet.angle) * dy)


def _fleet_can_hit_planet(
    fleet: Fleet,
    planet: Planet,
    horizon: int,
    perp_margin: float = 0.5,
) -> tuple[int, float] | None:
    forward = _fleet_forward_distance(fleet, planet)
    if forward <= 0:
        return None

    perp = _fleet_perpendicular_distance(fleet, planet)
    if perp > planet.radius + perp_margin:
        return None

    if segment_hits_sun(fleet.x, fleet.y, planet.x, planet.y):
        return None

    eta = math.ceil(forward / fleet_speed(fleet.ships))
    if eta < 1 or eta > horizon:
        return None

    return eta, forward


def build_arrival_ledger(
    planets: list[Planet],
    fleets: list[Fleet],
    horizon: int = 80,
) -> dict[int, list[Arrival]]:
    """Map planet id to already in-flight fleets likely to hit it within horizon."""
    ledger: defaultdict[int, list[Arrival]] = defaultdict(list)

    for fleet in fleets:
        hits: list[tuple[float, int, Planet]] = []
        for planet in planets:
            result = _fleet_can_hit_planet(fleet, planet, horizon)
            if result is None:
                continue
            eta, forward = result
            hits.append((forward, eta, planet))

        if not hits:
            continue

        _, eta, target = min(hits, key=lambda item: item[0])
        ledger[target.id].append(Arrival(eta=eta, owner=fleet.owner, ships=int(fleet.ships)))

    return {pid: sorted(arrivals, key=lambda a: a.eta) for pid, arrivals in ledger.items()}


def resolve_battle(
    current_owner: int,
    current_ships: int,
    arrivals: list[Arrival],
) -> tuple[int, int]:
    """Resolve same-turn arrivals against the current planet state."""
    by_owner: defaultdict[int, int] = defaultdict(int)
    for arrival in arrivals:
        if arrival.ships > 0:
            by_owner[arrival.owner] += int(arrival.ships)

    if not by_owner:
        return current_owner, current_ships

    ranked = sorted(by_owner.items(), key=lambda item: item[1], reverse=True)
    attacker_owner, attacker_ships = ranked[0]

    if len(ranked) > 1:
        second_ships = ranked[1][1]
        if attacker_ships == second_ships:
            return current_owner, current_ships
        attacker_ships -= second_ships

    if attacker_owner == current_owner:
        return current_owner, current_ships + attacker_ships

    if attacker_ships > current_ships:
        return attacker_owner, attacker_ships - current_ships

    return current_owner, current_ships - attacker_ships


def simulate_planet_timeline(
    planet: Planet,
    arrivals: list[Arrival],
    horizon: int = 80,
) -> list[PlanetState]:
    """Simulate owner and ship count for one planet over future turns."""
    arrivals_by_turn: defaultdict[int, list[Arrival]] = defaultdict(list)
    for arrival in arrivals:
        if 1 <= arrival.eta <= horizon:
            arrivals_by_turn[arrival.eta].append(arrival)

    owner = int(planet.owner)
    ships = int(planet.ships)
    timeline: list[PlanetState] = []

    for turn in range(1, horizon + 1):
        if owner != NEUTRAL_OWNER:
            ships += int(planet.production)

        if turn in arrivals_by_turn:
            owner, ships = resolve_battle(owner, ships, arrivals_by_turn[turn])

        timeline.append(PlanetState(turn=turn, owner=owner, ships=ships))

    return timeline


def state_at(timeline: list[PlanetState], turn: int) -> PlanetState | None:
    if not timeline:
        return None
    idx = max(0, min(len(timeline) - 1, int(math.ceil(turn)) - 1))
    return timeline[idx]


def first_turn_lost(
    planet: Planet,
    timeline: list[PlanetState],
    player: int,
) -> int | None:
    if planet.owner != player:
        return None
    for state in timeline:
        if state.owner != player:
            return state.turn
    return None


def ships_needed_to_capture_at(
    planet: Planet,
    timeline: list[PlanetState],
    player: int,
    eta: int,
) -> int:
    state = state_at(timeline, eta)
    if state is None:
        return max(0, int(planet.ships) + 1)
    if state.owner == player:
        return 0
    return max(0, int(state.ships) + 1)


def build_timelines(
    planets: list[Planet],
    ledger: dict[int, list[Arrival]],
    horizon: int = 80,
) -> dict[int, list[PlanetState]]:
    return {
        planet.id: simulate_planet_timeline(planet, ledger.get(planet.id, []), horizon)
        for planet in planets
    }
