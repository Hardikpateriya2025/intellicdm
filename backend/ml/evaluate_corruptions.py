from pathlib import Path
import json

import joblib
import numpy as np
import pandas as pd
import torch
from torch import nn

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data/synthea_prepared_v1"
ART = ROOT / "artifacts/synthea_autoencoder_v1"
OUT = ART / "corruption_evaluation"
OUT.mkdir(parents=True, exist_ok=True)

config = json.loads((ART / "config.json").read_text())
features = config["features"]
widths = config["architecture"]

scaler = joblib.load(ART / "scaler.joblib")
baseline = joblib.load(ART / "isolation_forest.joblib")

# Rebuild exactly the architecture used during training.
layers = []
for i in range(len(widths) - 1):
    layers.append(nn.Linear(widths[i], widths[i + 1]))
    if i < len(widths) - 2:
        layers.append(nn.ReLU())

model = nn.Sequential(*layers)
model.load_state_dict(torch.load(
    ART / "autoencoder_weights.pt",
    map_location="cpu",
    weights_only=True,
))
model.eval()

test = pd.read_csv(DATA / "test.csv")
original = test[features].to_numpy(dtype=np.float64)
patients = test["PATIENT"].to_numpy()

rng = np.random.default_rng(2026)
n, feature_count = original.shape
rows = np.arange(n)

# Change the same selected feature in each paired scenario.
selected_columns = rng.integers(0, feature_count, size=n)

times_ten = original.copy()
times_ten[rows, selected_columns] *= 10

divided_by_ten = original.copy()
divided_by_ten[rows, selected_columns] /= 10

# Choose donors from other patients in the held-out test split.
donors = np.empty(n, dtype=int)
for i in range(n):
    candidates = np.flatnonzero(patients != patients[i])
    donors[i] = rng.choice(candidates)

donor_replacement = original.copy()
donor_replacement[rows, selected_columns] = original[
    donors, selected_columns
]

scenarios = {
    "multiply_by_10": times_ten,
    "divide_by_10": divided_by_ten,
    "other_patient_value": donor_replacement,
}

thresholds = {
    "autoencoder": config["autoencoder_threshold"],
    "isolation_forest": config["isolation_forest_threshold"],
}


def score(values):
    frame = pd.DataFrame(values, columns=features)
    scaled = scaler.transform(frame).astype("float32")

    with torch.no_grad():
        tensor = torch.from_numpy(scaled)
        reconstructed = model(tensor)
        ae = ((reconstructed - tensor) ** 2).mean(dim=1).numpy()

    forest = -baseline.score_samples(scaled)
    return {"autoencoder": ae, "isolation_forest": forest}


original_scores = score(original)
summary = []
details = []

for name, scores in original_scores.items():
    flag_rate = float((scores >= thresholds[name]).mean())
    print(f"Original test flag rate — {name}: {flag_rate:.2%}")

for scenario, modified in scenarios.items():
    modified_scores = score(modified)

    # A replacement may equal the original value; exclude no-op edits.
    changed = modified[rows, selected_columns] != original[
        rows, selected_columns
    ]

    for model_name, scores in modified_scores.items():
        threshold = thresholds[model_name]
        original_flag = original_scores[model_name] >= threshold
        modified_flag = scores >= threshold

        eligible = changed & ~original_flag

        summary.append({
            "scenario": scenario,
            "model": model_name,
            "changed_panels": int(changed.sum()),
            "flag_rate_after_change": (
                float(modified_flag[changed].mean())
                if changed.any() else None
            ),
            "previously_unflagged_changed_panels": int(eligible.sum()),
            "new_flag_rate_among_previously_unflagged": (
                float(modified_flag[eligible].mean())
                if eligible.any() else None
            ),
            "fraction_with_score_increase": (
                float((
                    scores[changed]
                    > original_scores[model_name][changed]
                ).mean()) if changed.any() else None
            ),
        })

        detail = test[["PATIENT", "ENCOUNTER", "DATE"]].copy()
        detail["scenario"] = scenario
        detail["model"] = model_name
        detail["feature_changed"] = np.array(features)[selected_columns]
        detail["original_value"] = original[rows, selected_columns]
        detail["modified_value"] = modified[rows, selected_columns]
        detail["actually_changed"] = changed
        detail["original_score"] = original_scores[model_name]
        detail["modified_score"] = scores
        detail["original_flag"] = original_flag
        detail["modified_flag"] = modified_flag
        details.append(detail)

summary_frame = pd.DataFrame(summary)
summary_frame.to_csv(OUT / "summary.csv", index=False)
pd.concat(details, ignore_index=True).to_csv(
    OUT / "paired_results.csv", index=False
)

report = {
    "seed": 2026,
    "test_panels": n,
    "thresholds": thresholds,
    "results": summary,
    "limitations": [
        "Original Synthea panels do not have verified anomaly labels.",
        "Original flag rates are not false-positive rates.",
        "Corruptions are artificial and may remain statistically plausible.",
        "Repeated panels from one patient are not independent samples.",
        "Results do not establish clinical diagnostic performance.",
    ],
}
(OUT / "report.json").write_text(json.dumps(report, indent=2))

display = summary_frame.copy()
for column in [
    "flag_rate_after_change",
    "new_flag_rate_among_previously_unflagged",
    "fraction_with_score_increase",
]:
    display[column] = display[column].map(
        lambda value: f"{value:.1%}" if pd.notna(value) else "N/A"
    )

print("\nPaired corruption experiment:")
print(display.to_string(index=False))
print("\nSaved results to:", OUT)
