from pathlib import Path
import json

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "data/synthea_2000/csv/observations.csv"
OUTPUT = ROOT / "data/synthea_prepared_v1"
OUTPUT.mkdir(parents=True, exist_ok=True)

SPEC = {
    "2339-0": ("glucose", "mg/dL"),
    "38483-4": ("creatinine", "mg/dL"),
    "6299-2": ("urea_nitrogen", "mg/dL"),
    "2947-0": ("sodium", "mmol/L"),
    "6298-4": ("potassium", "mmol/L"),
    "2069-3": ("chloride", "mmol/L"),
    "49765-1": ("calcium", "mg/dL"),
    "20565-8": ("total_co2", "mmol/L"),
}
FEATURES = [name for name, unit in SPEC.values()]
KEYS = ["PATIENT", "ENCOUNTER", "DATE"]
columns = KEYS + ["CATEGORY", "CODE", "VALUE", "UNITS"]

parts = []
rejected = 0

for chunk in pd.read_csv(
    SOURCE, usecols=columns, dtype=str, chunksize=100000
):
    selected = chunk[chunk["CODE"].isin(SPEC)].copy()

    selected["numeric_value"] = pd.to_numeric(
        selected["VALUE"], errors="coerce"
    )
    selected["DATE"] = pd.to_datetime(
        selected["DATE"], errors="coerce", utc=True
    )
    expected_units = selected["CODE"].map(
        {code: unit for code, (name, unit) in SPEC.items()}
    )

    valid = (
        selected["CATEGORY"].eq("laboratory")
        & selected["UNITS"].eq(expected_units)
        & selected[KEYS].notna().all(axis=1)
        & np.isfinite(selected["numeric_value"])
    )

    rejected += int((~valid).sum())
    selected = selected.loc[valid].copy()
    selected["feature"] = selected["CODE"].map(
        {code: name for code, (name, unit) in SPEC.items()}
    )
    parts.append(selected[KEYS + ["feature", "numeric_value"]])

long = pd.concat(parts, ignore_index=True)
if long.empty:
    raise SystemExit("No valid measurements matched the selected codes and units.")

# Collapse identical duplicates, but reject panels with conflicting
# values for the same feature at the same collection timestamp.
group_keys = KEYS + ["feature"]
value_counts = long.groupby(group_keys)["numeric_value"].nunique()
conflicts = value_counts[value_counts > 1]
bad_panels = conflicts.reset_index()[KEYS].drop_duplicates()

if not bad_panels.empty:
    long = long.merge(
        bad_panels.assign(conflicting_panel=True),
        on=KEYS,
        how="left",
    )
    long = long[
        long["conflicting_panel"].isna()
    ].drop(columns="conflicting_panel")

long = long.drop_duplicates(group_keys)

wide = long.pivot(
    index=KEYS, columns="feature", values="numeric_value"
).reindex(columns=FEATURES)

candidate_panels = len(wide)

# Complete panels only for this first experiment.
# We do not fill missing measurements with invented values.
complete = wide.dropna(subset=FEATURES).reset_index()
complete.columns.name = None
complete = complete.sort_values(KEYS).reset_index(drop=True)

patient_ids = np.array(sorted(complete["PATIENT"].unique()))
if len(patient_ids) < 30:
    raise SystemExit(
        f"Only {len(patient_ids)} patients have complete panels. "
        "Inspect coverage before training."
    )

rng = np.random.default_rng(42)
rng.shuffle(patient_ids)

train_end = int(0.70 * len(patient_ids))
validation_end = int(0.85 * len(patient_ids))

groups = {
    "train": set(patient_ids[:train_end]),
    "validation": set(patient_ids[train_end:validation_end]),
    "test": set(patient_ids[validation_end:]),
}

assert groups["train"].isdisjoint(groups["validation"])
assert groups["train"].isdisjoint(groups["test"])
assert groups["validation"].isdisjoint(groups["test"])

summary = {
    "valid_measurement_rows_before_deduplication":
        int(sum(len(part) for part in parts)),
    "rejected_measurement_rows": rejected,
    "conflicting_panels_removed": len(bad_panels),
    "candidate_panels_after_conflict_removal": candidate_panels,
    "incomplete_panels_removed": candidate_panels - len(complete),
    "complete_panels": len(complete),
    "patients_with_complete_panels": len(patient_ids),
    "splits": {},
}

for name, ids in groups.items():
    frame = complete[complete["PATIENT"].isin(ids)].copy()
    frame.to_csv(OUTPUT / f"{name}.csv", index=False)
    summary["splits"][name] = {
        "rows": len(frame),
        "patients": int(frame["PATIENT"].nunique()),
    }

metadata = {
    "features": FEATURES,
    "units": {name: unit for name, unit in SPEC.values()},
    "codes": {name: code for code, (name, unit) in SPEC.items()},
    "grouping": KEYS,
    "split_seed": 42,
    "scope": "Synthetic data; no clinical anomaly labels",
}

(OUTPUT / "metadata.json").write_text(json.dumps(metadata, indent=2))
(OUTPUT / "preparation_report.json").write_text(
    json.dumps(summary, indent=2)
)

print(json.dumps(summary, indent=2))
print("\nSaved prepared datasets to:", OUTPUT)
print("\nTraining features:", FEATURES)
