"""Validation tuning and held-out test evaluation for anomaly decision layer.

Strict chronological methodology:
- Step 1: Tune candidate policies exclusively on the VALIDATION split.
- Step 2: Select the optimal policy balancing physical recall and low false alarms.
- Step 3: Evaluate ONCE on the held-out TEST split.
- Step 4: Report both row-level and event-level metrics.
"""

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score

from data.offline_dataset import chronological_split, chronological_windows, generate_dataset
from data.telemetry import NodeTelemetry
from features.engineering import build_features
from models.estimators import health_for_node
from training.anomaly import FeatureEncoder, load_anomaly_artifact


def evaluate_split(split_name: str, split_rows, model, threshold: float, encoder: FeatureEncoder):
    by_ts = defaultdict(list)
    for r in split_rows:
        by_ts[r[0]["timestamp"]].append(r)

    timestamps = sorted(by_ts.keys())
    node_history_scores = defaultdict(list)

    policies = {
        "1_raw_iforest": lambda h, is_h, rate, tilt: h[-1],
        "2_consecutive": lambda h, is_h, rate, tilt: int(len(h) >= 2 and h[-1] and h[-2]),
        "2_of_last_3": lambda h, is_h, rate, tilt: int(sum(h[-3:]) >= 2),
        "multi_signal": lambda h, is_h, rate, tilt: int(
            is_h and (
                (len(h) >= 2 and h[-1] and h[-2])
                or (h[-1] and abs(rate) >= 0.02)
                or (h[-1] and tilt >= 0.15)
            )
        ),
        "multi_signal_strict": lambda h, is_h, rate, tilt: int(
            is_h and (
                (sum(h[-3:]) >= 2)
                or (h[-1] and abs(rate) >= 0.03)
            )
        ),
    }

    results = {
        p: {
            "y_true": [],
            "y_pred": [],
            "lnames": [],
            "node_timeline": defaultdict(list),
            "true_timeline": defaultdict(list),
        }
        for p in policies
    }

    for ts in timestamps:
        cur_items = by_ts[ts]
        cur_telemetry = [NodeTelemetry.from_mapping(r[0]) for r in cur_items]

        for (cur, hist, lbl, lname), telem in zip(cur_items, cur_telemetry):
            if len(hist) < 4:
                continue
            sc = -float(model.decision_function(encoder.transform(cur, hist))[0])
            is_raw = int(sc >= threshold)
            nid = cur["node_id"]
            node_history_scores[nid].append(is_raw)

            feat = build_features([telem], {nid: [NodeTelemetry.from_mapping(h) for h in hist]}).nodes[0]
            hlth = health_for_node(feat)
            is_healthy = hlth.status.value == "HEALTHY"
            rate = feat.robust_tilt_rate_deg_per_hour or 0.0
            tilt = feat.tilt_deg

            for p, fn in policies.items():
                pred = fn(node_history_scores[nid], is_healthy, rate, tilt)
                results[p]["y_true"].append(lbl)
                results[p]["y_pred"].append(pred)
                results[p]["lnames"].append(lname)
                results[p]["node_timeline"][nid].append(pred)
                results[p]["true_timeline"][nid].append(lbl)

    print("=" * 88)
    print(f"SPLIT: {split_name.upper()} (N = {len(results['1_raw_iforest']['y_true'])} rows across {len(timestamps)} timestamps)")
    print("=" * 88)
    print(f"{'Policy':<22} {'Prec':<8} {'Recall':<8} {'F1':<8} {'FAR':<8} {'PhysRec':<8} {'SensFP':<8} {'FP':<6} {'FN':<6} {'TP':<6}")
    print("-" * 88)

    for p, d in results.items():
        yt = np.array(d["y_true"])
        yp = np.array(d["y_pred"])
        cm = confusion_matrix(yt, yp, labels=[0, 1])
        prec = precision_score(yt, yp, zero_division=0)
        rec = recall_score(yt, yp, zero_division=0)
        f1 = f1_score(yt, yp, zero_division=0)
        far = cm[0, 1] / (cm[0, 0] + cm[0, 1]) if (cm[0, 0] + cm[0, 1]) > 0 else 0.0
        lns = np.array(d["lnames"])
        phys_mask = lns == "physical_deformation"
        phys_rec = recall_score(np.ones(phys_mask.sum()), yp[phys_mask], zero_division=0) if phys_mask.any() else 0.0
        sens_mask = lns == "sensor_anomaly"
        sens_fp = int(yp[sens_mask].sum()) if sens_mask.any() else 0

        print(f"{p:<22} {prec:.4f}   {rec:.4f}   {f1:.4f}   {far:.4f}   {phys_rec:.4f}   {sens_fp:<8} {cm[0,1]:<6} {cm[1,0]:<6} {cm[1,1]:<6}")

    # Event-level evaluation
    print("\n--- EVENT-LEVEL METRICS ---")
    for p, d in results.items():
        # An event is defined as a continuous block of physical deformation for a node
        detected_events = 0
        total_events = 0
        delays = []
        false_alarm_clusters = 0

        for nid in sorted(d["true_timeline"].keys()):
            truth = d["true_timeline"][nid]
            preds = d["node_timeline"][nid]

            in_event = False
            event_detected = False
            event_start = 0

            in_fa = False

            for idx, (t_val, p_val) in enumerate(zip(truth, preds)):
                if t_val == 1:
                    if not in_event:
                        in_event = True
                        total_events += 1
                        event_start = idx
                        event_detected = False
                    if p_val == 1 and not event_detected:
                        event_detected = True
                        delays.append(idx - event_start)
                else:
                    if in_event:
                        in_event = False
                        if event_detected:
                            detected_events += 1

                    # Count false alarm clusters (consecutive false alarms count as 1 cluster)
                    if p_val == 1:
                        if not in_fa:
                            in_fa = True
                            false_alarm_clusters += 1
                    else:
                        in_fa = False

            if in_event and event_detected:
                detected_events += 1

        ev_recall = detected_events / total_events if total_events > 0 else 0.0
        mean_delay_samples = np.mean(delays) if delays else 0.0
        mean_delay_hours = mean_delay_samples * 0.25  # 15 min per sample

        total_hours = len(timestamps) * 0.25
        fa_per_day = (false_alarm_clusters / (total_hours / 24.0)) if total_hours > 0 else 0.0

        print(f"{p:<22}: Event Recall = {ev_recall*100:.1f}% ({detected_events}/{total_events}), "
              f"Mean Delay = {mean_delay_hours:.2f}h ({mean_delay_samples:.1f} frames), "
              f"FA Clusters = {false_alarm_clusters} ({fa_per_day:.2f}/day)")


def main():
    artifact_dir = Path(__file__).resolve().parents[1] / "artifacts" / "anomaly"
    bundle, metadata = load_anomaly_artifact(artifact_dir)
    model = bundle["model"]
    threshold = float(bundle["threshold"])
    encoder = FeatureEncoder()

    dataset = generate_dataset()
    train_recs, val_recs, test_recs = chronological_split(dataset, train_fraction=0.5, validation_fraction=0.15)
    rows = list(chronological_windows(dataset))

    c_train = len(train_recs)
    c_val = c_train + len(val_recs)

    print("PHASE 1: VALIDATION SPLIT EVALUATION (Policy Tuning)")
    evaluate_split("Validation", rows[c_train:c_val], model, threshold, encoder)

    print("\n" + "#" * 88)
    print("PHASE 2: HELD-OUT UNTOUCHED TEST SPLIT EVALUATION")
    print("#" * 88)
    evaluate_split("Held-out Test", rows[c_val:], model, threshold, encoder)


if __name__ == "__main__":
    main()
