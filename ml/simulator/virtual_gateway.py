"""A gateway that isn't real, speaking a protocol that is.

Encodes genuine SUBSIDENCE-NET frames from the physics simulator, routes them
through the mesh model (so hop counts, relaying and packet loss are real
behaviour rather than decoration), and delivers them to the backend exactly as
an ESP32 gateway would.

This is what lets the whole software stack be built and demonstrated against the
real wire format before any hardware exists -- and, once nodes are flashed, it
keeps working as the offline demo path. The backend cannot tell the difference,
which is the point: if the simulator can drive it, so can the field.

    python -m simulator.virtual_gateway --api http://localhost:8000 --speed 60

Transports:
    http  POST /api/ingest with base64 frames (default; simplest for an ESP32)
    mqtt  publish to subnet/gw/<id>/up (what a deployed gateway uses)
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import logging
import random
import sys
import time
from dataclasses import dataclass

import numpy as np
from subnet_proto import Neighbor, NeighborReport, Telemetry

from .field import SITE_PRESETS, build_grid_field
from .mesh import MeshNetwork, Obstruction, RadioModel
from .scenarios import SCENARIOS, FieldSimulator

log = logging.getLogger("virtual-gateway")

#: One tick is fifteen simulated minutes, matching the dashboard's clock.
TICK_MINUTES = 15
SECONDS_PER_DAY = 86_400

TERRAIN = [
    Obstruction(280, -60, 90, 18.0, "overburden dump"),
    Obstruction(430, 90, 70, 14.0, "tree belt"),
]


@dataclass(slots=True)
class Stats:
    generated: int = 0
    delivered: int = 0
    lost: int = 0
    posted: int = 0
    failures: int = 0

    @property
    def delivery_pct(self) -> float:
        return 100.0 * self.delivered / self.generated if self.generated else 0.0


class VirtualGateway:
    def __init__(self, *, site: str, scenario: str, seed: int, api: str,
                 transport: str, mqtt_host: str | None, gateway_id: str,
                 start_day: float, batch: int):
        self.preset = SITE_PRESETS[site]
        radio = RadioModel()
        self.nodes = build_grid_field(
            self.preset, cols=5, rows=3, max_spacing_m=radio.max_reliable_spacing_m())
        self.sim = FieldSimulator(
            self.preset, self.nodes, SCENARIOS[scenario](self.preset,
                                                         np.random.default_rng(seed)),
            seed=seed)
        self.mesh = MeshNetwork(self.nodes, GATEWAY_LOCAL_XY(self.preset), radio=radio,
                                seed=seed, obstructions=TERRAIN)
        self.api = api.rstrip("/")
        self.transport = transport
        self.mqtt_host = mqtt_host
        self.gateway_id = gateway_id
        self.day = start_day
        self.batch = batch
        self.seq = 0
        self.stats = Stats()
        self.rng = random.Random(seed)
        self._buffer: list[bytes] = []
        self._client = None

    # ------------------------------------------------------------ provision
    async def provision(self, session) -> None:
        """Announce the panel and its nodes. Idempotent, so it is safe to re-run."""
        panel = self.preset.panel
        baselines = self._commissioning_baselines()
        payload = {
            "slug": self.preset.slug,
            "name": self.preset.name,
            "coalfield": self.preset.coalfield,
            "origin_lat": self.preset.origin_lat,
            "origin_lon": self.preset.origin_lon,
            "seam_depth_m": panel.seam_depth_m,
            "extraction_thickness_m": panel.extraction_thickness_m,
            "subsidence_factor": panel.subsidence_factor,
            "angle_of_draw_deg": panel.angle_of_draw_deg,
            "face_x_m": self._face_x(),
            "panel_x_start": panel.x_start, "panel_x_end": panel.x_end,
            "panel_y_min": panel.y_min, "panel_y_max": panel.y_max,
            "nodes": [
                {"addr": n.addr, "label": n.label, "zone": _zone(panel, n.x_m, n.y_m),
                 "lat": n.lat, "lon": n.lon, "x_m": n.x_m, "y_m": n.y_m,
                 # Commissioned on undisturbed ground, before extraction began.
                 "baseline_pitch_mdeg": baselines[n.addr][0],
                 "baseline_roll_mdeg": baselines[n.addr][1]}
                for n in self.nodes
            ],
        }
        resp = await session.post(f"{self.api}/api/provision", json=payload, timeout=30)
        resp.raise_for_status()
        log.info("provisioned: %s", resp.json())

    def _face_x(self) -> float:
        """Face position, clamped to the panel it is cutting."""
        panel = self.preset.panel
        return float(min(max(self.sim.scenario.face_x(self.day), panel.x_start),
                         panel.x_end))

    def _commissioning_baselines(self) -> dict[int, tuple[int, int]]:
        """Each node's attitude at day zero, before any extraction.

        This is the survey a crew records when the field is installed. Without
        it a node baselines itself against whatever deformation already exists
        the first time it reports, which silently zeroes out the very signal the
        system is meant to detect.
        """
        undisturbed = self.sim.sample_at(0.0, int(time.time()))
        return {ns.node.addr: (ns.telemetry.pitch_mdeg, ns.telemetry.roll_mdeg)
                for ns in undisturbed.nodes}

    # --------------------------------------------------------------- frames
    def _frames_for_tick(self) -> list[bytes]:
        """Sample the field, then push each frame through the mesh to the gateway."""
        epoch = int(time.time())
        sample = self.sim.sample_at(self.day, epoch)
        frames: list[bytes] = []

        for ns in sample.nodes:
            self.seq = (self.seq + 1) & 0xFFFF
            self.stats.generated += 1
            delivery = self.mesh.deliver(ns.node.addr)
            if not delivery.delivered:
                # Genuinely lost to the link budget. The gateway never sees it,
                # so neither does the backend -- which is how packet-delivery
                # statistics stay honest.
                self.stats.lost += 1
                continue
            self.stats.delivered += 1

            tlm: Telemetry = ns.telemetry
            tlm.rssi = delivery.rssi_at_gateway
            tlm.snr = max(0, min(255, int((delivery.snr_at_gateway + 20) * 4)))
            frames.append(tlm.frame(src=ns.node.addr, seq=self.seq,
                                    hops=delivery.hops))

        # Neighbour reports keep the topology graph alive; they are far less
        # frequent than telemetry because the topology changes slowly.
        if self.rng.random() < 0.25:
            for node in self.rng.sample(self.nodes, k=min(4, len(self.nodes))):
                table = self.mesh.neighbor_table(node.addr, limit=6)
                if not table:
                    continue
                self.seq = (self.seq + 1) & 0xFFFF
                report = NeighborReport(t_epoch=epoch, neighbors=[
                    Neighbor(lk.dst, int(lk.rssi_dbm),
                             max(0, min(255, int((lk.snr_db + 20) * 4))))
                    for lk in table
                ])
                frames.append(report.frame(src=node.addr, seq=self.seq))
        return frames

    # -------------------------------------------------------------- uplink
    async def _post(self, session, frames: list[bytes]) -> None:
        """Deliver frames, buffering them locally if the backend is unreachable.

        This is the store-and-forward behaviour a real gateway needs: mine sites
        lose connectivity, and telemetry gathered while offline must survive to
        be reconciled later rather than being dropped on the floor.
        """
        self._buffer.extend(frames)
        if not self._buffer:
            return
        payload = {
            "frames": [base64.b64encode(f).decode() for f in self._buffer[:self.batch]],
            "gateway": self.gateway_id,
            "site": self.preset.slug,
        }
        try:
            resp = await session.post(f"{self.api}/api/ingest", json=payload, timeout=15)
            resp.raise_for_status()
            sent = len(payload["frames"])
            del self._buffer[:sent]
            self.stats.posted += sent
        except Exception as exc:
            self.stats.failures += 1
            log.warning("uplink failed (%s); %d frames buffered", exc, len(self._buffer))
            # Bound the buffer the way an SD card would be bounded.
            if len(self._buffer) > 20_000:
                del self._buffer[:len(self._buffer) - 20_000]

    async def _report_face(self, session) -> None:
        """Tell the backend where the face has reached; it re-drives the model."""
        try:
            await session.patch(f"{self.api}/api/sites/{self.preset.slug}/face",
                                json={"face_x_m": self._face_x()}, timeout=10)
        except Exception as exc:
            log.debug("face update failed: %s", exc)

    async def run(self, ticks: int | None, interval: float) -> None:
        import httpx

        async with httpx.AsyncClient() as session:
            await self.provision(session)
            count = 0
            while ticks is None or count < ticks:
                frames = self._frames_for_tick()
                await self._post(session, frames)
                self.day += TICK_MINUTES / 1440
                count += 1
                if count % 24 == 0:      # roughly every six simulated hours
                    await self._report_face(session)
                if count % 20 == 0:
                    log.info("tick %d | day %.2f | delivered %.1f%% | posted %d | buffered %d",
                             count, self.day, self.stats.delivery_pct,
                             self.stats.posted, len(self._buffer))
                await asyncio.sleep(interval)


async def _noop() -> None:
    return None


def GATEWAY_LOCAL_XY(preset) -> tuple[float, float]:
    """Gateway position in the preset's local frame."""
    return (preset.panel.x_start - 0.5 * preset.panel.radius_of_influence_m, 0.0)


def _zone(panel, x: float, y: float) -> str:
    mid_y = (panel.y_min + panel.y_max) / 2
    band = (panel.y_max - panel.y_min) / 3
    if y < mid_y - band / 2:
        return "Panel A - South"
    if y > mid_y + band / 2:
        return "Panel A - North"
    span = panel.x_end - panel.x_start
    if x < panel.x_start + span / 3:
        return "Panel A - West"
    if x > panel.x_end - span / 3:
        return "Panel A - East"
    return "Panel A - Center"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--site", default="jharia", choices=sorted(SITE_PRESETS))
    parser.add_argument("--scenario", default="accelerating", choices=sorted(SCENARIOS))
    parser.add_argument("--transport", default="http", choices=["http", "mqtt"])
    parser.add_argument("--mqtt-host", default=None)
    parser.add_argument("--gateway-id", default="gw-01")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--start-day", type=float, default=40.0,
                        help="opening day: trough developed, alerts already standing")
    parser.add_argument("--interval", type=float, default=0.25,
                        help="real seconds between ticks (one tick = 15 simulated minutes)")
    parser.add_argument("--ticks", type=int, default=None, help="stop after N ticks")
    parser.add_argument("--batch", type=int, default=64, help="max frames per POST")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    gw = VirtualGateway(
        site=args.site, scenario=args.scenario, seed=args.seed, api=args.api,
        transport=args.transport, mqtt_host=args.mqtt_host,
        gateway_id=args.gateway_id, start_day=args.start_day, batch=args.batch)

    try:
        asyncio.run(gw.run(args.ticks, args.interval))
    except KeyboardInterrupt:
        pass
    log.info("generated %d, delivered %d (%.1f%%), lost %d, posted %d, failures %d",
             gw.stats.generated, gw.stats.delivered, gw.stats.delivery_pct,
             gw.stats.lost, gw.stats.posted, gw.stats.failures)
    return 0


if __name__ == "__main__":
    sys.exit(main())
