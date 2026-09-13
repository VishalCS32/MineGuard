"""Pull live MineGuard telemetry from the gateway's receiver API.

The field gateway pushes decoded readings to a small HTTP service (see
`services/telemetry-api` in the firmware repo). This module reads them back
and hands them to the ML pipeline in the shape `NodeTelemetry.from_mapping`
already accepts, so nothing downstream has to know where the data came from.

    from data.api_client import TelemetryAPI
    from inference.pipeline import predict

    api = TelemetryAPI("https://mineguard-api.tenant.eu.org")
    current, history = api.predict_inputs(history_limit=200)
    result = predict(current, history)

THREE FIELDS DO NOT LINE UP, and silently getting any of them wrong would
produce confident nonsense rather than an error:

  vibration   The API carries RMS in m/s^2; this pipeline wants milli-g.
              Passing one as the other is a factor of ~9.8 -- comfortably
              enough to turn ordinary noise into an alarm, in the direction
              that cries wolf.

  timestamp   The API calls it `ts`, and also carries `received_at`. `ts` is
              the node's own clock and is the one to use: `received_at` is
              when the gateway's backhaul happened to recover, which on a
              spooled batch can be hours later and would compress a day of
              readings into one minute.

  peak_hz     Never measured. A dominant frequency needs an FFT over a
              uniformly sampled window and the node takes a duty-cycled
              burst, so the firmware reports nothing rather than inventing a
              number. The pipeline requires the field, so it is supplied as
              0.0 -- meaning "not measured", not "no vibration".
"""

from __future__ import annotations

from typing import Any, Iterator, Mapping, Sequence

import httpx

# 1 g = 9.80665 m/s^2, matching data.telemetry.STANDARD_GRAVITY.
STANDARD_GRAVITY = 9.80665

#: Straight renames -- API column on the left, what the parser looks for on
#: the right. Everything not listed here either matches already or needs the
#: conversion handled in `to_record`.
_RENAME = {
    "vib_x": "vib_x", "vib_y": "vib_y", "vib_z": "vib_z",
}


def to_record(row: Mapping[str, Any]) -> dict[str, Any]:
    """One API row as a mapping `NodeTelemetry.from_mapping` will accept."""
    rms_mps2 = row.get("vib_rms")
    rms_mg = (float(rms_mps2) / STANDARD_GRAVITY * 1000.0
              if rms_mps2 is not None else 0.0)

    record: dict[str, Any] = {
        "node_id": row["node_id"],
        "timestamp": row["ts"],
        "pitch_deg": row.get("pitch_deg") or 0.0,
        "roll_deg": row.get("roll_deg") or 0.0,
        "vibration_rms_mg": rms_mg,
        "vibration_peak_hz": 0.0,       # not measured -- see module docstring
    }

    # Optional fields are passed through only when present. The parser treats
    # a missing key and an explicit None differently in places, and a node
    # with no GNSS should look like a node with no GNSS rather than one
    # reporting the Atlantic.
    for src, dst in (("temperature_c", "temperature_c"),
                     ("battery_mv", "battery_mv"),
                     ("rssi_dbm", "rssi_dbm"),
                     ("snr_db", "snr_db"),
                     ("latitude", "latitude"),
                     ("longitude", "longitude"),
                     ("altitude", "altitude_m"),
                     ("accel_x", "accel_x"),
                     ("accel_y", "accel_y"),
                     ("accel_z", "accel_z"),
                     ("gyro_x", "gyro_x"),
                     ("gyro_y", "gyro_y"),
                     ("gyro_z", "gyro_z")):
        if row.get(src) is not None:
            record[dst] = row[src]

    if row.get("flags") is not None:
        record["flags"] = int(row["flags"])
    return record


class TelemetryAPI:
    """Read-only client for the telemetry receiver."""

    def __init__(self, base_url: str, token: str | None = None,
                 timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        # httpx sends its own User-Agent, which matters: a bare urllib
        # request is rejected outright by the CDN in front of the API.
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout,
                                    headers=headers, follow_redirects=True)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "TelemetryAPI":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------- raw reads
    def health(self) -> dict[str, Any]:
        return self._client.get("/health").raise_for_status().json()

    def nodes(self) -> list[dict[str, Any]]:
        """Every node, with its most recent reading."""
        return self._client.get("/api/v1/nodes").raise_for_status().json()

    def latest(self, node_id: str) -> dict[str, Any]:
        return self._client.get(
            f"/api/v1/nodes/{node_id}/latest").raise_for_status().json()

    def readings(self, node_id: str | None = None, since_id: int = 0,
                 limit: int = 1000) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"since_id": since_id, "limit": limit}
        if node_id:
            params["node_id"] = node_id
        return self._client.get("/api/v1/readings",
                                params=params).raise_for_status().json()

    # --------------------------------------------------------- ML-shaped reads
    def predict_inputs(self, node_ids: Sequence[str] | None = None,
                       history_limit: int = 200
                       ) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        """`(current, history)` ready for `inference.pipeline.predict`.

        `current` is each node's latest reading; `history` is what came
        before it, oldest first, which is what the baseline and rate
        calculations expect.
        """
        latest_rows = self.nodes()
        if node_ids is not None:
            wanted = set(node_ids)
            latest_rows = [r for r in latest_rows if r["node_id"] in wanted]

        current = [to_record(r) for r in latest_rows]
        history: dict[str, list[dict[str, Any]]] = {}
        for row in latest_rows:
            nid = row["node_id"]
            rows = self.readings(node_id=nid, limit=history_limit)
            # Drop the reading that is already in `current`: counting it in
            # both would let the newest sample vote twice in its own baseline.
            history[nid] = [to_record(r) for r in rows if r["id"] != row["id"]]
        return current, history

    def stream(self, since_id: int = 0, limit: int = 1000
               ) -> Iterator[tuple[int, list[dict[str, Any]]]]:
        """Yield `(cursor, records)` batches, newest after `since_id`.

        Paged by row id rather than time on purpose: paging by timestamp
        repeats or skips rows whenever two readings share a second, and at a
        five-second interval across a field of nodes they do.
        """
        cursor = since_id
        while True:
            rows = self.readings(since_id=cursor, limit=limit)
            if not rows:
                return
            cursor = rows[-1]["id"]
            yield cursor, [to_record(r) for r in rows]


if __name__ == "__main__":
    import json
    import sys

    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8020"
    with TelemetryAPI(url) as api:
        print("health:", json.dumps(api.health()))
        current, history = api.predict_inputs(history_limit=50)
        print(f"{len(current)} node(s) current, "
              f"{sum(len(v) for v in history.values())} historical readings")
        for rec in current:
            print(" ", json.dumps(rec))
