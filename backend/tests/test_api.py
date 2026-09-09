"""Backend behaviour tests, exercised through the real HTTP surface."""

from __future__ import annotations

import time

import pytest
from subnet_proto import (
    ADDR_GATEWAY, GNSS_FIX_3D, CfgStatus, Config, ConfigAck, Event, EventCode, Neighbor,
    NeighborReport, Position, Severity, Telemetry, pack_gnss_status,
)

#: The commissioning temperature every fixture frame is taken at. Held constant
#: unless a test is specifically about thermal drift, so that tilt assertions are
#: about ground movement and nothing else.
REF_TEMP_C = 28.0


def tlm(pitch: int = 0, roll: int = 0, *, temp_c: float = REF_TEMP_C, vib: int = 20,
        t: int | None = None) -> Telemetry:
    return Telemetry(t_epoch=t or int(time.time()), pitch_mdeg=pitch, roll_mdeg=roll,
                     vib_rms_mg=vib, temp_c_x100=int(temp_c * 100), n_samples=32,
                     gnss_status=pack_gnss_status(GNSS_FIX_3D, 9),
                     vbat_mv=3900, rssi=-70, snr=112)


async def post_frames(client, b64, *frames) -> dict:
    resp = await client.post("/api/ingest", json={"frames": [b64(f) for f in frames]})
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestHealth:
    async def test_health(self, client):
        body = (await client.get("/api/health")).json()
        assert body["status"] == "ok"

    async def test_snapshot_without_a_site_is_empty_not_an_error(self, client):
        """A freshly installed server has no panel yet; that is not a failure."""
        body = (await client.get("/api/snapshot")).json()
        assert body["nodes"] == []
        assert body["kpis"]["totalNodes"] == 0


class TestProvisioning:
    async def test_creates_site_and_nodes(self, provisioned):
        nodes = (await provisioned.get("/api/nodes")).json()
        assert {n["addr"] for n in nodes} == {0x10, 0x11}

    async def test_is_idempotent(self, client, site_payload):
        first = (await client.post("/api/provision", json=site_payload)).json()
        second = (await client.post("/api/provision", json=site_payload)).json()
        assert first["nodesCreated"] == 2
        assert second["nodesCreated"] == 0 and second["nodesUpdated"] == 2

    async def test_unknown_node_is_auto_provisioned(self, provisioned, b64):
        """A node appearing on the mesh should appear on the dashboard."""
        await post_frames(provisioned, b64, tlm().frame(src=0x55, seq=1))
        addrs = {n["addr"] for n in (await provisioned.get("/api/nodes")).json()}
        assert 0x55 in addrs


class TestIngest:
    async def test_telemetry_is_stored_and_surfaces_in_the_snapshot(self, provisioned, b64):
        await post_frames(provisioned, b64, tlm(pitch=500).frame(src=0x10, seq=1))
        snap = (await provisioned.get("/api/snapshot")).json()
        node = next(n for n in snap["nodes"] if n["addr"] == 0x10)
        assert node["online"] is True
        assert snap["kpis"]["activeNodes"] == 1

    async def test_corrupt_frame_is_rejected_not_fatal(self, provisioned, b64):
        frame = bytearray(tlm(pitch=100).frame(src=0x10, seq=1))
        frame[18] ^= 0xFF                       # flip a payload bit
        result = await post_frames(provisioned, b64, bytes(frame))
        assert result["rejected"] == 1 and result["accepted"] == 0
        assert "CRC" in result["errors"][0]

    async def test_a_good_frame_still_lands_alongside_a_corrupt_one(self, provisioned, b64):
        bad = bytearray(tlm().frame(src=0x10, seq=1))
        bad[0] = 0xAA                           # bad magic
        result = await post_frames(provisioned, b64, bytes(bad),
                                   tlm(pitch=50).frame(src=0x11, seq=2))
        assert result["accepted"] == 1 and result["rejected"] == 1

    async def test_non_base64_body_is_a_client_error(self, provisioned):
        resp = await provisioned.post("/api/ingest", json={"frames": ["not base64!!"]})
        assert resp.status_code == 400

    async def test_replayed_frame_does_not_duplicate(self, provisioned, b64):
        """A relayed frame can reach the gateway twice."""
        frame = tlm(pitch=120, t=1_767_225_600).frame(src=0x10, seq=9)
        await post_frames(provisioned, b64, frame)
        await post_frames(provisioned, b64, frame)
        history = (await provisioned.get("/api/nodes/16/history?range=24H")).json()
        assert len(history) == 1


class TestBaselines:
    async def test_first_frame_establishes_the_baseline_and_never_alerts(
            self, provisioned, b64):
        """A node is planted at whatever angle the ground allows. Reading that
        installation angle as ground movement would alert on every new node."""
        await post_frames(provisioned, b64, tlm(pitch=4000, roll=-3000).frame(src=0x10, seq=1))
        snap = (await provisioned.get("/api/snapshot")).json()
        node = next(n for n in snap["nodes"] if n["addr"] == 0x10)
        assert node["tiltDeg"] == pytest.approx(0.0, abs=1e-9)
        assert snap["alerts"] == []

    async def test_movement_after_baseline_is_measured(self, provisioned, b64):
        await post_frames(provisioned, b64, tlm(pitch=4000).frame(src=0x10, seq=1))
        await post_frames(provisioned, b64, tlm(pitch=4700).frame(src=0x10, seq=2))
        snap = (await provisioned.get("/api/snapshot")).json()
        node = next(n for n in snap["nodes"] if n["addr"] == 0x10)
        assert node["tiltDeg"] == pytest.approx(0.7, abs=0.01)

    async def test_history_is_baseline_corrected_like_the_gauges(self, provisioned, b64):
        """The chart and the gauge must not disagree about the same node."""
        await post_frames(provisioned, b64, tlm(pitch=4000).frame(src=0x10, seq=1))
        await post_frames(provisioned, b64, tlm(pitch=4500).frame(src=0x10, seq=2))
        history = (await provisioned.get("/api/nodes/16/history?range=24H")).json()
        snap = (await provisioned.get("/api/snapshot")).json()
        node = next(n for n in snap["nodes"] if n["addr"] == 0x10)
        assert history[-1]["pitch"] == pytest.approx(node["tiltPitchDeg"], abs=1e-6)
        assert history[-1]["pitch"] == pytest.approx(0.5, abs=1e-6)

    async def test_recalibrate_clears_the_baseline(self, provisioned, b64):
        await post_frames(provisioned, b64, tlm(pitch=4000).frame(src=0x10, seq=1))
        await provisioned.post("/api/nodes/16/recalibrate")
        await post_frames(provisioned, b64, tlm(pitch=9000).frame(src=0x10, seq=2))
        snap = (await provisioned.get("/api/snapshot")).json()
        node = next(n for n in snap["nodes"] if n["addr"] == 0x10)
        assert node["tiltDeg"] == pytest.approx(0.0, abs=1e-9)


class TestAlerts:
    async def test_threshold_breach_raises_an_alert(self, provisioned, b64):
        await post_frames(provisioned, b64, tlm().frame(src=0x10, seq=1))
        await post_frames(provisioned, b64, tlm(pitch=900).frame(src=0x10, seq=2))
        alerts = (await provisioned.get("/api/alerts")).json()
        assert len(alerts) == 1
        assert alerts[0]["severity"] >= 2

    async def test_alerts_are_rate_limited_per_node(self, provisioned, b64):
        """An early-warning system that repeats itself gets muted by its users."""
        await post_frames(provisioned, b64, tlm().frame(src=0x10, seq=1))
        for seq in range(2, 8):
            await post_frames(provisioned, b64, tlm(pitch=900).frame(src=0x10, seq=seq))
        assert len(((await provisioned.get("/api/alerts")).json())) == 1

    async def test_node_event_frame_raises_an_alert(self, provisioned, b64):
        evt = Event(t_epoch=int(time.time()), event_code=EventCode.TILT_ACCEL,
                    severity=Severity.CRITICAL, value=4200, threshold=2000)
        await post_frames(provisioned, b64, evt.frame(src=0x11, seq=1))
        alerts = (await provisioned.get("/api/alerts")).json()
        assert alerts[0]["title"] == "Tilt Accelerating"

    async def test_ack_and_resolve(self, provisioned, b64):
        await post_frames(provisioned, b64, tlm().frame(src=0x10, seq=1))
        await post_frames(provisioned, b64, tlm(pitch=900).frame(src=0x10, seq=2))
        alert_id = (await provisioned.get("/api/alerts")).json()[0]["id"]

        assert (await provisioned.post(f"/api/alerts/{alert_id}/ack")).json()["state"] == "acked"
        assert (await provisioned.post(
            f"/api/alerts/{alert_id}/resolve")).json()["state"] == "resolved"
        # Resolved alerts leave the live view.
        assert (await provisioned.get("/api/snapshot")).json()["alerts"] == []

    async def test_ack_of_missing_alert_is_404(self, provisioned):
        assert (await provisioned.post("/api/alerts/9999/ack")).status_code == 404


class TestConfigDownlink:
    async def test_push_creates_a_pending_version(self, provisioned):
        resp = await provisioned.post("/api/nodes/16/config",
                                      json={"sample_interval_s": 30})
        assert resp.status_code == 201
        body = resp.json()
        assert body["cfg_version"] == 1 and body["cfg_hash"] != 0

    async def test_hash_matches_what_the_node_will_verify(self, provisioned):
        body = (await provisioned.post("/api/nodes/16/config",
                                       json={"sample_interval_s": 45})).json()
        expected = Config(cfg_version=1, sample_interval_s=45).compute_hash()
        assert body["cfg_hash"] == expected

    async def test_ack_closes_the_loop(self, provisioned, b64):
        """Pending until the node confirms -- a downlink that never reached a
        sleeping node must be visible as such, not assumed."""
        pushed = (await provisioned.post("/api/nodes/16/config", json={})).json()
        assert (await provisioned.get("/api/nodes/16/config")).json()[0]["status"] == "pending"

        ack = ConfigAck(t_epoch=int(time.time()), cfg_version=pushed["cfg_version"],
                        cfg_hash=pushed["cfg_hash"], status=CfgStatus.APPLIED)
        await post_frames(provisioned, b64, ack.frame(src=0x10, seq=1))
        assert (await provisioned.get("/api/nodes/16/config")).json()[0]["status"] == "applied"

    async def test_versions_increment(self, provisioned):
        first = (await provisioned.post("/api/nodes/16/config", json={})).json()
        second = (await provisioned.post("/api/nodes/16/config", json={})).json()
        assert second["cfg_version"] == first["cfg_version"] + 1

    async def test_rejects_out_of_range_settings(self, provisioned):
        resp = await provisioned.post("/api/nodes/16/config",
                                      json={"tx_power_dbm": 40})
        assert resp.status_code == 422

    async def test_config_for_unknown_node_is_404(self, provisioned):
        assert (await provisioned.post("/api/nodes/999/config", json={})).status_code == 404


class TestMeshTopology:
    async def test_neighbour_report_builds_links(self, provisioned, b64):
        report = NeighborReport(t_epoch=int(time.time()),
                                neighbors=[Neighbor(0x11, -72, 110)])
        await post_frames(provisioned, b64, report.frame(src=0x10, seq=1))
        links = (await provisioned.get("/api/snapshot")).json()["links"]
        assert any({l["a"], l["b"]} == {0x10, 0x11} for l in links)

    async def test_route_links_join_adjacent_hop_counts(self, provisioned, b64):
        """A link carries traffic when it joins a node to one a hop closer in."""
        await post_frames(provisioned, b64,
                          tlm().frame(src=0x10, seq=1, hops=1),
                          tlm().frame(src=0x11, seq=2, hops=2))
        report = NeighborReport(t_epoch=int(time.time()),
                                neighbors=[Neighbor(0x11, -72, 110)])
        await post_frames(provisioned, b64, report.frame(src=0x10, seq=3))
        links = (await provisioned.get("/api/snapshot")).json()["links"]
        assert next(l for l in links if {l["a"], l["b"]} == {0x10, 0x11})["onRoute"]


class TestOperations:
    async def test_face_advance_updates_the_model(self, provisioned):
        resp = await provisioned.patch("/api/sites/test-panel/face",
                                       json={"face_x_m": 450})
        assert resp.status_code == 200
        assert (await provisioned.get("/api/snapshot")).json()["faceX"] == 450

    async def test_node_can_be_placed_on_the_map(self, provisioned):
        await provisioned.patch("/api/nodes/16", json={"lat": 23.9, "lon": 86.5})
        node = next(n for n in (await provisioned.get("/api/snapshot")).json()["nodes"]
                    if n["addr"] == 0x10)
        assert node["lat"] == pytest.approx(23.9)

    async def test_stats(self, provisioned, b64):
        await post_frames(provisioned, b64, tlm().frame(src=0x10, seq=1))
        assert (await provisioned.get("/api/stats")).json()["framesTotal"] == 1


class TestThermalDrift:
    """The correction that decides whether this hardware is usable at all.

    Post expansion swings apparent tilt by several times the sensor noise across
    an ordinary day. Without the temperature channel that is indistinguishable
    from ground movement, and the system cries wolf every afternoon.
    """

    async def test_a_temperature_swing_alone_is_not_ground_movement(self, provisioned, b64):
        await post_frames(provisioned, b64, tlm(pitch=4000, temp_c=REF_TEMP_C).frame(src=0x10, seq=1))
        # 15 degC hotter, and the post has expanded by 15 * 18 = 270 mdeg.
        hot = tlm(pitch=4000 + 270, roll=270, temp_c=REF_TEMP_C + 15.0)
        await post_frames(provisioned, b64, hot.frame(src=0x10, seq=2))

        snap = (await provisioned.get("/api/snapshot")).json()
        node = next(n for n in snap["nodes"] if n["addr"] == 0x10)
        assert node["tiltDeg"] == pytest.approx(0.0, abs=0.02)
        assert snap["alerts"] == []

    async def test_real_movement_during_a_temperature_swing_still_reads(self, provisioned, b64):
        """And the correction must not swallow the signal along with the drift."""
        await post_frames(provisioned, b64, tlm(pitch=4000, temp_c=REF_TEMP_C).frame(src=0x10, seq=1))
        moved = tlm(pitch=4000 + 270 + 800, roll=270, temp_c=REF_TEMP_C + 15.0)
        await post_frames(provisioned, b64, moved.frame(src=0x10, seq=2))

        snap = (await provisioned.get("/api/snapshot")).json()
        node = next(n for n in snap["nodes"] if n["addr"] == 0x10)
        assert node["tiltDeg"] == pytest.approx(0.8, abs=0.02)

    async def test_history_is_temperature_corrected_like_the_gauges(self, provisioned, b64):
        await post_frames(provisioned, b64, tlm(pitch=4000, temp_c=REF_TEMP_C).frame(src=0x10, seq=1))
        await post_frames(provisioned, b64,
                          tlm(pitch=4270, temp_c=REF_TEMP_C + 15.0).frame(src=0x10, seq=2))
        history = (await provisioned.get("/api/nodes/16/history?range=24H")).json()
        assert history[-1]["pitch"] == pytest.approx(0.0, abs=1e-6)
        assert history[-1]["tempC"] == pytest.approx(REF_TEMP_C + 15.0, abs=0.01)


class TestReconstructedField:
    """Strain has no sensor behind it any more -- it comes from the array."""

    async def test_strain_is_reported_for_a_placed_pair(self, provisioned, b64):
        await post_frames(provisioned, b64,
                          tlm().frame(src=0x10, seq=1), tlm().frame(src=0x11, seq=1))
        # 0x10 at x=0 stays put; 0x11 at x=150 m tilts. That gradient is strain.
        await post_frames(provisioned, b64,
                          tlm().frame(src=0x10, seq=2), tlm(pitch=500).frame(src=0x11, seq=2))
        snap = (await provisioned.get("/api/snapshot")).json()
        node = next(n for n in snap["nodes"] if n["addr"] == 0x11)
        assert node["strainValid"]
        assert abs(node["strainMmPerM"]) > 0

    async def test_an_unplaced_node_reports_no_strain_rather_than_zero(self, provisioned, b64):
        """Zero strain renders as a healthy node. Unknown must not."""
        await post_frames(provisioned, b64, tlm(pitch=500).frame(src=0x99, seq=1))
        snap = (await provisioned.get("/api/snapshot")).json()
        node = next(n for n in snap["nodes"] if n["addr"] == 0x99)
        assert not node["strainValid"]

    async def test_subsidence_is_flagged_when_the_anchor_sits_inside_the_trough(
            self, provisioned, b64):
        await post_frames(provisioned, b64,
                          tlm().frame(src=0x10, seq=1), tlm().frame(src=0x11, seq=1))
        snap = (await provisioned.get("/api/snapshot")).json()
        # The westernmost fixture node is at x=0, on the panel edge -- not the
        # full radius of influence beyond it, so depths are provisional.
        assert all(not n["subsidenceValid"] for n in snap["nodes"] if n["online"])


class TestGnss:
    async def test_a_fix_places_a_node_that_was_never_surveyed(self, provisioned, b64):
        await post_frames(provisioned, b64, tlm().frame(src=0x42, seq=1))
        pos = Position(t_epoch=int(time.time()), lat_e7=237500000, lon_e7=864200000,
                       alt_m=210, h_acc_cm=250,
                       gnss_status=pack_gnss_status(GNSS_FIX_3D, 9))
        await post_frames(provisioned, b64, pos.frame(src=0x42, seq=2))

        node = next(n for n in (await provisioned.get("/api/nodes")).json()
                    if n["addr"] == 0x42)
        assert node["lat"] == pytest.approx(23.75, abs=1e-4)
        assert node["position_source"] == "gnss"

    async def test_a_node_that_has_moved_metres_raises_an_alert(self, provisioned, b64):
        await post_frames(provisioned, b64, tlm().frame(src=0x10, seq=1))
        # ~110 m north of its surveyed position: a collapse, or a theft.
        pos = Position(t_epoch=int(time.time()), lat_e7=int(23.751 * 1e7),
                       lon_e7=int(86.42 * 1e7), alt_m=210, h_acc_cm=250,
                       gnss_status=pack_gnss_status(GNSS_FIX_3D, 9))
        await post_frames(provisioned, b64, pos.frame(src=0x10, seq=2))
        titles = [a["title"] for a in (await provisioned.get("/api/alerts")).json()]
        assert "Node Displaced" in titles

    async def test_metre_scale_noise_does_not_raise_an_alert(self, provisioned, b64):
        """Ordinary GNSS wander must never look like a collapse."""
        await post_frames(provisioned, b64, tlm().frame(src=0x10, seq=1))
        pos = Position(t_epoch=int(time.time()), lat_e7=int(23.75002 * 1e7),
                       lon_e7=int(86.42 * 1e7), alt_m=210, h_acc_cm=250,
                       gnss_status=pack_gnss_status(GNSS_FIX_3D, 9))
        await post_frames(provisioned, b64, pos.frame(src=0x10, seq=2))
        titles = [a["title"] for a in (await provisioned.get("/api/alerts")).json()]
        assert "Node Displaced" not in titles

    async def test_an_unusable_fix_is_ignored(self, provisioned, b64):
        await post_frames(provisioned, b64, tlm().frame(src=0x43, seq=1))
        pos = Position(t_epoch=int(time.time()), lat_e7=237500000, lon_e7=864200000,
                       h_acc_cm=0, gnss_status=pack_gnss_status(1, 3))   # 2-D only
        await post_frames(provisioned, b64, pos.frame(src=0x43, seq=2))
        node = next(n for n in (await provisioned.get("/api/nodes")).json()
                    if n["addr"] == 0x43)
        assert node["lat"] is None
