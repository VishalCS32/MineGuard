from collections import defaultdict
from math import sqrt
from statistics import mean

from data.offline_dataset import generate_dataset
from inference.pipeline import predict


# Dataset cadence:
# 15 minutes per sample.
#
# Therefore:
# 1 hour  = 4 samples
# 6 hours = 24 samples
# 12 hours = 48 samples
# 24 hours = 96 samples
HORIZONS = {
    1: 4,
    6: 24,
    12: 48,
    24: 96,
}


def calculate_rmse(errors):
    """Calculate RMSE from signed errors."""
    if not errors:
        return None

    return sqrt(mean(error * error for error in errors))


def record_to_dict(item):
    """
    Convert an OfflineDataset record object into the raw telemetry
    dictionary expected by the production inference pipeline.
    """
    return dict(item.record)


def main():
    print("=" * 72)
    print("MineGuard Forecast Evaluation")
    print("=" * 72)

    # ==================================================================
    # 1. LOAD OFFLINE DATASET
    # ==================================================================

    dataset = generate_dataset()

    print("\nDATASET")
    print("-" * 72)

    print(f"Total records : {len(dataset.records)}")

    # Convert dataset entries into ordinary dictionaries.
    records = [
        record_to_dict(item)
        for item in dataset.records
    ]

    # ==================================================================
    # 2. GROUP BY TIMESTAMP AND NODE
    # ==================================================================

    by_timestamp = defaultdict(dict)
    by_node = defaultdict(list)

    for record in records:
        timestamp = record["timestamp"]
        node_id = str(record["node_id"])

        by_timestamp[timestamp][node_id] = record
        by_node[node_id].append(record)

    timestamps = sorted(by_timestamp.keys())

    node_ids = sorted(by_node.keys())

    print(f"Nodes         : {len(node_ids)}")
    print(f"Start         : {timestamps[0]}")
    print(f"End           : {timestamps[-1]}")

    print(f"\nGrouped nodes : {len(node_ids)}")

    # Make sure every node is chronological.
    for node_id in node_ids:
        by_node[node_id].sort(
            key=lambda record: record["timestamp"]
        )

    # ==================================================================
    # 3. CREATE INDEXES
    # ==================================================================

    timestamp_index = {
        timestamp: index
        for index, timestamp in enumerate(timestamps)
    }

    # ==================================================================
    # 4. RESULT STORAGE
    # ==================================================================

    results = {
        horizon: {
            "mg_errors": [],
            "persistence_errors": [],
        }
        for horizon in HORIZONS
    }

    diagnostics = {
        horizon: {
            "possible": 0,
            "history_ok": 0,
            "forecast_ok": 0,
            "future_found": 0,
        }
        for horizon in HORIZONS
    }

    # ================================================    # ==================================================================
    # 5. EVALUATE EACH TIME STEP
    # ==================================================================

    for current_index, current_timestamp in enumerate(timestamps):

        # --------------------------------------------------------------
        # Build the complete current 21-node field ONCE.
        # --------------------------------------------------------------

        current_field = by_timestamp[current_timestamp]

        if len(current_field) != len(node_ids):
            continue

        current_nodes = [
            current_field[node_id]
            for node_id in node_ids
        ]

        # --------------------------------------------------------------
        # Build historical data for every node.
        # Current observation is intentionally excluded.
        # --------------------------------------------------------------

        history = {}

        for node_id in node_ids:

            node_history = [
                record
                for record in by_node[node_id]
                if record["timestamp"] < current_timestamp
            ]

            history[node_id] = node_history

        # --------------------------------------------------------------
        # MineGuard requires at least 4 prior observations.
        # --------------------------------------------------------------

        min_history = min(
            (
                len(history[node_id])
                for node_id in node_ids
            ),
            default=0,
        )

        if min_history < 4:
            continue

        # --------------------------------------------------------------
        # RUN PRODUCTION ML ONCE
        #
        # One prediction contains all forecast horizons.
        # --------------------------------------------------------------

        try:
            result = predict(
                current_nodes,
                history,
            )
        except Exception as exc:
            print(
                f"\nPrediction failed at "
                f"{current_timestamp}: {exc}"
            )
            continue

        forecast_data = result.get("forecast")

        if not forecast_data:
            continue

        # --------------------------------------------------------------
        # Evaluate all horizons from this ONE prediction.
        # --------------------------------------------------------------

        for horizon, offset in HORIZONS.items():

            future_index = current_index + offset

            if future_index >= len(timestamps):
                continue

            diagnostics[horizon]["possible"] += 1
            diagnostics[horizon]["history_ok"] += 1

            future_timestamp = timestamps[future_index]
            future_field = by_timestamp[future_timestamp]

            if len(future_field) != len(node_ids):
                continue

            # ----------------------------------------------------------
            # Extract forecast for this horizon.
            # ----------------------------------------------------------

            horizon_result = forecast_data.get(str(horizon))

            if not horizon_result:
                continue

            predicted = horizon_result.get("tilt_deg")

            if predicted is None:
                continue

            diagnostics[horizon]["forecast_ok"] += 1

            # ----------------------------------------------------------
            # Actual future maximum tilt magnitude across all nodes.
            # Physical quantity matches predicted tilt_deg = hypot(pitch, roll).
            # ----------------------------------------------------------

            from math import hypot

            future_tilts = [
                hypot(
                    float(future_field[node_id]["pitch_deg"]),
                    float(future_field[node_id].get("roll_deg", 0.0)),
                )
                for node_id in node_ids
            ]

            actual = max(future_tilts)

            # ----------------------------------------------------------
            # Persistence baseline.
            # Current maximum tilt magnitude remains unchanged.
            # ----------------------------------------------------------

            current_tilts = [
                hypot(
                    float(current_field[node_id]["pitch_deg"]),
                    float(current_field[node_id].get("roll_deg", 0.0)),
                )
                for node_id in node_ids
            ]

            persistence = max(current_tilts)

            diagnostics[horizon]["future_found"] += 1

            # ----------------------------------------------------------
            # Store signed errors.
            # ----------------------------------------------------------

            results[horizon]["mg_errors"].append(
                float(predicted) - actual
            )

            results[horizon]["persistence_errors"].append(
                persistence - actual
            )

        # --------------------------------------------------------------
        # Progress indicator so it doesn't look frozen.
        # --------------------------------------------------------------

        if current_index % 10 == 0:
            print(
                f"Evaluated timestamp "
                f"{current_index + 1}/{len(timestamps)} "
                f"({current_timestamp})"
            )

    # ==================================================================
    # 6. PRINT RESULTS
    # ==================================================================

    print("\n" + "=" * 72)
    print("FORECAST RESULTS")
    print("=" * 72)

    print(
        f"{'Horizon':<10}"
        f"{'Samples':<12}"
        f"{'MG MAE':<16}"
        f"{'Persistence MAE':<20}"
        f"{'MG RMSE':<16}"
        f"{'Persistence RMSE':<20}"
    )

    print("-" * 72)

    for horizon in HORIZONS:

        mg_errors = results[horizon]["mg_errors"]
        persistence_errors = results[horizon]["persistence_errors"]

        if not mg_errors:
            print(
                f"{horizon:<10}"
                f"{0:<12}"
                f"{'NO DATA':<16}"
            )
            continue

        mg_mae = mean(abs(error) for error in mg_errors)
        persistence_mae = mean(
            abs(error)
            for error in persistence_errors
        )

        mg_rmse = calculate_rmse(mg_errors)
        persistence_rmse = calculate_rmse(
            persistence_errors
        )

        print(
            f"{horizon:<10}"
            f"{len(mg_errors):<12}"
            f"{mg_mae:<16.6f}"
            f"{persistence_mae:<20.6f}"
            f"{mg_rmse:<16.6f}"
            f"{persistence_rmse:<20.6f}"
        )

    # ==================================================================
    # 7. DIAGNOSTICS
    # ==================================================================

    print("\n" + "=" * 72)
    print("DIAGNOSTICS")
    print("=" * 72)

    for horizon in HORIZONS:

        d = diagnostics[horizon]

        print(
            f"{horizon:>2}h : "
            f"possible={d['possible']} | "
            f"history_ok={d['history_ok']} | "
            f"forecast_ok={d['forecast_ok']} | "
            f"future_found={d['future_found']}"
        )

    # ==================================================================
    # 8. VERDICT
    # ==================================================================

    print("\n" + "=" * 72)
    print("VERDICT")
    print("=" * 72)

    for horizon in HORIZONS:

        mg_errors = results[horizon]["mg_errors"]
        persistence_errors = results[horizon]["persistence_errors"]

        if not mg_errors:
            print(f"{horizon:>2}h : NO VALID SAMPLES")
            continue

        mg_mae = mean(abs(error) for error in mg_errors)
        persistence_mae = mean(
            abs(error)
            for error in persistence_errors
        )

        if mg_mae < persistence_mae:
            verdict = "BETTER THAN PERSISTENCE"
        elif mg_mae > persistence_mae:
            verdict = "WORSE THAN PERSISTENCE"
        else:
            verdict = "EQUAL TO PERSISTENCE"

        if persistence_mae > 0:
            improvement = (
                (persistence_mae - mg_mae)
                / persistence_mae
                * 100
            )
        else:
            improvement = 0.0

        print(
            f"{horizon:>2}h : "
            f"{verdict} | "
            f"MG MAE={mg_mae:.6f} | "
            f"Persistence MAE={persistence_mae:.6f} | "
            f"Difference={improvement:+.2f}%"
        )

    print("\nOffline evaluation only.")
    print("Production ML code was not modified.")


if __name__ == "__main__":
    main()