"""SUBSIDENCE-NET mesh wire protocol.

Shared deliberately: the backend decodes these frames and the simulator encodes
them, and if the two ever drift apart the whole system lies about what the field
is doing. One codec, one set of conformance tests, imported by both.

The C side of the same contract lives in ``firmware/common/mesh_proto.h`` and is
checked byte-for-byte against this module by ``tests/test_proto.py``.
"""

from .proto import (  # noqa: F401
    ADDR_BROADCAST, ADDR_GATEWAY, ADDR_UNASSIGNED,
    CFG_DEEP_SLEEP, CFG_GNSS_ENABLED, CFG_RECALIBRATE, CFG_RELAY_ENABLED, CFG_VIB_ENABLED,
    DEFAULT_TTL, GNSS_FIX_2D, GNSS_FIX_3D, GNSS_FIX_DGPS, GNSS_NO_FIX,
    HDR_LEN, MAGIC, MAX_NEIGHBORS, MAX_PAYLOAD, PROTO_VER,
    TLM_GNSS_FAULT, TLM_LOW_BATTERY, TLM_RELAYED, TLM_TILT_FAULT, TLM_UNCALIBRATED,
    TLM_VIB_FAULT,
    CfgStatus, Config, ConfigAck, Event, EventCode, Header, MsgType, Neighbor,
    NeighborReport, Payload, Position, ProtocolError, Severity, Telemetry,
    TimeSync,
    crc16, decode, pack_gnss_status,
)

__version__ = "1.0.0"
