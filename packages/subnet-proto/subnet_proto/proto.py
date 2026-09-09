"""SUBSIDENCE-NET mesh wire protocol codec.

Byte-for-byte mirror of ``firmware/common/mesh_proto.h``. Both sides are checked
against the same golden vectors by ``backend/tests/test_proto.py`` -- if you change
a struct here, change it there, and regenerate the vectors.

All frames are little-endian and packed (native ESP32 layout, no byte swapping).
Frame layout:  [ 12 B header ][ payload ]
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import ClassVar

MAGIC = 0x5B
PROTO_VER = 0x1

ADDR_GATEWAY = 0x0001
ADDR_BROADCAST = 0xFFFF
ADDR_UNASSIGNED = 0x0000

HDR_LEN = 12
MAX_PAYLOAD = 52
DEFAULT_TTL = 4
MAX_NEIGHBORS = 8


class MsgType(IntEnum):
    TELEMETRY = 0x1
    EVENT = 0x2
    CONFIG_SET = 0x3
    CONFIG_ACK = 0x4
    NEIGHBOR = 0x5
    TIME_SYNC = 0x6
    POSITION = 0x7


class EventCode(IntEnum):
    TILT_RATE = 0x01        # tilt rate over threshold
    TILT_ABSOLUTE = 0x02    # absolute tilt over threshold
    TILT_ACCEL = 0x03       # tilt rate is itself increasing -- the precursor
    VIBRATION = 0x04
    DISPLACEMENT = 0x05     # GNSS: node has physically moved metres
    NODE_TAMPER = 0x06
    LOW_BATTERY = 0x07


class Severity(IntEnum):
    INFO = 0
    WARNING = 1
    HIGH = 2
    CRITICAL = 3


class CfgStatus(IntEnum):
    APPLIED = 0
    REJECTED = 1
    PARTIAL = 2


# Telemetry flag bits
TLM_TILT_FAULT = 1 << 0
TLM_GNSS_FAULT = 1 << 1
TLM_VIB_FAULT = 1 << 2
TLM_UNCALIBRATED = 1 << 3
TLM_LOW_BATTERY = 1 << 4
TLM_RELAYED = 1 << 5

# Config flag bits
CFG_RELAY_ENABLED = 1 << 0
CFG_GNSS_ENABLED = 1 << 1
CFG_VIB_ENABLED = 1 << 2
CFG_DEEP_SLEEP = 1 << 3
CFG_RECALIBRATE = 1 << 4

# GNSS fix quality, packed into the low 2 bits of ``gnss_status``.
GNSS_NO_FIX = 0
GNSS_FIX_2D = 1
GNSS_FIX_3D = 2
GNSS_FIX_DGPS = 3


class ProtocolError(ValueError):
    """Raised when a frame cannot be decoded. Never trust the radio."""


# --------------------------------------------------------------------- CRC
def crc16(data: bytes) -> int:
    """CRC16/CCITT-FALSE -- poly 0x1021, init 0xFFFF, no reflection, no xor-out.

    Must stay identical to ``mesh_crc16()`` in mesh_proto.h.
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


# ------------------------------------------------------------------ header
_HDR = struct.Struct("<BBHHHBBH")
assert _HDR.size == HDR_LEN


@dataclass(slots=True)
class Header:
    msg_type: MsgType
    src: int
    dst: int = ADDR_GATEWAY
    seq: int = 0
    ttl: int = DEFAULT_TTL
    hops: int = 0
    version: int = PROTO_VER

    def pack(self, payload: bytes) -> bytes:
        """Serialise header + payload, computing the CRC over both."""
        ver_type = ((self.version & 0x0F) << 4) | (int(self.msg_type) & 0x0F)
        # CRC covers the first 10 header bytes (everything but the CRC field) + payload
        prefix = struct.pack(
            "<BBHHHBB", MAGIC, ver_type, self.src, self.dst, self.seq, self.ttl, self.hops
        )
        return prefix + struct.pack("<H", crc16(prefix + payload)) + payload

    @classmethod
    def unpack(cls, frame: bytes) -> tuple["Header", bytes]:
        """Parse and validate a frame, returning (header, payload)."""
        if len(frame) < HDR_LEN:
            raise ProtocolError(f"frame too short: {len(frame)} B < {HDR_LEN} B header")
        magic, ver_type, src, dst, seq, ttl, hops, got_crc = _HDR.unpack(frame[:HDR_LEN])
        if magic != MAGIC:
            raise ProtocolError(f"bad magic 0x{magic:02X}, expected 0x{MAGIC:02X}")
        version = ver_type >> 4
        if version != PROTO_VER:
            raise ProtocolError(f"unsupported protocol version {version}")
        payload = frame[HDR_LEN:]
        if len(payload) > MAX_PAYLOAD:
            raise ProtocolError(f"payload {len(payload)} B exceeds {MAX_PAYLOAD} B")
        want_crc = crc16(frame[:10] + payload)
        if got_crc != want_crc:
            raise ProtocolError(f"CRC mismatch: got 0x{got_crc:04X}, computed 0x{want_crc:04X}")
        try:
            msg_type = MsgType(ver_type & 0x0F)
        except ValueError as exc:
            raise ProtocolError(f"unknown message type 0x{ver_type & 0x0F:X}") from exc
        return cls(msg_type=msg_type, src=src, dst=dst, seq=seq, ttl=ttl, hops=hops,
                   version=version), payload


# ---------------------------------------------------------------- payloads
class Payload:
    """Base for payload bodies. Subclasses declare ``_S`` and ``MSG_TYPE``."""

    _S: ClassVar[struct.Struct]
    MSG_TYPE: ClassVar[MsgType]

    def pack(self) -> bytes:  # pragma: no cover - overridden
        raise NotImplementedError

    def frame(self, src: int, seq: int = 0, dst: int = ADDR_GATEWAY,
              ttl: int = DEFAULT_TTL, hops: int = 0) -> bytes:
        """Convenience: wrap this payload in a header and serialise."""
        return Header(self.MSG_TYPE, src, dst, seq, ttl, hops).pack(self.pack())


@dataclass(slots=True)
class Telemetry(Payload):
    """22 B periodic sensor frame. Feature extraction already done on-node.

    Every field here comes from one of three sensors: the LIS3DH (attitude,
    vibration and die temperature), the vibration sensor, and the GNSS receiver.
    There is no displacement ranger and no crack gauge -- both quantities are
    recovered from the tilt *field* instead, because ``U = B*T`` and
    ``strain = B*dT/dx`` (see ``ml/simulator/physics.py``). A single node cannot
    measure them; an array of nodes can, and the array is what we deploy.
    """

    _S: ClassVar[struct.Struct] = struct.Struct("<IhhHHhBBHbBBB")
    MSG_TYPE: ClassVar[MsgType] = MsgType.TELEMETRY

    t_epoch: int
    pitch_mdeg: int = 0
    roll_mdeg: int = 0
    vib_rms_mg: int = 0
    vib_peak_hz: int = 0
    #: LIS3DH die temperature, centi-degrees C. Not a weather reading: thermal
    #: expansion of the mounting post drifts apparent tilt by ~18 mdeg/degC,
    #: which over a 15 degC day swamps the 50 mdeg sensor noise five times over.
    #: Without this field that drift is indistinguishable from ground movement.
    temp_c_x100: int = 0
    #: Raw samples averaged into this frame. The server needs it to know this
    #: reading's noise (sigma/sqrt(n)) before differentiating the tilt field.
    n_samples: int = 1
    #: Low 2 bits fix quality (GNSS_*), high 6 bits satellite count.
    gnss_status: int = 0
    vbat_mv: int = 0
    rssi: int = 0
    snr: int = 0              # raw field = (dB + 20) * 4
    flags: int = 0
    reserved: int = 0

    def pack(self) -> bytes:
        return self._S.pack(
            self.t_epoch, self.pitch_mdeg, self.roll_mdeg, self.vib_rms_mg,
            self.vib_peak_hz, self.temp_c_x100, self.n_samples, self.gnss_status,
            self.vbat_mv, self.rssi, self.snr, self.flags, self.reserved)

    @classmethod
    def unpack(cls, b: bytes) -> "Telemetry":
        if len(b) != cls._S.size:
            raise ProtocolError(f"telemetry payload is {len(b)} B, expected {cls._S.size} B")
        return cls(*cls._S.unpack(b))

    # -- engineering units -------------------------------------------------
    @property
    def pitch_deg(self) -> float:
        return self.pitch_mdeg / 1000.0

    @property
    def roll_deg(self) -> float:
        return self.roll_mdeg / 1000.0

    @property
    def tilt_deg(self) -> float:
        """Total tilt magnitude -- the quantity subsidence damage criteria use."""
        return (self.pitch_mdeg**2 + self.roll_mdeg**2) ** 0.5 / 1000.0

    @property
    def temp_c(self) -> float:
        return self.temp_c_x100 / 100.0

    @property
    def gnss_fix(self) -> int:
        """Fix quality: one of the GNSS_* constants."""
        return self.gnss_status & 0x03

    @property
    def gnss_sats(self) -> int:
        return (self.gnss_status >> 2) & 0x3F

    @property
    def has_fix(self) -> bool:
        return self.gnss_fix >= GNSS_FIX_2D

    @property
    def snr_db(self) -> float:
        return self.snr / 4.0 - 20.0

    @property
    def vbat_volts(self) -> float:
        return self.vbat_mv / 1000.0


def pack_gnss_status(fix: int, sats: int) -> int:
    """Build the packed ``gnss_status`` byte from a fix quality and sat count."""
    return (fix & 0x03) | ((min(sats, 63) & 0x3F) << 2)


@dataclass(slots=True)
class Event(Payload):
    """14 B immediate alert. Bypasses the duty cycle -- sent the moment it trips."""

    _S: ClassVar[struct.Struct] = struct.Struct("<IBBii")
    MSG_TYPE: ClassVar[MsgType] = MsgType.EVENT

    t_epoch: int
    event_code: EventCode
    severity: Severity
    value: int = 0            # milli-units, event-specific
    threshold: int = 0

    def pack(self) -> bytes:
        return self._S.pack(self.t_epoch, int(self.event_code), int(self.severity),
                            self.value, self.threshold)

    @classmethod
    def unpack(cls, b: bytes) -> "Event":
        if len(b) != cls._S.size:
            raise ProtocolError(f"event payload is {len(b)} B, expected {cls._S.size} B")
        t, code, sev, val, thr = cls._S.unpack(b)
        return cls(t, EventCode(code), Severity(sev), val, thr)


@dataclass(slots=True)
class Config(Payload):
    """20 B downlink configuration. ``cfg_hash`` is computed, never set by hand."""

    _S: ClassVar[struct.Struct] = struct.Struct("<HHHBHHHhhBH")
    MSG_TYPE: ClassVar[MsgType] = MsgType.CONFIG_SET

    cfg_version: int
    sample_interval_s: int = 60
    wor_period_ms: int = 2000
    tx_power_dbm: int = 22
    tilt_alert_mdeg: int = 2000
    vib_alert_mg: int = 500
    #: Tilt *rate* in milli-degrees per hour. With no crack gauge this is the
    #: node's primary early-warning trigger: accelerating tilt precedes failure,
    #: and a rate threshold fires while absolute tilt is still well inside limits.
    tilt_rate_alert_mdeg_h: int = 150
    tilt_offset_pitch: int = 0
    tilt_offset_roll: int = 0
    flags: int = CFG_RELAY_ENABLED | CFG_GNSS_ENABLED | CFG_VIB_ENABLED | CFG_DEEP_SLEEP
    cfg_hash: int = 0

    def _body(self) -> bytes:
        """The 18 hashed bytes -- everything except cfg_hash itself."""
        return struct.pack(
            "<HHHBHHHhhB", self.cfg_version, self.sample_interval_s, self.wor_period_ms,
            self.tx_power_dbm, self.tilt_alert_mdeg, self.vib_alert_mg,
            self.tilt_rate_alert_mdeg_h, self.tilt_offset_pitch, self.tilt_offset_roll,
            self.flags)

    def compute_hash(self) -> int:
        return crc16(self._body())

    def pack(self) -> bytes:
        body = self._body()
        self.cfg_hash = crc16(body)
        return body + struct.pack("<H", self.cfg_hash)

    @classmethod
    def unpack(cls, b: bytes) -> "Config":
        if len(b) != cls._S.size:
            raise ProtocolError(f"config payload is {len(b)} B, expected {cls._S.size} B")
        cfg = cls(*cls._S.unpack(b))
        expected = cfg.compute_hash()
        if cfg.cfg_hash != expected:
            raise ProtocolError(
                f"config hash mismatch: got 0x{cfg.cfg_hash:04X}, computed 0x{expected:04X}")
        return cfg


@dataclass(slots=True)
class ConfigAck(Payload):
    """9 B confirmation. ``cfg_hash`` must echo the pushed config exactly."""

    _S: ClassVar[struct.Struct] = struct.Struct("<IHHB")
    MSG_TYPE: ClassVar[MsgType] = MsgType.CONFIG_ACK

    t_epoch: int
    cfg_version: int
    cfg_hash: int
    status: CfgStatus = CfgStatus.APPLIED

    def pack(self) -> bytes:
        return self._S.pack(self.t_epoch, self.cfg_version, self.cfg_hash, int(self.status))

    @classmethod
    def unpack(cls, b: bytes) -> "ConfigAck":
        if len(b) != cls._S.size:
            raise ProtocolError(f"config-ack payload is {len(b)} B, expected {cls._S.size} B")
        t, ver, h, status = cls._S.unpack(b)
        return cls(t, ver, h, CfgStatus(status))


@dataclass(slots=True)
class Neighbor:
    addr: int
    rssi: int
    snr: int

    @property
    def snr_db(self) -> float:
        return self.snr / 4.0 - 20.0


@dataclass(slots=True)
class NeighborReport(Payload):
    """Variable length: 5 B header + 4 B per neighbour. Drives the topology graph."""

    _S: ClassVar[struct.Struct] = struct.Struct("<IB")
    _ENTRY: ClassVar[struct.Struct] = struct.Struct("<HbB")
    MSG_TYPE: ClassVar[MsgType] = MsgType.NEIGHBOR

    t_epoch: int
    neighbors: list[Neighbor] = field(default_factory=list)

    def pack(self) -> bytes:
        if len(self.neighbors) > MAX_NEIGHBORS:
            raise ProtocolError(f"{len(self.neighbors)} neighbours exceeds {MAX_NEIGHBORS}")
        out = self._S.pack(self.t_epoch, len(self.neighbors))
        for n in self.neighbors:
            out += self._ENTRY.pack(n.addr, n.rssi, n.snr)
        return out

    @classmethod
    def unpack(cls, b: bytes) -> "NeighborReport":
        if len(b) < cls._S.size:
            raise ProtocolError(f"neighbour payload is {len(b)} B, expected >= {cls._S.size} B")
        t_epoch, count = cls._S.unpack(b[: cls._S.size])
        if count > MAX_NEIGHBORS:
            raise ProtocolError(f"neighbour count {count} exceeds {MAX_NEIGHBORS}")
        want = cls._S.size + count * cls._ENTRY.size
        if len(b) != want:
            raise ProtocolError(f"neighbour payload is {len(b)} B, expected {want} B "
                                f"for count={count}")
        entries = [
            Neighbor(*cls._ENTRY.unpack_from(b, cls._S.size + i * cls._ENTRY.size))
            for i in range(count)
        ]
        return cls(t_epoch, entries)


@dataclass(slots=True)
class TimeSync(Payload):
    """6 B downlink clock discipline. Nodes carry no RTC across deep sleep."""

    _S: ClassVar[struct.Struct] = struct.Struct("<IH")
    MSG_TYPE: ClassVar[MsgType] = MsgType.TIME_SYNC

    t_epoch: int
    t_millis: int = 0

    def pack(self) -> bytes:
        return self._S.pack(self.t_epoch, self.t_millis)

    @classmethod
    def unpack(cls, b: bytes) -> "TimeSync":
        if len(b) != cls._S.size:
            raise ProtocolError(f"time-sync payload is {len(b)} B, expected {cls._S.size} B")
        return cls(*cls._S.unpack(b))


@dataclass(slots=True)
class Position(Payload):
    """17 B GNSS report. Low rate -- position is static until it isn't.

    Deliberately not part of TELEMETRY. A node's position does not change from
    one duty cycle to the next, so spending 10 bytes on it every minute would
    burn airtime to retransmit a constant. It is sent at commissioning, then
    rarely, then immediately if the node detects it has moved.

    This does *not* measure subsidence. A NEO-6M is metre-scale and subsidence is
    millimetre-scale, so the two are three orders of magnitude apart. What it
    does measure: where the node is (self-localisation, so no operator has to
    drop a pin), the inter-node baselines the strain calculation divides by, and
    gross displacement -- a node that has moved metres is a collapse or a theft,
    and both are worth an immediate frame.
    """

    _S: ClassVar[struct.Struct] = struct.Struct("<IiihHB")
    MSG_TYPE: ClassVar[MsgType] = MsgType.POSITION

    t_epoch: int
    lat_e7: int = 0           # degrees * 1e7
    lon_e7: int = 0           # degrees * 1e7
    alt_m: int = 0            # metres above ellipsoid
    h_acc_cm: int = 0         # horizontal accuracy estimate, centimetres
    gnss_status: int = 0      # same packing as Telemetry.gnss_status

    def pack(self) -> bytes:
        return self._S.pack(self.t_epoch, self.lat_e7, self.lon_e7,
                            self.alt_m, self.h_acc_cm, self.gnss_status)

    @classmethod
    def unpack(cls, b: bytes) -> "Position":
        if len(b) != cls._S.size:
            raise ProtocolError(f"position payload is {len(b)} B, expected {cls._S.size} B")
        return cls(*cls._S.unpack(b))

    @property
    def lat(self) -> float:
        return self.lat_e7 / 1e7

    @property
    def lon(self) -> float:
        return self.lon_e7 / 1e7

    @property
    def h_acc_m(self) -> float:
        return self.h_acc_cm / 100.0

    @property
    def gnss_fix(self) -> int:
        return self.gnss_status & 0x03

    @property
    def gnss_sats(self) -> int:
        return (self.gnss_status >> 2) & 0x3F

    @property
    def is_usable(self) -> bool:
        """A 2-D fix with no altitude is not good enough to place a node."""
        return self.gnss_fix >= GNSS_FIX_3D and self.h_acc_cm > 0


_DECODERS: dict[MsgType, type] = {
    MsgType.TELEMETRY: Telemetry,
    MsgType.EVENT: Event,
    MsgType.CONFIG_SET: Config,
    MsgType.CONFIG_ACK: ConfigAck,
    MsgType.NEIGHBOR: NeighborReport,
    MsgType.TIME_SYNC: TimeSync,
    MsgType.POSITION: Position,
}


def decode(frame: bytes) -> tuple[Header, Payload]:
    """Decode a complete over-the-air frame into (header, typed payload).

    Raises ProtocolError on anything malformed -- callers should log and drop,
    never crash the ingest loop on a corrupt radio frame.
    """
    header, raw = Header.unpack(frame)
    return header, _DECODERS[header.msg_type].unpack(raw)
