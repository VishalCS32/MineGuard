"""Software model of the LoRa surface mesh.

The E220-900M22S is a point-to-multipoint transceiver with no routing of its own,
so the mesh -- the part of this project that is actually novel -- is a protocol we
implement on the ESP32. This module is that protocol, written first in Python so
the routing behaviour can be designed, tested and demonstrated before a single
node is flashed. The firmware in ``firmware/node`` implements the same algorithm
against the same frame format.

Routing: controlled flooding with de-duplication
------------------------------------------------
Every node rebroadcasts a frame it has not seen before, decrementing TTL, and
suppresses a rebroadcast if it already heard the same ``(src, seq)`` relayed by a
neighbour with a stronger link. That gives:

  * no routing tables and no convergence delay -- a new node participates instantly
  * automatic self-healing -- if a relay dies, surviving neighbours still carry the
    flood, and the only visible effect is a change in hop count
  * bounded cost -- TTL caps the broadcast storm, and RSSI suppression stops every
    node shouting the same frame

The trade is redundant airtime, which is affordable at one frame per node per
minute and is what buys robustness on a surface where nodes get buried, stolen,
run over, or simply run flat.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .field import NodeSpec

__all__ = ["RadioModel", "MeshNetwork", "DeliveryResult", "Link", "Obstruction"]

GATEWAY_ADDR = 0x0001


@dataclass(frozen=True, slots=True)
class Obstruction:
    """Terrain that attenuates any link crossing it.

    Coalfield surface is not an empty plane: spoil heaps, overburden dumps, tree
    belts and village structures sit between nodes. These are what force multi-hop
    routing, so they are modelled explicitly rather than buried in a fudge factor.
    """

    x_m: float
    y_m: float
    radius_m: float
    attenuation_db: float
    label: str = "spoil heap"

    def blocks(self, ax: float, ay: float, bx: float, by: float) -> bool:
        """Does the segment a->b pass through this obstruction?"""
        dx, dy = bx - ax, by - ay
        seg_len_sq = dx * dx + dy * dy
        if seg_len_sq == 0:
            return math.hypot(ax - self.x_m, ay - self.y_m) <= self.radius_m
        # Closest approach of the circle centre to the segment.
        t = ((self.x_m - ax) * dx + (self.y_m - ay) * dy) / seg_len_sq
        t = max(0.0, min(1.0, t))
        cx, cy = ax + t * dx, ay + t * dy
        return math.hypot(cx - self.x_m, cy - self.y_m) <= self.radius_m


@dataclass(frozen=True, slots=True)
class RadioModel:
    """LoRa link budget for the E220-900M22S in the Indian 865-867 MHz ISM band.

    Calibrated for *ground-level* nodes, which is the deployment that matters here
    and is far harsher than the open line-of-sight figures LoRa is usually quoted
    with. A node sits on a short post over rough, vegetated, undulating ground, so
    its first Fresnel zone is substantially obstructed and the effective path-loss
    exponent lands around 3.4 rather than the ~2.0-2.7 of an elevated link.

    This matters to the design: with an optimistic exponent every node reaches the
    gateway directly and the mesh is decoration. Under realistic ground-level
    propagation it is what keeps the far half of the field connected -- and it also
    says something practical for deployment, namely that antenna height buys more
    range than transmit power does.
    """

    tx_power_dbm: float = 22.0
    sensitivity_dbm: float = -123.0     # ~SF9, 125 kHz
    path_loss_exponent: float = 3.4     # ground-level over rough vegetated terrain
    reference_loss_db: float = 43.0     # at 1 m, 868 MHz
    shadowing_sigma_db: float = 4.5     # terrain variability
    # Link margin above sensitivity at which delivery becomes reliable.
    reliable_margin_db: float = 12.0

    def rssi(self, distance_m: float, rng: np.random.Generator,
             obstruction_db: float = 0.0) -> float:
        d = max(1.0, distance_m)
        loss = self.reference_loss_db + 10 * self.path_loss_exponent * math.log10(d)
        return self.tx_power_dbm - loss - obstruction_db + rng.normal(
            0, self.shadowing_sigma_db)

    def max_reliable_spacing_m(self, shadowing_sigmas: float = 2.0,
                               obstruction_db: float = 0.0) -> float:
        """Largest node spacing that still yields a reliable link.

        A deployment-planning tool, not a curiosity: node spacing has to satisfy
        *two* independent constraints, and they pull in opposite directions.
        Sensing wants nodes concentrated where tilt and strain peak; connectivity
        wants them close enough to hear each other. Spacing chosen for coverage
        alone produces a field that measures beautifully and cannot get a single
        frame home.

        The margin deliberately allows for shadowing running against us -- design
        to the median link and half the field drops out on a bad day.
        """
        budget = (self.tx_power_dbm - self.reference_loss_db
                  - (self.sensitivity_dbm + self.reliable_margin_db)
                  - shadowing_sigmas * self.shadowing_sigma_db
                  - obstruction_db)
        return float(10 ** (budget / (10 * self.path_loss_exponent)))

    def delivery_probability(self, rssi_dbm: float) -> float:
        """Packet delivery ratio as a function of link margin.

        Modelled as a logistic curve over the margin above sensitivity: LoRa holds
        near-perfect delivery until it falls off a cliff within a few dB of its
        limit, which is exactly the behaviour that makes a mesh worth having.
        """
        margin = rssi_dbm - self.sensitivity_dbm
        return float(1.0 / (1.0 + math.exp(-(margin - self.reliable_margin_db) / 2.5)))


@dataclass(slots=True)
class Link:
    """A directed radio link between two mesh members."""

    src: int
    dst: int
    distance_m: float
    rssi_dbm: float
    pdr: float

    @property
    def snr_db(self) -> float:
        return float(np.clip(14.0 + (self.rssi_dbm + 100) * 0.25, -18, 30))


@dataclass(slots=True)
class DeliveryResult:
    """Outcome of one frame's journey to the gateway."""

    delivered: bool
    hops: int = 0
    path: list[int] = field(default_factory=list)
    rssi_at_gateway: int = 0
    snr_at_gateway: float = 0.0
    transmissions: int = 0        # total airtime cost, including redundant relays


class MeshNetwork:
    """The surface mesh: who can hear whom, and how frames actually get home."""

    def __init__(self, nodes: list[NodeSpec], gateway_xy: tuple[float, float],
                 radio: RadioModel | None = None, seed: int = 0,
                 default_ttl: int = 4, obstructions: list[Obstruction] | None = None):
        self.nodes = {n.addr: n for n in nodes}
        self.gateway_xy = gateway_xy
        self.radio = radio if radio is not None else RadioModel()
        self.rng = np.random.default_rng(seed)
        self.default_ttl = default_ttl
        self.obstructions = obstructions or []
        self.down: set[int] = set()
        self._positions: dict[int, tuple[float, float]] = {
            n.addr: (n.x_m, n.y_m) for n in nodes}
        self._positions[GATEWAY_ADDR] = gateway_xy
        self._links: dict[tuple[int, int], Link] = {}
        self._build_links()

    # ------------------------------------------------------------- topology
    def _build_links(self) -> None:
        """Link budget for every pair, once. Shadowing is fixed per link because
        terrain does not re-roll itself between packets."""
        addrs = list(self._positions)
        for i, a in enumerate(addrs):
            for b in addrs[i + 1:]:
                (ax, ay), (bx, by) = self._positions[a], self._positions[b]
                d = math.hypot(ax - bx, ay - by)
                blocked_db = sum(o.attenuation_db for o in self.obstructions
                                 if o.blocks(ax, ay, bx, by))
                rssi = self.radio.rssi(d, self.rng, obstruction_db=blocked_db)
                if rssi < self.radio.sensitivity_dbm:
                    continue                      # out of range entirely
                pdr = self.radio.delivery_probability(rssi)
                self._links[(a, b)] = Link(a, b, d, rssi, pdr)
                self._links[(b, a)] = Link(b, a, d, rssi, pdr)

    def link(self, a: int, b: int) -> Link | None:
        return self._links.get((a, b))

    def neighbors(self, addr: int) -> list[Link]:
        """Links this node can currently hear, strongest first."""
        out = [lk for (s, _), lk in self._links.items()
               if s == addr and lk.dst not in self.down and lk.src not in self.down]
        return sorted(out, key=lambda lk: lk.rssi_dbm, reverse=True)

    def is_alive(self, addr: int) -> bool:
        return addr not in self.down

    def set_down(self, addr: int) -> None:
        """Take a node off the air -- flat battery, theft, or a demo pulling power."""
        if addr == GATEWAY_ADDR:
            raise ValueError("the gateway cannot be taken down; nothing would be heard")
        self.down.add(addr)

    def set_up(self, addr: int) -> None:
        self.down.discard(addr)

    # -------------------------------------------------------------- routing
    def deliver(self, src: int, ttl: int | None = None) -> DeliveryResult:
        """Flood one frame from ``src`` and report whether it reached the gateway.

        Simulates the real algorithm hop by hop: holders rebroadcast once, each
        link succeeds stochastically, already-seen frames are dropped, and TTL
        bounds the flood. The hop count that comes back is the true path length,
        which is what the dashboard plots and what reveals a re-heal.
        """
        ttl = self.default_ttl if ttl is None else ttl
        if src in self.down:
            return DeliveryResult(delivered=False)

        # Nodes currently holding the frame, mapped to the path that got it there.
        holders: dict[int, list[int]] = {src: [src]}
        seen: set[int] = {src}
        transmissions = 0

        for hop in range(1, ttl + 1):
            next_holders: dict[int, list[int]] = {}
            for holder, path in holders.items():
                transmissions += 1
                for lk in self.neighbors(holder):
                    if lk.dst in seen or lk.dst in self.down:
                        continue
                    if self.rng.random() > lk.pdr:
                        continue                      # lost to the link budget
                    if lk.dst == GATEWAY_ADDR:
                        return DeliveryResult(
                            delivered=True, hops=hop, path=path + [GATEWAY_ADDR],
                            rssi_at_gateway=int(lk.rssi_dbm),
                            snr_at_gateway=lk.snr_db,
                            transmissions=transmissions)
                    # Keep the first arrival; later copies are the duplicates that
                    # de-duplication exists to discard.
                    if lk.dst not in next_holders:
                        next_holders[lk.dst] = path + [lk.dst]

            seen.update(next_holders)
            holders = next_holders
            if not holders:
                break

        return DeliveryResult(delivered=False, transmissions=transmissions)

    def neighbor_table(self, addr: int, limit: int = 8) -> list[Link]:
        """What a node would report in a NEIGHBOR frame."""
        return self.neighbors(addr)[:limit]

    # ----------------------------------------------------------- diagnostics
    def reachability(self, trials: int = 40) -> dict[int, float]:
        """Fraction of frames each live node gets home. The honest measure of
        whether the field is actually covered."""
        out: dict[int, float] = {}
        for addr in self.nodes:
            if addr in self.down:
                out[addr] = 0.0
                continue
            got = sum(self.deliver(addr).delivered for _ in range(trials))
            out[addr] = got / trials
        return out

    def direct_reachability(self, trials: int = 40) -> dict[int, float]:
        """Same measure with relaying disabled (TTL 1) -- what a plain star
        topology would achieve. The difference is what the mesh buys."""
        out: dict[int, float] = {}
        for addr in self.nodes:
            if addr in self.down:
                out[addr] = 0.0
                continue
            got = sum(self.deliver(addr, ttl=1).delivered for _ in range(trials))
            out[addr] = got / trials
        return out
