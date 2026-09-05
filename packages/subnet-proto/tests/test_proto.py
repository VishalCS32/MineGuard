"""Wire-protocol conformance tests.

The critical ones are in TestCrossLanguage: they compile the real firmware header
and assert the C and Python encoders produce identical bytes. Everything the mesh
carries depends on those two staying in lockstep.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from subnet_proto import proto
from subnet_proto import (
    ADDR_GATEWAY,
    Config,
    ConfigAck,
    Event,
    EventCode,
    Header,
    MsgType,
    Neighbor,
    NeighborReport,
    ProtocolError,
    Severity,
    Telemetry,
    TimeSync,
    crc16,
    decode,
)

REPO = Path(__file__).resolve().parents[3]
FIRMWARE_COMMON = REPO / "firmware" / "common"


# ------------------------------------------------------------------ round trips
class TestRoundTrip:
    def test_telemetry(self):
        tlm = Telemetry(t_epoch=1767225600, pitch_mdeg=-1234, roll_mdeg=5678,
                        vib_rms_mg=412, vib_peak_hz=37, tof_mm=2450, crack_ohm=1500,
                        vbat_mv=3987, rssi=-87, snr=122, flags=proto.TLM_RELAYED)
        header, decoded = decode(tlm.frame(src=0x42, seq=0x1337, hops=2))
        assert header.msg_type is MsgType.TELEMETRY
        assert (header.src, header.dst, header.seq, header.hops) == (0x42, ADDR_GATEWAY, 0x1337, 2)
        assert decoded == tlm

    def test_telemetry_frame_is_34_bytes(self):
        """Airtime budget: header + telemetry must stay small at SF9."""
        assert len(Telemetry(t_epoch=0).frame(src=1)) == 34

    def test_event(self):
        evt = Event(t_epoch=1767225600, event_code=EventCode.TILT_RATE,
                    severity=Severity.CRITICAL, value=-4200, threshold=2000)
        header, decoded = decode(evt.frame(src=7, seq=9))
        assert header.msg_type is MsgType.EVENT
        assert decoded == evt

    def test_config_and_ack_hash_agree(self):
        """The ACK echoes cfg_hash; that is how the dashboard knows it really landed."""
        cfg = Config(cfg_version=12, sample_interval_s=30, tilt_alert_mdeg=1500)
        _, decoded = decode(cfg.frame(src=ADDR_GATEWAY, dst=0x42))
        assert decoded == cfg
        assert decoded.cfg_hash == cfg.compute_hash() != 0

        ack = ConfigAck(t_epoch=1767225600, cfg_version=12, cfg_hash=decoded.cfg_hash)
        _, decoded_ack = decode(ack.frame(src=0x42))
        assert decoded_ack.cfg_hash == cfg.cfg_hash
        assert decoded_ack.status is proto.CfgStatus.APPLIED

    def test_neighbor_report_variable_length(self):
        rep = NeighborReport(t_epoch=1767225600, neighbors=[
            Neighbor(0x02, -71, 110), Neighbor(0x03, -94, 96), Neighbor(0x04, -55, 130)])
        _, decoded = decode(rep.frame(src=0x42))
        assert decoded == rep
        assert len(rep.pack()) == 5 + 3 * 4

    def test_empty_neighbor_report(self):
        _, decoded = decode(NeighborReport(t_epoch=1, neighbors=[]).frame(src=1))
        assert decoded.neighbors == []

    def test_time_sync(self):
        _, decoded = decode(TimeSync(t_epoch=1767225600, t_millis=750).frame(
            src=ADDR_GATEWAY, dst=proto.ADDR_BROADCAST))
        assert decoded == TimeSync(1767225600, 750)

    @pytest.mark.parametrize("pitch,roll", [(0, 0), (-32768, 32767), (1000, -1000)])
    def test_signed_tilt_extremes(self, pitch, roll):
        _, decoded = decode(Telemetry(t_epoch=0, pitch_mdeg=pitch, roll_mdeg=roll).frame(src=1))
        assert (decoded.pitch_mdeg, decoded.roll_mdeg) == (pitch, roll)


# ------------------------------------------------------------- corrupt input
class TestRejectsCorruption:
    """A radio link delivers garbage. Ingest must reject it, not crash on it."""

    def test_truncated_frame(self):
        with pytest.raises(ProtocolError, match="too short"):
            decode(Telemetry(t_epoch=0).frame(src=1)[:8])

    def test_bad_magic(self):
        frame = bytearray(Telemetry(t_epoch=0).frame(src=1))
        frame[0] = 0xAA
        with pytest.raises(ProtocolError, match="bad magic"):
            decode(bytes(frame))

    def test_bit_flip_in_payload_caught_by_crc(self):
        frame = bytearray(Telemetry(t_epoch=1767225600, pitch_mdeg=100).frame(src=1))
        frame[20] ^= 0x01
        with pytest.raises(ProtocolError, match="CRC mismatch"):
            decode(bytes(frame))

    def test_unsupported_version(self):
        frame = bytearray(Telemetry(t_epoch=0).frame(src=1))
        frame[1] = (0xF << 4) | MsgType.TELEMETRY
        with pytest.raises(ProtocolError, match="version"):
            decode(bytes(frame))

    def test_unknown_message_type(self):
        payload = b""
        prefix = bytes([proto.MAGIC, (proto.PROTO_VER << 4) | 0xE]) + bytes(8)
        frame = prefix + crc16(prefix + payload).to_bytes(2, "little") + payload
        with pytest.raises(ProtocolError, match="unknown message type"):
            decode(frame)

    def test_wrong_payload_length(self):
        header = Header(MsgType.TELEMETRY, src=1)
        with pytest.raises(ProtocolError, match="expected 22 B"):
            decode(header.pack(b"\x00" * 10))

    def test_tampered_config_hash(self):
        frame = bytearray(Config(cfg_version=5).frame(src=ADDR_GATEWAY, dst=0x42))
        frame[12 + 1] ^= 0x01          # flip a config byte, leave the frame CRC valid
        prefix = bytes(frame[:10])
        payload = bytes(frame[12:])
        frame = prefix + crc16(prefix + payload).to_bytes(2, "little") + payload
        with pytest.raises(ProtocolError, match="config hash mismatch"):
            decode(frame)

    def test_too_many_neighbors_rejected(self):
        rep = NeighborReport(t_epoch=0, neighbors=[Neighbor(i, -70, 100) for i in range(9)])
        with pytest.raises(ProtocolError, match="exceeds"):
            rep.pack()


# ------------------------------------------------------------ engineering units
class TestEngineeringUnits:
    def test_conversions(self):
        tlm = Telemetry(t_epoch=0, pitch_mdeg=-1234, roll_mdeg=5678,
                        crack_ohm=1500, snr=122, vbat_mv=3987)
        assert tlm.pitch_deg == pytest.approx(-1.234)
        assert tlm.roll_deg == pytest.approx(5.678)
        assert tlm.crack_ohms == pytest.approx(15000.0)
        assert tlm.snr_db == pytest.approx(10.5)
        assert tlm.vbat_volts == pytest.approx(3.987)

    def test_tilt_magnitude_combines_both_axes(self):
        """Damage criteria are stated against total tilt, not per-axis."""
        tlm = Telemetry(t_epoch=0, pitch_mdeg=3000, roll_mdeg=4000)
        assert tlm.tilt_deg == pytest.approx(5.0)


# --------------------------------------------------------------- CRC vectors
class TestCrc:
    def test_known_check_value(self):
        """CRC16/CCITT-FALSE published check value for the string '123456789'."""
        assert crc16(b"123456789") == 0x29B1

    def test_empty_is_init_value(self):
        assert crc16(b"") == 0xFFFF


# ------------------------------------------------------- C <-> Python identity
@pytest.mark.skipif(shutil.which("cc") is None, reason="no C compiler available")
class TestCrossLanguage:
    """Compiles firmware/common/mesh_proto.h and diffs it against this codec."""

    @staticmethod
    @pytest.fixture(scope="class")
    def c_output(tmp_path_factory) -> dict[str, str]:
        binary = tmp_path_factory.mktemp("proto") / "proto_check"
        subprocess.run(
            ["cc", "-std=c11", "-Wall", "-Werror", f"-I{FIRMWARE_COMMON}",
             str(Path(__file__).parent / "proto_check.c"), "-o", str(binary)],
            check=True, capture_output=True)
        out = subprocess.run([str(binary)], check=True, capture_output=True, text=True).stdout
        return dict(line.split("=", 1) for line in out.strip().splitlines())

    def test_struct_sizes_match(self, c_output):
        assert int(c_output["sizeof_hdr"]) == proto.HDR_LEN == proto._HDR.size
        assert int(c_output["sizeof_tlm"]) == Telemetry._S.size
        assert int(c_output["sizeof_evt"]) == Event._S.size
        assert int(c_output["sizeof_cfg"]) == Config._S.size
        assert int(c_output["sizeof_cfg_ack"]) == ConfigAck._S.size
        assert int(c_output["sizeof_timesync"]) == TimeSync._S.size
        assert int(c_output["sizeof_neigh_hdr"]) == NeighborReport._S.size
        assert int(c_output["sizeof_neigh_entry"]) == NeighborReport._ENTRY.size

    def test_crc_implementations_agree(self, c_output):
        assert int(c_output["crc_check123456789"], 16) == crc16(b"123456789")
        assert int(c_output["crc_empty"], 16) == crc16(b"")

    def test_encoded_frame_is_byte_identical(self, c_output):
        """The real check: a node's transmitted bytes must equal what we build here."""
        tlm = Telemetry(t_epoch=1767225600, pitch_mdeg=-1234, roll_mdeg=5678,
                        vib_rms_mg=412, vib_peak_hz=37, tof_mm=2450, crack_ohm=1500,
                        vbat_mv=3987, rssi=-87, snr=122,
                        flags=proto.TLM_RELAYED | proto.TLM_LOW_BATTERY)
        assert tlm.frame(src=0x42, seq=0x1337, hops=2).hex() == c_output["frame_telemetry"]

    def test_c_frame_decodes_in_python(self, c_output):
        """And the reverse direction: C-produced bytes must parse cleanly here."""
        header, decoded = decode(bytes.fromhex(c_output["frame_telemetry"]))
        assert header.src == 0x42 and header.hops == 2
        assert decoded.tof_mm == 2450 and decoded.rssi == -87
