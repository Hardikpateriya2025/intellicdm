from pathlib import Path
import sys
import json
import hashlib

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from app.ml import load_artifacts, ARTIFACTS

SOURCE = ROOT / "data/synthea_final_500/csv"
V2 = ROOT / "artifacts/synthea_feature_score_v2/scoring_config.json"
OUT = ROOT / "artifacts/final_frozen_evaluation"
OUT.mkdir(parents=True, exist_ok=True)

config, scaler, model = load_artifacts()
v2_config = json.loads(V2.read_text())
features = config["features"]

if v2_config["features"] != features:
    raise RuntimeError("Version-2 features do not match the model.")

scales = np.asarray(v2_config["feature_error_scales"], dtype=float)
if scales.shape != (len(features),) or not np.isfinite(scales).all():
    raise RuntimeError("Invalid feature-error scales.")
if (scales <= 0).any():
    raise RuntimeError("Feature-error scales must be positive.")

thresholds = {
    "v1_average": float(config["autoencoder_threshold"]),
    "v2_feature_max": float(v2_config["threshold"]),
}

# Check separation again inside the evaluation.
def ids(folder):
    return set(pd.read_csv(
        ROOT / "data" / folder / "csv/patients.csv",
        usecols=["Id"], dtype=str,
    )["Id"])

final_ids = ids("synthea_final_500")
previous_ids = ids("synthea_2000") | ids("synthea_external_500")
if final_ids & previous_ids:
    raise RuntimeError("Patient overlap found.")

code_map = {code: name for name, code in config["codes"].items()}
unit_map = {
    code: config["units"][name] for code, name in code_map.items()
}
keys = ["PATIENT", "ENCOUNTER", "DATE"]
parts = []
rejected = 0

for chunk in pd.read_csv(
    SOURCE / "observations.csv",
    usecols=keys + ["CATEGORY", "CODE", "VALUE", "UNITS"],
    dtype=str,
    chunksize=100000,
):
    selected = chunk[chunk["CODE"].isin(code_map)].copy()
    selected["numeric_value"] = pd.to_numeric(
        selected["VALUE"], errors="coerce"
    )
    selected["DATE"] = pd.to_datetime(
        selected["DATE"], errors="coerce", utc=True
    )

    valid = (
        selected["CATEGORY"].eq("laboratory")
        & selected["UNITS"].eq(selected["CODE"].map(unit_map))
        & selected[keys].notna().all(axis=1)
        & np.isfinite(selected["numeric_value"])
    )
    rejected += int((~valid).sum())
    selected = selected.loc[valid].copy()
    selected["feature"] = selected["CODE"].map(code_map)
    parts.append(selected[keys + ["feature", "numeric_value"]])

long = pd.concat(parts, ignore_index=True)
if long.empty:
    raise RuntimeError("No eligible measurements.")

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

panels = wide.dropna(subset=features).reset_index()
panels.columns.name = None
panels = panels.sort_values(keys).reset_index(drop=True)

if panels.empty:
    raise RuntimeError("No complete panels.")

panels.to_csv(OUT / "original_panels.csv", index=False)


def scores(frame):
    values = scaler.transform(frame[features]).astype("float32")
    errors = []

    with torch.inference_mode():
        for start in range(0, len(values), 1024):
            batch = torch.from_numpy(values[start:start + 1024])
            errors.append(((model(batch) - batch) ** 2).numpy())

    errors = np.concatenate(errors)
    if not np.isfinite(errors).all():
        raise RuntimeError("Non-finite reconstruction errors.")

    return {
        "v1_average": errors.mean(axis=1),
        "v2_feature_max": (errors / scales).max(axis=1),
    }


def patient_mean(flags, eligible):
    grouped = pd.DataFrame({
        "patient": panels.loc[eligible, "PATIENT"].to_numpy(),
        "flag": flags[eligible],
    }).groupby("patient")["flag"].mean()
    return float(grouped.mean()) if len(grouped) else None


original_scores = scores(panels)
all_rows = np.ones(len(panels), dtype=bool)
original_rates = {}

saved_scores = panels[keys].copy()
for name, values in original_scores.items():
    flags = values >= thresholds[name]
    original_rates[name] = {
        "panel_flag_rate": float(flags.mean()),
        "equal_patient_flag_rate": patient_mean(flags, all_rows),
        "flagged_panels": int(flags.sum()),
    }
    saved_scores[name + "_score"] = values
    saved_scores[name + "_flag"] = flags

saved_scores.to_csv(OUT / "original_scores.csv", index=False)

common_unflagged = (
    (original_scores["v1_average"] < thresholds["v1_average"])
    & (original_scores["v2_feature_max"] < thresholds["v2_feature_max"])
)

rows = []
for feature in features:
    for scenario, factor in [
        ("divide_by_10", 0.1),
        ("multiply_by_10", 10.0),
    ]:
        modified = panels.copy()
        modified[feature] *= factor

        changed = (
            modified[feature].to_numpy()
            != panels[feature].to_numpy()
        )
        eligible = common_unflagged & changed
        modified_scores = scores(modified)

        for name, values in modified_scores.items():
            flags = values >= thresholds[name]
            rows.append({
                "feature": feature,
                "error": scenario,
                "method": name,
                "eligible_panels": int(eligible.sum()),
                "eligible_patients": int(
                    panels.loc[eligible, "PATIENT"].nunique()
                ),
                "panel_detection": (
                    float(flags[eligible].mean())
                    if eligible.any() else None
                ),
                "equal_patient_detection": patient_mean(flags, eligible),
            })

results = pd.DataFrame(rows)
results.to_csv(OUT / "per_feature_results.csv", index=False)

# Record the exact model/configuration files used.
artifact_paths = [
    ARTIFACTS / "autoencoder_weights.pt",
    ARTIFACTS / "scaler.joblib",
    ARTIFACTS / "config.json",
    V2,
]
hashes = {
    str(path.relative_to(ROOT)): hashlib.sha256(
        path.read_bytes()
    ).hexdigest()
    for path in artifact_paths
}

report = {
    "population_patients": len(final_ids),
    "patients_with_complete_panels": int(panels["PATIENT"].nunique()),
    "complete_panels": len(panels),
    "rejected_measurements": rejected,
    "conflicting_panels_removed": len(conflicts),
    "incomplete_panels_removed": len(wide) - len(panels),
    "common_unflagged_panels": int(common_unflagged.sum()),
    "fixed_thresholds": thresholds,
    "original_panel_results": original_rates,
    "artifact_sha256": hashes,
    "limitations": [
        "Same synthetic generator; not real-world clinical validation.",
        "Original flag rates are not known false-positive rates.",
        "Detection results cover artificial x10 and /10 errors only.",
        "No fitting or recalibration was performed.",
    ],
}
(OUT / "report.json").write_text(json.dumps(report, indent=2))

print("\nFINAL EVALUATION REPORT")
print(json.dumps(
    {k: v for k, v in report.items() if k != "artifact_sha256"},
    indent=2,
))

table = results.pivot(
    index=["feature", "error"],
    columns="method",
    values="equal_patient_detection",
)
print("\nEqual-patient detection on common eligible panels (%):")
print((100 * table).round(1).to_string())
print("\nSaved results:", OUT)
