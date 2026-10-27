from pathlib import Path
import sys
import json

import joblib
import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from app.ml import load_artifacts, ARTIFACTS

SOURCE = ROOT / "data/synthea_external_500/csv"
OUT = ARTIFACTS / "fresh_population_evaluation"
OUT.mkdir(parents=True, exist_ok=True)

config, scaler, autoencoder = load_artifacts()
forest = joblib.load(ARTIFACTS / "isolation_forest.joblib")

features = config["features"]
code_to_feature = {
    code: feature for feature, code in config["codes"].items()
}
expected_units = {
    code: config["units"][feature]
    for code, feature in code_to_feature.items()
}
keys = ["PATIENT", "ENCOUNTER", "DATE"]

# Recheck separation from the entire original generated population.
old_ids = set(pd.read_csv(
    ROOT / "data/synthea_2000/csv/patients.csv",
    usecols=["Id"], dtype=str,
)["Id"])
new_ids = set(pd.read_csv(
    SOURCE / "patients.csv", usecols=["Id"], dtype=str
)["Id"])
if old_ids & new_ids:
    raise RuntimeError("Patient IDs overlap with the original population.")

parts = []
rejected = 0

for chunk in pd.read_csv(
    SOURCE / "observations.csv",
    dtype=str,
    usecols=keys + ["CATEGORY", "CODE", "VALUE", "UNITS"],
    chunksize=100000,
):
    selected = chunk[chunk["CODE"].isin(code_to_feature)].copy()
    selected["numeric_value"] = pd.to_numeric(
        selected["VALUE"], errors="coerce"
    )
    selected["DATE"] = pd.to_datetime(
        selected["DATE"], errors="coerce", utc=True
    )

    valid = (
        selected["CATEGORY"].eq("laboratory")
        & selected["UNITS"].eq(selected["CODE"].map(expected_units))
        & selected[keys].notna().all(axis=1)
        & np.isfinite(selected["numeric_value"])
    )
    rejected += int((~valid).sum())
    selected = selected.loc[valid].copy()
    selected["feature"] = selected["CODE"].map(code_to_feature)
    parts.append(selected[keys + ["feature", "numeric_value"]])

long = pd.concat(parts, ignore_index=True)
if long.empty:
    raise RuntimeError("No matching measurements found.")

group_keys = keys + ["feature"]
counts = long.groupby(group_keys)["numeric_value"].nunique()
conflicts = counts[counts > 1].reset_index()[keys].drop_duplicates()

if not conflicts.empty:
    long = long.merge(
        conflicts.assign(conflict=True), on=keys, how="left"
    )
    long = long[long["conflict"].isna()].drop(columns="conflict")

long = long.drop_duplicates(group_keys)
wide = long.pivot(
    index=keys, columns="feature", values="numeric_value"
).reindex(columns=features)

candidate_count = len(wide)
panels = wide.dropna(subset=features).reset_index()
panels.columns.name = None
panels = panels.sort_values(keys).reset_index(drop=True)

if panels.empty:
    raise RuntimeError("No complete panels found.")

panels.to_csv(OUT / "original_panels.csv", index=False)
original = panels[features].to_numpy(dtype=float)
patient_ids = panels["PATIENT"].to_numpy()

thresholds = {
    "autoencoder": float(config["autoencoder_threshold"]),
    "isolation_forest": float(config["isolation_forest_threshold"]),
}


def score(values):
    frame = pd.DataFrame(values, columns=features)
    scaled = scaler.transform(frame).astype("float32")
    if not np.isfinite(scaled).all():
        raise RuntimeError("Non-finite model inputs")

    errors = []
    with torch.inference_mode():
        for start in range(0, len(scaled), 1024):
            batch = torch.from_numpy(scaled[start:start + 1024])
            errors.append(
                ((autoencoder(batch) - batch) ** 2)
                .mean(dim=1).numpy()
            )

    return {
        "autoencoder": np.concatenate(errors),
        "isolation_forest": -forest.score_samples(scaled),
    }


original_scores = score(original)
base_report = {}

for name, scores in original_scores.items():
    flags = scores >= thresholds[name]
    base_report[name] = {
        "threshold": thresholds[name],
        "original_panel_flag_rate": float(flags.mean()),
        "flagged_original_panels": int(flags.sum()),
    }

results = []

for column, feature in enumerate(features):
    for scenario, factor in [("multiply_by_10", 10.0),
                             ("divide_by_10", 0.1)]:
        modified = original.copy()
        modified[:, column] *= factor
        changed = modified[:, column] != original[:, column]
        modified_scores = score(modified)

        for name, scores in modified_scores.items():
            original_flags = original_scores[name] >= thresholds[name]
            modified_flags = scores >= thresholds[name]
            eligible = changed & ~original_flags

            # Report panel-weighted and equal-patient-weighted rates.
            patient_rates = pd.DataFrame({
                "patient": patient_ids[eligible],
                "flagged": modified_flags[eligible],
            }).groupby("patient")["flagged"].mean()

            results.append({
                "feature": feature,
                "error": scenario,
                "model": name,
                "changed_panels": int(changed.sum()),
                "eligible_panels": int(eligible.sum()),
                "eligible_patients": len(patient_rates),
                "new_flag_rate": (
                    float(modified_flags[eligible].mean())
                    if eligible.any() else None
                ),
                "equal_patient_new_flag_rate": (
                    float(patient_rates.mean())
                    if len(patient_rates) else None
                ),
            })

summary = pd.DataFrame(results)
summary.to_csv(OUT / "per_feature_results.csv", index=False)

report = {
    "population": "Fresh Synthea population, same generator",
    "complete_panels": len(panels),
    "patients_with_complete_panels": int(panels["PATIENT"].nunique()),
    "rejected_measurements": rejected,
    "conflicting_panels_removed": len(conflicts),
    "incomplete_panels_removed": candidate_count - len(panels),
    "original_panel_results": base_report,
    "limitations": [
        "Original panels have no verified anomaly labels.",
        "Original flag rates are not false-positive rates.",
        "Errors are artificial decimal shifts, not clinical diagnoses.",
        "No model fitting or threshold adjustment was performed.",
    ],
}
(OUT / "report.json").write_text(json.dumps(report, indent=2))

print("\nPopulation and original-panel results:")
print(json.dumps(report, indent=2))

print("\nNEW FLAG RATES among previously unflagged changed panels (%):")
table = summary.pivot(
    index=["feature", "error"],
    columns="model",
    values="new_flag_rate",
)
print((100 * table).round(1).to_string())

print("\nEQUAL-PATIENT-WEIGHTED new flag rates (%):")
patient_table = summary.pivot(
    index=["feature", "error"],
    columns="model",
    values="equal_patient_new_flag_rate",
)
print((100 * patient_table).round(1).to_string())

print("\nSaved results to:", OUT)
