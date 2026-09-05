"""Tests for the mesh routing model.

This is the project's differentiating claim, so it gets tested as a claim: the
mesh must measurably beat a star under realistic propagation, and it must survive
losing a relay. "It's a mesh" is a slogan; these are the numbers behind it.
"""

from __future__ import annotations

import numpy as np
import pytest

from simulator.field import SITE_PRESETS, build_grid_field
from simulator.mesh import GATEWAY_ADDR, MeshNetwork, Obstruction, RadioModel

PRESET = SITE_PRESETS["jharia"]
GATEWAY_XY = (PRESET.panel.x_start - 0.5 * PRESET.panel.radius_of_influence_m, 0.0)
OBSTRUCTIONS = [
    Obstruction(280, -60, 90, 18.0, "overburden dump"),
    Obstruction(430, 90, 70, 14.0, "tree belt"),
]


@pytest.fixture(scope="module")
def nodes():
    return build_grid_field(PRESET, cols=5, rows=3,
                            max_spacing_m=RadioModel().max_reliable_spacing_m())


@pytest.fixture
def net(nodes):
    return MeshNetwork(nodes, GATEWAY_XY, seed=3, obstructions=OBSTRUCTIONS)


class TestObstruction:
    def test_segment_through_the_centre_is_blocked(self):
        o = Obstruction(100, 0, 20, 15.0)
        assert o.blocks(0, 0, 200, 0)

    def test_segment_passing_clear_is_not_blocked(self):
        o = Obstruction(100, 100, 20, 15.0)
        assert not o.blocks(0, 0, 200, 0)

    def test_obstruction_beyond_the_segment_end_is_not_blocked(self):
        """Clamping to the segment matters: an infinite line would false-positive."""
        o = Obstruction(300, 0, 20, 15.0)
        assert not o.blocks(0, 0, 100, 0)

    def test_degenerate_zero_length_segment(self):
        o = Obstruction(0, 0, 10, 15.0)
        assert o.blocks(5, 0, 5, 0)
        assert not o.blocks(50, 0, 50, 0)


class TestRadioModel:
    def test_rssi_falls_with_distance(self):
        r = RadioModel(shadowing_sigma_db=0.0)
        rng = np.random.default_rng(0)
        assert r.rssi(10, rng) > r.rssi(100, rng) > r.rssi(1000, rng)

    def test_obstruction_costs_exactly_its_attenuation(self):
        r = RadioModel(shadowing_sigma_db=0.0)
        clear = r.rssi(100, np.random.default_rng(1))
        blocked = r.rssi(100, np.random.default_rng(1), obstruction_db=18.0)
        assert clear - blocked == pytest.approx(18.0)

    def test_delivery_probability_is_monotonic_and_bounded(self):
        r = RadioModel()
        probs = [r.delivery_probability(x) for x in (-140, -125, -115, -100, -60)]
        assert all(b >= a for a, b in zip(probs, probs[1:]))
        assert 0.0 <= probs[0] < 0.1 and probs[-1] > 0.99

    def test_spacing_budget_shrinks_behind_an_obstruction(self):
        r = RadioModel()
        assert r.max_reliable_spacing_m(obstruction_db=18) < r.max_reliable_spacing_m()

    def test_spacing_budget_shrinks_in_harsher_terrain(self):
        clear = RadioModel(path_loss_exponent=2.2).max_reliable_spacing_m()
        rough = RadioModel(path_loss_exponent=3.4).max_reliable_spacing_m()
        assert rough < clear

    def test_shadowing_allowance_is_conservative(self):
        """Designing to the median link loses half the field on a bad day."""
        r = RadioModel()
        assert r.max_reliable_spacing_m(shadowing_sigmas=2.0) < \
               r.max_reliable_spacing_m(shadowing_sigmas=0.0)


class TestLayoutRespectsLinkBudget:
    def test_spacing_constraint_adds_infill_nodes(self):
        sparse = build_grid_field(PRESET, 5, 3)
        dense = build_grid_field(PRESET, 5, 3, max_spacing_m=150.0)
        assert len(dense) > len(sparse)

    def test_no_gap_exceeds_the_budget(self):
        spacing = 150.0
        nodes = build_grid_field(PRESET, 5, 3, max_spacing_m=spacing)
        xs = sorted({n.x_m for n in nodes})
        ys = sorted({n.y_m for n in nodes})
        assert max(b - a for a, b in zip(xs, xs[1:])) <= spacing + 1e-9
        assert max(b - a for a, b in zip(ys, ys[1:])) <= spacing + 1e-9

    def test_edge_anchors_survive_infill(self):
        """Infill must not displace the high-signal edge positions."""
        nodes = build_grid_field(PRESET, 5, 3, max_spacing_m=120.0)
        xs = {round(n.x_m, 6) for n in nodes}
        assert round(PRESET.panel.x_start, 6) in xs
        assert round(PRESET.panel.x_end, 6) in xs

    def test_rejects_nonsense_spacing(self):
        with pytest.raises(ValueError, match="must be positive"):
            build_grid_field(PRESET, 5, 3, max_spacing_m=0)


class TestRouting:
    def test_every_node_reaches_the_gateway(self, net):
        assert min(net.reachability(40).values()) > 0.9

    def test_mesh_decisively_beats_a_star(self, net):
        """The differentiating claim, as a measurement.

        With ground-level propagation and terrain in the way, direct-to-gateway
        links simply do not close for much of the field. Relaying is not a nicety
        here -- it is the difference between a monitored panel and a blind one.
        """
        star = np.mean(list(net.direct_reachability(40).values()))
        mesh = np.mean(list(net.reachability(40).values()))
        assert star < 0.75
        assert mesh > 0.95
        assert mesh > star + 0.25

    def test_distant_nodes_need_more_hops(self, net, nodes):
        near = min(nodes, key=lambda n: n.x_m)
        far = max(nodes, key=lambda n: n.x_m)
        near_hops = np.mean([r.hops for _ in range(30)
                             if (r := net.deliver(near.addr)).delivered])
        far_hops = np.mean([r.hops for _ in range(30)
                            if (r := net.deliver(far.addr)).delivered])
        assert far_hops > near_hops

    def test_ttl_bounds_the_path_length(self, net, nodes):
        far = max(nodes, key=lambda n: n.x_m)
        for _ in range(40):
            r = net.deliver(far.addr, ttl=3)
            if r.delivered:
                assert r.hops <= 3

    def test_path_starts_at_source_and_ends_at_gateway(self, net, nodes):
        far = max(nodes, key=lambda n: n.x_m)
        for _ in range(30):
            r = net.deliver(far.addr)
            if r.delivered:
                assert r.path[0] == far.addr
                assert r.path[-1] == GATEWAY_ADDR
                assert len(r.path) == r.hops + 1
                break
        else:
            pytest.fail("no frame from the far node was ever delivered")

    def test_a_dead_node_sends_nothing(self, net, nodes):
        addr = nodes[-1].addr
        net.set_down(addr)
        assert not net.deliver(addr).delivered
        assert net.reachability(10)[addr] == 0.0

    def test_gateway_cannot_be_taken_down(self, net):
        with pytest.raises(ValueError, match="gateway cannot be taken down"):
            net.set_down(GATEWAY_ADDR)


class TestSelfHealing:
    def test_field_survives_losing_its_busiest_relay(self, net, nodes):
        """The live demo, as a test: pull power on the hardest-working relay and
        the field must stay connected by routing around it."""
        traffic: dict[int, int] = {}
        for n in nodes:
            for _ in range(15):
                r = net.deliver(n.addr)
                for hop in r.path[1:-1]:
                    traffic[hop] = traffic.get(hop, 0) + 1
        if not traffic:
            pytest.skip("no relaying occurred in this topology")

        busiest = max(traffic, key=traffic.get)
        before = np.mean([v for a, v in net.reachability(30).items() if a != busiest])
        net.set_down(busiest)
        after = np.mean([v for a, v in net.reachability(30).items() if a != busiest])
        assert after > 0.85, f"field fell apart after losing relay 0x{busiest:04X}"
        assert after > before - 0.15

    def test_recovery_when_the_node_comes_back(self, net, nodes):
        addr = nodes[len(nodes) // 2].addr
        net.set_down(addr)
        assert net.reachability(10)[addr] == 0.0
        net.set_up(addr)
        assert net.reachability(20)[addr] > 0.8

    def test_neighbour_table_hides_dead_nodes(self, net, nodes):
        victim = nodes[0].addr
        neighbour = nodes[1].addr
        assert any(lk.dst == victim for lk in net.neighbors(neighbour))
        net.set_down(victim)
        assert not any(lk.dst == victim for lk in net.neighbors(neighbour))

    def test_neighbour_table_is_capped_and_ordered(self, net, nodes):
        table = net.neighbor_table(nodes[len(nodes) // 2].addr, limit=8)
        assert len(table) <= 8
        assert table == sorted(table, key=lambda lk: lk.rssi_dbm, reverse=True)


class TestAirtimeCost:
    def test_flooding_costs_more_transmissions_than_one_hop(self, net, nodes):
        """The mesh is not free -- redundant relaying is the price of robustness,
        and it belongs in the power budget honestly."""
        far = max(nodes, key=lambda n: n.x_m)
        costs = [net.deliver(far.addr).transmissions for _ in range(20)]
        assert np.mean(costs) > 1.0
