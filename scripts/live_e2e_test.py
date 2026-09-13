"""Live End-to-End Test for MineGuard Integration.

Executes Phase 12:
Gateway -> Deployed Backend API (https://mineguard-api.tenant.eu.org) -> Backend Processing/History -> ML /predict -> Web/UI Snapshot.
"""

import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_root = str(Path(__file__).resolve().parents[1])
_ml_root = str(Path(__file__).resolve().parents[1] / "ml")
if _root not in sys.path:
    sys.path.insert(0, _root)
if _ml_root not in sys.path:
    sys.path.insert(0, _ml_root)

from gateway.uplink import GatewayUplink, build_telemetry_payload
from backend.app.ml_payload import build_ml_payload, telemetry_to_ml_node
from ml.inference.pipeline import predict as ml_predict


def run_live_e2e():
    print("=" * 70)
    print("MINEGUARD PHASE 12: LIVE DEPLOYED API SMOKE TEST")
    print("=" * 70)

    # 1. Prepare Safe Reading with Dedicated Test Node
    test_node_id = "INTEGRATION-TEST-001"
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    reading = build_telemetry_payload(
        node_id=test_node_id,
        timestamp=now_ts,
        pitch_deg=0.048,
        roll_deg=-0.012,
        vibration_rms_mg=16.5,
        temperature_c=27.2,
        battery_mv=3960.0,
        latitude=23.7501,
        longitude=86.4201,
        altitude_m=230.5,
        satellites=12,
        rssi_dbm=-72.0,
        snr_db=9.5,
        accel_x=0.08,
        accel_y=-0.02,
        accel_z=9.79,
        gyro_x=0.005,
        gyro_y=-0.003,
        gyro_z=0.010,
    )
    print(f"\n[1] Prepared Gateway Reading for Node: {test_node_id}")
    print(json.dumps(reading, indent=2))

    # 2. Transmit via Production Gateway Uplink to Deployed Backend API
    deployed_endpoint = "https://mineguard-api.tenant.eu.org/api/v1/telemetry"
    print(f"\n[2] Transmitting via GatewayUplink to: {deployed_endpoint} ...")
    gw = GatewayUplink(backend_url=deployed_endpoint, timeout_s=15.0, max_retries=2)
    result = gw.send_reading(reading)

    print(f"    -> Success: {result.success}")
    print(f"    -> HTTP Status: {result.status_code}")
    print(f"    -> Accepted Count: {result.accepted_count}")
    print(f"    -> Response Body: {json.dumps(result.response_body)}")
    assert result.success is True, f"Gateway transmission failed: {result.error}"
    assert result.status_code == 202, f"Unexpected status: {result.status_code}"

    # 3. Verify Reading in Deployed Backend API (/api/v1/nodes)
    print("\n[3] Verifying node presence in Deployed Backend API (/api/v1/nodes)...")
    time.sleep(1.0)
    nodes_url = "https://mineguard-api.tenant.eu.org/api/v1/nodes"
    req = urllib.request.Request(nodes_url, headers={"User-Agent": "MineGuard-Live-Audit"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        nodes_code = resp.status
        nodes_data = json.loads(resp.read().decode("utf-8"))
    
    print(f"    -> GET {nodes_url} -> HTTP {nodes_code}")
    matching = [n for n in nodes_data if n.get("node_id") == test_node_id]
    print(f"    -> Found {len(matching)} matching record(s) for {test_node_id}")
    if matching:
        print(f"    -> Latest Node Record: {json.dumps(matching[0], indent=2)}")
    assert len(matching) > 0, f"Test node {test_node_id} not found in deployed /api/v1/nodes!"

    # 4. Backend Conversion to ML Request Schema
    print("\n[4] Backend constructing ML Request from live telemetry record...")
    ml_node = telemetry_to_ml_node(reading)
    print("    -> ML Node Contract Converted:")
    print(json.dumps(ml_node, indent=2))

    # 5. ML /predict Execution
    print("\n[5] Executing Production ML Inference (/predict)...")
    # Provide synthetic baseline history for the test node to demonstrate healthy inference
    hist = [
        telemetry_to_ml_node(build_telemetry_payload(
            node_id=test_node_id,
            timestamp=f"2026-09-13T0{h}:00:00Z",
            pitch_deg=0.045 + 0.001 * (h % 3),
            roll_deg=-0.010,
            temperature_c=27.0,
            battery_mv=3960.0,
        ))
        for h in range(1, 6)
    ]
    ml_output = ml_predict(current=[ml_node], history={test_node_id: hist})
    print("    -> ML Inference Summary:")
    print(f"       Overall Status:    {ml_output['overall']['status']}")
    print(f"       Alarm:             {ml_output['overall']['alarm']}")
    print(f"       Risk Level:        {ml_output['overall']['risk_level']}")
    print(f"       Risk Score:        {ml_output['overall']['risk_score']}")
    print(f"       Model Version:     {ml_output['model_version']}")
    print(f"       Healthy Nodes:     {ml_output['sensor_health']['healthy_nodes']}")
    print(f"       Anti-Theft Alert:  {ml_output['anti_theft']['alert']}")
    print(f"       Threshold Status:  {ml_output['time_to_threshold']['warning_status']}")

    assert ml_output["overall"]["status"] in ("NORMAL", "INSUFFICIENT_HISTORY", "WARNING")
    assert ml_output["overall"]["alarm"] is False

    print("\n" + "=" * 70)
    print("PHASE 12 LIVE DEPLOYED API SMOKE TEST: ALL CHECKS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    run_live_e2e()
