from pathlib import Path
import sys
import json

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from app.ml import load_artifacts, ARTIFACTS

config, scaler, model = load_artifacts()
features = config["features"]

OUT = ROOT / "artifacts/synthea_feature_score_v2"
OUT.mkdir(parents=True, exist_ok=True)

validation = pd.read_csv(
    ROOT / "data/synthea_prepared_v1/validation.csv"
)
evaluation = pd.read_csv(
    ARTIFACTS / "fresh_population_evaluation/original_panels.csv"
)

if set(validation["PATIENT"]) & set(evaluation["PATIENT"]):
    raise RuntimeError("Patient overlap detected")


def feature_errors(frame):
    scaled = scaler.transform(frame[features]).astype("float32")
    errors = []

    with torch.inference_mode():
        for start in range(0, len(scaled), 1024):
            batch = torch.from_numpy(scaled[start:start + 1024])
            errors.append(((model(batch) - batch) ** 2).numpy())

    result = np.concatenate(errors)
    if not np.isfinite(result).all():
        raise RuntimeError("Non-finite reconstruction errors")
    return result


# Calibration uses validation data only.
validation_errors = feature_errors(validation)

# Each feature gets its own reference error scale.
# The floor prevents division by zero.
error_scales = np.maximum(
    np.quantile(validation_errors, 0.95, axis=0), 1e-8
)

validation_v2 = (validation_errors / error_scales).max(axis=1)
v2_threshold = float(np.quantile(validation_v2, 0.95))
v1_threshold = float(config["autoencoder_threshold"])

calibration = {
    "version": "synthea_feature_score_v2",
    "base_model": "synthea_autoencoder_v1",
    "features": features,
    "feature_error_scales": error_scales.tolist(),
    "threshold": v2_threshold,
    "score": "max(per_feature_squared_error / feature_error_scale)",
    "calibration": (
        "Feature scales and threshold estimated from original validation "
        "panels. No known-normal labels or probability calibration."
    ),
}
(OUT / "scoring_config.json").write_text(
    json.dumps(calibration, indent=2)
)

original_errors = feature_errors(evaluation)


def both_scores(errors):
    return {
        "v1_average": errors.mean(axis=1),
        "v2_feature_max": (errors / error_scales).max(axis=1),
    }


thresholds = {
    "v1_average": v1_threshold,
    "v2_feature_max": v2_threshold,
}
original_scores = both_scores(original_errors)

print("Original-panel flag rates (NOT false-positive rates):")
original_rates = {}

for name, scores in original_scores.items():
    flags = scores >= thresholds[name]
    patient_rate = pd.DataFrame({
        "patient": evaluation["PATIENT"].to_numpy(),
        "flag": flags,
    }).groupby("patient")["flag"].mean().mean()

    original_rates[name] = {
        "panel_weighted": float(flags.mean()),
        "equal_patient_weighted": float(patient_rate),
    }
    print(
        f"{name}: panels={flags.mean():.2%}, "
        f"equal-patient={patient_rate:.2%}"
    )

# For a fair paired comparison, use the SAME originally unflagged
# panels for both methods.
common_unflagged = (
    (original_scores["v1_average"] < v1_threshold)
    & (original_scores["v2_feature_max"] < v2_threshold)
)

print("\nPanels initially unflagged by BOTH:",
      int(common_unflagged.sum()))

rows = []

for feature in features:
    for scenario, factor in [
        ("divide_by_10", 0.1),
        ("multiply_by_10", 10.0),
    ]:
        changed = evaluation.copy()
        changed[feature] = changed[feature] * factor

        eligible = common_unflagged & (
            changed[feature].to_numpy()
            != evaluation[feature].to_numpy()
        )
        scores = both_scores(feature_errors(changed))

        for name, values in scores.items():
            flags = values >= thresholds[name]
            by_patient = pd.DataFrame({
                "patient": evaluation.loc[eligible, "PATIENT"].to_numpy(),
                "flag": flags[eligible],
            }).groupby("patient")["flag"].mean()

            rows.append({
                "feature": feature,
                "error": scenario,
                "method": name,
                "eligible_panels": int(eligible.sum()),
                "eligible_patients": len(by_patient),
                "equal_patient_detection": (
                    float(by_patient.mean()) if len(by_patient) else None
                ),
            })

results = pd.DataFrame(rows)
results.to_csv(OUT / "development_comparison.csv", index=False)

(OUT / "original_flag_rates.json").write_text(
    json.dumps(original_rates, indent=2)
)

table = results.pivot(
    index=["feature", "error"],
    columns="method",
    values="equal_patient_detection",
)

print("\nEqual-patient detection on common eligible panels (%):")
print((100 * table).round(1).to_string())

print("\nSaved:", OUT)
print("Development comparison only: this population was already inspected.")
print("API and version-1 artifacts are unchanged.")
