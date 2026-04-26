import math
from typing import NamedTuple

CENTER = 50.0
SUN_RADIUS = 10.0
BOARD_SIZE = 100.0


class Planet(NamedTuple):
    id: int
    owner: int
    x: float
    y: float
    radius: float
    ships: int
    production: int


class Fleet(NamedTuple):
    id: int
    owner: int
    x: float
    y: float
    angle: float
    from_planet_id: int
    ships: int


def parse_obs(obs):
    if isinstance(obs, dict):
        raw_planets = obs.get("planets", [])
        raw_fleets = obs.get("fleets", [])
        player = obs.get("player", 0)
        angular_velocity = obs.get("angular_velocity", 0.0)
        step = obs.get("step", 0)
    else:
        raw_planets = obs.planets
        raw_fleets = obs.fleets
        player = obs.player
        angular_velocity = getattr(obs, "angular_velocity", 0.0)
        step = getattr(obs, "step", 0)
    planets = [Planet(*p) for p in raw_planets]
    fleets = [Fleet(*f) for f in raw_fleets]
    remaining_turns = 500 - step
    return player, planets, fleets, angular_velocity, remaining_turns


def angle_to(src: Planet, dst: Planet) -> float:
    return math.atan2(dst.y - src.y, dst.x - src.x)


def distance(a: Planet, b: Planet) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def fleet_speed(ships: int, max_speed: float = 6.0) -> float:
    if ships <= 1:
        return 1.0
    return 1.0 + (max_speed - 1.0) * (math.log(ships) / math.log(1000)) ** 1.5


def eta(src: Planet, dst: Planet, ships: int) -> float:
    """フリートがdstに到着するまでのターン数を返す (dst が静止惑星前提)"""
    dist = distance(src, dst)
    speed = fleet_speed(ships)
    return dist / speed


def predict_planet_pos(planet: Planet, initial_planet: Planet, angular_velocity: float, turns: int):
    """軌道惑星の turns ターン後の (x, y) を返す"""
    dx = initial_planet.x - CENTER
    dy = initial_planet.y - CENTER
    r = math.hypot(dx, dy)
    base_angle = math.atan2(dy, dx)
    new_angle = base_angle + angular_velocity * turns
    return CENTER + r * math.cos(new_angle), CENTER + r * math.sin(new_angle)
