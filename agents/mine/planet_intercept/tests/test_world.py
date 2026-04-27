from src.utils import Fleet, Planet
from src.world import (
    Arrival,
    apply_planned_arrival,
    build_arrival_ledger,
    first_turn_lost,
    resolve_battle,
    ships_needed_to_capture_at,
    simulate_planet_timeline,
)


def P(pid: int, owner: int, x: float, y: float, ships: int, prod: int = 1) -> Planet:
    return Planet(id=pid, owner=owner, x=x, y=y, radius=1.0, ships=ships, production=prod)


def F(fid: int, owner: int, x: float, y: float, angle: float, ships: int) -> Fleet:
    return Fleet(id=fid, owner=owner, x=x, y=y, angle=angle, from_planet_id=99, ships=ships)


class TestArrivalLedger:
    def test_fleet_hits_forward_planet(self):
        target = P(1, -1, 20, 0, ships=5)
        fleet = F(10, 0, 5, 0, angle=0.0, ships=10)

        ledger = build_arrival_ledger([target], [fleet], horizon=80)

        assert set(ledger) == {1}
        assert ledger[1][0].owner == 0
        assert ledger[1][0].ships == 10
        assert ledger[1][0].eta > 0

    def test_enemy_fleet_is_included(self):
        target = P(1, 0, 20, 0, ships=5)
        fleet = F(10, 1, 5, 0, angle=0.0, ships=10)

        ledger = build_arrival_ledger([target], [fleet], horizon=80)

        assert ledger[1][0].owner == 1

    def test_nearest_planet_on_line_is_used(self):
        near = P(1, -1, 20, 0, ships=5)
        far = P(2, -1, 40, 0, ships=5)
        fleet = F(10, 0, 5, 0, angle=0.0, ships=10)

        ledger = build_arrival_ledger([far, near], [fleet], horizon=80)

        assert set(ledger) == {1}

    def test_sun_crossing_fleet_is_excluded(self):
        target = P(1, -1, 60, 50, ships=5)
        fleet = F(10, 0, 40, 50, angle=0.0, ships=10)

        ledger = build_arrival_ledger([target], [fleet], horizon=80)

        assert ledger == {}

    def test_horizon_excludes_late_arrivals(self):
        target = P(1, -1, 90, 0, ships=5)
        fleet = F(10, 0, 0, 0, angle=0.0, ships=1)

        ledger = build_arrival_ledger([target], [fleet], horizon=10)

        assert ledger == {}


class TestTimeline:
    def test_owned_planet_produces_before_arrival(self):
        planet = P(1, 0, 0, 0, ships=10, prod=2)

        timeline = simulate_planet_timeline(planet, [], horizon=3)

        assert [s.ships for s in timeline] == [12, 14, 16]

    def test_neutral_planet_does_not_produce(self):
        planet = P(1, -1, 0, 0, ships=10, prod=5)

        timeline = simulate_planet_timeline(planet, [], horizon=3)

        assert [s.ships for s in timeline] == [10, 10, 10]

    def test_enemy_arrival_captures_planet(self):
        planet = P(1, 0, 0, 0, ships=10, prod=0)
        arrivals = [Arrival(eta=2, owner=1, ships=15)]

        timeline = simulate_planet_timeline(planet, arrivals, horizon=3)

        assert timeline[1].owner == 1
        assert timeline[1].ships == 5

    def test_same_turn_attackers_cancel_on_tie(self):
        owner, ships = resolve_battle(
            current_owner=-1,
            current_ships=10,
            arrivals=[
                Arrival(eta=1, owner=0, ships=20),
                Arrival(eta=1, owner=1, ships=20),
            ],
        )

        assert owner == -1
        assert ships == 10

    def test_same_owner_arrival_reinforces(self):
        planet = P(1, 0, 0, 0, ships=10, prod=0)
        arrivals = [Arrival(eta=1, owner=0, ships=7)]

        timeline = simulate_planet_timeline(planet, arrivals, horizon=1)

        assert timeline[0].owner == 0
        assert timeline[0].ships == 17

    def test_first_turn_lost(self):
        planet = P(1, 0, 0, 0, ships=10, prod=0)
        arrivals = [Arrival(eta=3, owner=1, ships=20)]
        timeline = simulate_planet_timeline(planet, arrivals, horizon=5)

        assert first_turn_lost(planet, timeline, player=0) == 3

    def test_ships_needed_to_capture_at(self):
        planet = P(1, 1, 0, 0, ships=10, prod=2)
        timeline = simulate_planet_timeline(planet, [], horizon=5)

        assert ships_needed_to_capture_at(planet, timeline, player=0, eta=5) == 21

    def test_ships_needed_zero_when_already_owned(self):
        planet = P(1, 0, 0, 0, ships=10, prod=2)
        timeline = simulate_planet_timeline(planet, [], horizon=5)

        assert ships_needed_to_capture_at(planet, timeline, player=0, eta=5) == 0


class TestApplyPlannedArrival:
    def test_adds_arrival_to_ledger(self):
        planet = P(1, -1, 20, 0, ships=5, prod=0)
        ledger: dict = {}
        timelines = {planet.id: simulate_planet_timeline(planet, [], horizon=10)}
        apply_planned_arrival(
            ledger, timelines, [planet],
            target_id=planet.id, owner=0, ships=8, eta=3, horizon=10,
        )
        assert planet.id in ledger
        assert len(ledger[planet.id]) == 1
        a = ledger[planet.id][0]
        assert a.eta == 3 and a.owner == 0 and a.ships == 8

    def test_timeline_reflects_new_arrival(self):
        # 自軍所有の惑星で敵 fleet に落ちる予定 -> 自軍 arrival を追加すれば救われる
        planet = P(1, 0, 50, 50, ships=5, prod=0)
        base_arrivals = [Arrival(eta=5, owner=1, ships=30)]
        base_timeline = simulate_planet_timeline(planet, base_arrivals, horizon=10)
        assert first_turn_lost(planet, base_timeline, player=0) == 5

        ledger = {planet.id: list(base_arrivals)}
        timelines = {planet.id: base_timeline}
        apply_planned_arrival(
            ledger, timelines, [planet],
            target_id=planet.id, owner=0, ships=40, eta=4, horizon=10,
        )
        # 自軍 40 が先着 -> fall しないはず
        assert first_turn_lost(planet, timelines[planet.id], player=0) is None

    def test_ignores_eta_beyond_horizon(self):
        planet = P(1, -1, 20, 0, ships=5, prod=0)
        ledger: dict = {}
        timelines = {planet.id: simulate_planet_timeline(planet, [], horizon=10)}
        snapshot_timeline = list(timelines[planet.id])
        apply_planned_arrival(
            ledger, timelines, [planet],
            target_id=planet.id, owner=0, ships=5, eta=15, horizon=10,
        )
        assert ledger == {}
        assert timelines[planet.id] == snapshot_timeline

    def test_multiple_arrivals_sorted_by_eta(self):
        planet = P(1, -1, 20, 0, ships=5, prod=0)
        ledger: dict = {}
        timelines = {planet.id: simulate_planet_timeline(planet, [], horizon=10)}
        for eta in (7, 3, 5):
            apply_planned_arrival(
                ledger, timelines, [planet],
                target_id=planet.id, owner=0, ships=2, eta=eta, horizon=10,
            )
        etas = [a.eta for a in ledger[planet.id]]
        assert etas == sorted(etas)
