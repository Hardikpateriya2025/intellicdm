from pathlib import Path
import json

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    precision_score,
    recall_score,
    f1_score,
)

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
ARTIFACTS = ROOT / "artifacts"
DATA.mkdir(exist_ok=True)
ARTIFACTS.mkdir(exist_ok=True)

FEATURES = [
    "glucose_mg_dl",
    "creatinine_mg_dl",
    "urea_mg_dl",
    "hemoglobin_g_dl",
    "wbc_10e9_l",
    "platelets_10e9_l",
]


def generate_dataset(n, seed, anomaly_fraction=0.0):
    rng = np.random.default_rng(seed)

    # Invented latent factors create relationships between measurements.
    # These distributions are for software demonstration only.
    factors = rng.normal(size=(n, 3))
    noise = rng.normal(size=(n, 6))

    centers = np.array([95, 0.9, 28, 14, 7, 250])
    spreads = np.array([0.16, 0.20, 0.23, 0.08, 0.22, 0.18])

    patterns = np.column_stack([
        0.6 * factors[:, 0] + 0.8 * noise[:, 0],
        0.8 * factors[:, 1] + 0.6 * noise[:, 1],
        0.8 * factors[:, 1] + 0.6 * noise[:, 2],
        0.5 * factors[:, 2] + 0.87 * noise[:, 3],
        0.4 * factors[:, 0] + 0.92 * noise[:, 4],
        0.5 * factors[:, 2] + 0.87 * noise[:, 5],
    ])

    values = centers * np.exp(patterns * spreads)
    labels = np.zeros(n, dtype=int)
    kinds = np.full(n, "baseline", dtype=object)

    count = int(n * anomaly_fraction)
    selected = rng.choice(n, size=count, replace=False)

    for position, row in enumerate(selected):
        labels[row] = 1

        if position % 2 == 0:
            # Shift one or two measurements by varying amounts.
            columns = rng.choice(6, size=int(rng.integers(1, 3)),
                                 replace=False)
            direction = rng.choice([-1, 1], size=len(columns))
            magnitude = rng.uniform(2.5, 5.0, size=len(columns))
            values[row, columns] *= np.exp(
                direction * magnitude * spreads[columns]
            )
            kinds[row] = "measurement_shift"
        else:
            # Break the invented relationship between two measurements.
            magnitude = rng.uniform(1.8, 3.5)
            values[row, 1] *= np.exp(magnitude * spreads[1])
            values[row, 2] *= np.exp(-magnitude * spreads[2])
            kinds[row] = "relationship_shift"

    frame = pd.DataFrame(values, columns=FEATURES).round(4)
    frame.insert(0, "synthetic_record_id",
                 [f"DEMO-{seed}-{i:06d}" for i in range(n)])
    frame["is_injected_anomaly"] = labels
    frame["injection_type"] = kinds

    assert np.isfinite(frame[FEATURES].to_numpy()).all()
    assert (frame[FEATURES] > 0).all().all()
    assert frame["synthetic_record_id"].is_unique
    return frame


# Independent synthetic records in each split.
train = generate_dataset(10000, seed=42)
validation = generate_dataset(3000, seed=43, anomaly_fraction=0.10)
test = generate_dataset(3000, seed=44, anomaly_fraction=0.10)

for name, frame in [
    ("train", train),
    ("validation", validation),
    ("test", test),
]:
    frame.to_csv(DATA / f"{name}.csv", index=False)
    print(f"Saved {name}.csv: {len(frame):,} rows")

# IDs and evaluation labels are NEVER used as training features.
model = IsolationForest(
    n_estimators=300,
    max_samples=256,
    contamination="auto",
    random_state=42,
    n_jobs=-1,
)
model.fit(train[FEATURES])

# Negate score_samples so larger scores mean more unusual.
validation_scores = -model.score_samples(validation[FEATURES])
validation_labels = validation["is_injected_anomaly"].to_numpy()

# Select threshold using validation only. Test remains untouched.
thresholds = np.unique(
    np.quantile(validation_scores, np.linspace(0.50, 0.995, 200))
)
validation_f1 = [
    f1_score(validation_labels, validation_scores >= threshold,
             zero_division=0)
    for threshold in thresholds
]
threshold = float(thresholds[int(np.argmax(validation_f1))])

test_scores = -model.score_samples(test[FEATURES])
test_predictions = (test_scores >= threshold).astype(int)
test_labels = test["is_injected_anomaly"].to_numpy()

metrics = {
    "scope": "Synthetic demonstration only; not clinical validation",
    "train_rows": len(train),
    "validation_rows": len(validation),
    "test_rows": len(test),
    "threshold": threshold,
    "test_precision": float(
        precision_score(test_labels, test_predictions, zero_division=0)
    ),
    "test_recall": float(
        recall_score(test_labels, test_predictions, zero_division=0)
    ),
    "test_f1": float(
        f1_score(test_labels, test_predictions, zero_division=0)
    ),
    "test_average_precision": float(
        average_precision_score(test_labels, test_scores)
    ),
    "confusion_matrix": confusion_matrix(
        test_labels, test_predictions, labels=[0, 1]
    ).tolist(),
}

joblib.dump(
    {
        "model": model,
        "features": FEATURES,
        "threshold": threshold,
        "score_convention": "negative_score_samples",
        "version": "synthetic-demo-v1",
        "scope": metrics["scope"],
    },
    ARTIFACTS / "isolation_forest_demo.joblib",
)

(ARTIFACTS / "metrics.json").write_text(json.dumps(metrics, indent=2))

test_output = test.copy()
test_output["anomaly_score"] = test_scores
test_output["predicted_anomaly"] = test_predictions
test_output.to_csv(DATA / "test_predictions.csv", index=False)

print("\nHeld-out synthetic test results:")
print(json.dumps(metrics, indent=2))
print("\nModel saved:", ARTIFACTS / "isolation_forest_demo.joblib")
