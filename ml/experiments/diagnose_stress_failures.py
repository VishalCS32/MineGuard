"""Diagnostic script to inspect false positives and false negatives from stress test."""

import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.stress_test_robustness import generate_domain_randomized_stream
from inference.pipeline import predict


def diagnose(seed: int = 42, steps: int = 100, low_prevalence: bool = False, run_name: str = "Seed 42"):
    records_by_time, ground_truth = generate_domain_randomized_stream(
        seed=seed, steps=steps, low_prevalence=low_prevalence
    )
    timestamps = sorted(records_by_time.keys())
    history_by_node = defaultdict(list)
    gt_map = {(ts, nid): (lbl, lname) for (ts, nid, lbl, lname) in ground_truth}

    fps = []
    fns = []
    tps = []
    tns = []

    for ts in timestamps:
        current_frame = records_by_time[ts]
        hist_snapshot = {nid: list(history_by_node[nid][-8:]) for nid in history_by_node}
        res = predict(current_frame, hist_snapshot)

        frame_nodes_map = {n["node_id"]: n for n in current_frame}

        for n_out in res["nodes"]:
            nid = n_out["node_id"]
            lbl, lname = gt_map[(ts, nid)]
            rec = frame_nodes_map[nid]

            is_confirmed = int(n_out["deformation"]["status"] == "CONFIRMED_PHYSICAL")
            sample_info = {
                "run": run_name,
                "timestamp": ts,
                "node_id": nid,
                "true_label": lbl,
                "true_name": lname,
                "pred_confirmed": is_confirmed,
                "pred_raw_anomaly": n_out["anomaly"]["detected"],
                "anomaly_score": n_out["anomaly"]["score"],
                "tilt": n_out["deformation"]["tilt_deg"],
                "rate": n_out["deformation"]["tilt_rate_deg_per_hour"],
                "vibration": rec.get("vibration_rms_mg", 0.0),
                "temperature": rec.get("temperature_c", 0.0),
                "battery": rec.get("battery_mv", 0.0),
                "rssi": rec.get("rssi_dbm", 0.0),
                "snr": rec.get("snr_db", 0.0),
                "history_len": len(hist_snapshot.get(nid, [])),
                "temporal_support": n_out["deformation"]["evidence"]["temporal"],
                "spatial_support": n_out["deformation"]["evidence"]["spatial"],
                "physics_support": n_out["deformation"]["evidence"]["physics"],
                "reason_codes": n_out["reason_codes"],
                "deformation_status": n_out["deformation"]["status"],
            }

            if lbl == 0 and is_confirmed == 1:
                fps.append(sample_info)
            elif lbl == 1 and lname == "physical_deformation" and is_confirmed == 0:
                fns.append(sample_info)
            elif lbl == 1 and lname == "physical_deformation" and is_confirmed == 1:
                tps.append(sample_info)
            elif lbl == 0 and is_confirmed == 0:
                tns.append(sample_info)

        for rec in current_frame:
            history_by_node[rec["node_id"]].append(rec)

    print(f"\n--- DIAGNOSTIC SUMMARY FOR {run_name} ---")
    print(f"Total: TP={len(tps)}, FP={len(fps)}, FN={len(fns)}, TN={len(tns)}")
    print(f"Precision: {len(tps) / (len(tps) + len(fps)):.4f}" if (len(tps) + len(fps)) > 0 else "N/A")
    print(f"Recall: {len(tps) / (len(tps) + len(fns)):.4f}" if (len(tps) + len(fns)) > 0 else "N/A")

    print("\nTop 15 False Positives:")
    print(f"{'TS':19} | {'NODE':8} | {'TILT':6} | {'RATE':7} | {'VIB':6} | {'TEMP':5} | {'SPAT':5} | {'TEMP_S':6} | {'ANOM_SC':7} | {'REASONS'}")
    for fp in fps[:15]:
        print(f"{fp['timestamp'][-14:-6]:19} | {fp['node_id']:8} | {fp['tilt']:6.3f} | {fp['rate']:7.4f} | {fp['vibration']:6.1f} | {fp['temperature']:5.1f} | {str(fp['spatial_support']):5} | {str(fp['temporal_support']):6} | {fp['anomaly_score']:7.3f} | {','.join(fp['reason_codes'])}")

    print("\nTop 10 False Negatives (Missed Physical Deformation):")
    for fn in fns[:10]:
        print(f"{fn['timestamp'][-14:-6]:19} | {fn['node_id']:8} | {fn['tilt']:6.3f} | {fn['rate']:7.4f} | {fn['vibration']:6.1f} | {fn['temperature']:5.1f} | {str(fn['spatial_support']):5} | {str(fn['temporal_support']):6} | {fn['anomaly_score']:7.3f} | {fn['deformation_status']} | {','.join(fn['reason_codes'])}")

    # Analysis of FP causes
    fp_tilt_over_12 = sum(1 for fp in fps if fp['tilt'] >= 0.12)
    fp_rate_over_015 = sum(1 for fp in fps if abs(fp['rate']) >= 0.015)
    fp_vib_over_30 = sum(1 for fp in fps if fp['vibration'] >= 30)
    fp_spatial = sum(1 for fp in fps if fp['spatial_support'])
    print("\nFP Breakdown:")
    print(f"  Total FPs: {len(fps)}")
    print(f"  FPs with tilt >= 0.12 deg: {fp_tilt_over_12} ({fp_tilt_over_12/len(fps)*100:.1f}%)" if fps else 0)
    print(f"  FPs with rate >= 0.015 deg/h: {fp_rate_over_015} ({fp_rate_over_015/len(fps)*100:.1f}%)" if fps else 0)
    print(f"  FPs with vibration >= 30 mg: {fp_vib_over_30} ({fp_vib_over_30/len(fps)*100:.1f}%)" if fps else 0)
    print(f"  FPs with spatial support: {fp_spatial} ({fp_spatial/len(fps)*100:.1f}%)" if fps else 0)

    # Nodes with most FPs
    fp_by_node = defaultdict(int)
    for fp in fps:
        fp_by_node[fp['node_id']] += 1
    print("  FPs by node:", dict(sorted(fp_by_node.items(), key=lambda x: -x[1])[:8]))

    # Analysis of FN causes
    print("\nFN Breakdown:")
    print(f"  Total FNs: {len(fns)}")
    for fn in fns:
        print(f"  Node {fn['node_id']} at tilt {fn['tilt']:.3f}, rate {fn['rate']:.4f}, status={fn['deformation_status']}, anom={fn['pred_raw_anomaly']} (score={fn['anomaly_score']:.3f})")

    return fps, fns


if __name__ == "__main__":
    print("=== DIAGNOSING SEED 42 ===")
    diagnose(seed=42, steps=100, low_prevalence=False, run_name="Seed 42")
    print("\n=== DIAGNOSING LOW PREVALENCE ===")
    diagnose(seed=2024, steps=120, low_prevalence=True, run_name="Low Prevalence")
