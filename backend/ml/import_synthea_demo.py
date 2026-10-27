from pathlib import Path
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid5, NAMESPACE_URL
import json
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from app.database import SessionLocal
from app.models import Patient, Encounter, LabResult

CSV = ROOT / "data/synthea_2000/csv"
PREPARED = ROOT / "data/synthea_prepared_v1"
metadata = json.loads((PREPARED / "metadata.json").read_text())
features = metadata["features"]


def read_checked(path, required):
    columns = pd.read_csv(path, nrows=0).columns
    missing = set(required) - set(columns)
    if missing:
        raise SystemExit(f"{path.name}: missing columns {sorted(missing)}")
    return pd.read_csv(path, usecols=required, dtype=str).fillna("")


def timestamp(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp must include a timezone")
    return result.astimezone(timezone.utc)


def mapped_id(kind, source):
    return uuid5(
        NAMESPACE_URL,
        f"intellicdm/synthea_2000/import_v1/{kind}/{source}",
    )


panels = read_checked(
    PREPARED / "train.csv",
    ["PATIENT", "ENCOUNTER", "DATE"] + features,
)
patients = read_checked(
    CSV / "patients.csv", ["Id", "BIRTHDATE", "FIRST", "LAST"]
)
encounters = read_checked(
    CSV / "encounters.csv",
    ["Id", "START", "PATIENT", "DESCRIPTION", "REASONDESCRIPTION"],
)

if patients["Id"].duplicated().any() or encounters["Id"].duplicated().any():
    raise SystemExit("Duplicate patient or encounter IDs in source CSVs.")

# Choose a reproducible, bounded sample of complete panels.
chosen = sorted(panels["PATIENT"].unique())[:10]
panels = panels[panels["PATIENT"].isin(chosen)].copy()
panels["parsed_date"] = panels["DATE"].map(timestamp)
panels = (
    panels.sort_values(["PATIENT", "parsed_date", "ENCOUNTER"])
    .groupby("PATIENT", sort=False)
    .tail(5)
)

if panels.empty:
    raise SystemExit("No eligible panels.")

patient_rows = patients.set_index("Id")
encounter_rows = encounters.set_index("Id")
now = datetime.now(timezone.utc)

# Validate and assemble the entire import before opening a write transaction.
patient_specs = {}
encounter_specs = {}
lab_specs = {}

for _, panel in panels.iterrows():
    source_patient = panel["PATIENT"]
    source_encounter = panel["ENCOUNTER"]

    UUID(source_patient)
    UUID(source_encounter)

    if source_patient not in patient_rows.index:
        raise ValueError(f"Missing source patient: {source_patient}")
    if source_encounter not in encounter_rows.index:
        raise ValueError(f"Missing source encounter: {source_encounter}")

    p = patient_rows.loc[source_patient]
    e = encounter_rows.loc[source_encounter]
    if e["PATIENT"] != source_patient:
        raise ValueError("Patient/encounter link mismatch")

    dob = date.fromisoformat(p["BIRTHDATE"])
    visited = timestamp(e["START"])
    collected = panel["parsed_date"]

    if not (dob <= visited.date() and dob <= collected.date()):
        raise ValueError("Visit or collection predates birth")
    if visited > now or collected > now:
        raise ValueError("Future visit or collection")
    if collected < visited:
        raise ValueError("Collection predates encounter start")
    if not p["FIRST"] or not p["LAST"]:
        raise ValueError("Missing patient name")
    if len(p["FIRST"]) > 100 or len(p["LAST"]) > 100:
        raise ValueError("Patient name exceeds database field length")

    pid = mapped_id("patient", source_patient)
    eid = mapped_id("encounter", source_encounter)

    patient_specs[pid] = {
        "medical_record_number": f"SYNTH-{source_patient}",
        "first_name": p["FIRST"],
        "last_name": p["LAST"],
        "date_of_birth": dob,
    }

    reason = e["REASONDESCRIPTION"] or e["DESCRIPTION"] or "Synthetic encounter"
    if len(reason) > 500:
        raise ValueError("Encounter reason exceeds database field length")

    encounter_specs[eid] = {
        "patient_id": pid,
        "visited_at": visited,
        "reason": reason,
        "notes": (
            "Synthetic Synthea data for development only. "
            f"Source patient: {source_patient}; "
            f"source encounter: {source_encounter}. "
            "Imported subset: selected complete blood chemistry panels."
        ),
    }

    for feature in features:
        value = Decimal(panel[feature])
        if not value.is_finite():
            raise ValueError(f"Non-finite value: {feature}")

        lid = mapped_id(
            "lab", f"{source_encounter}/{collected.isoformat()}/{feature}"
        )
        spec = {
            "encounter_id": eid,
            "test_name": metadata["codes"][feature],
            "value": value,
            "unit": metadata["units"][feature],
            "collected_at": collected,
        }
        if lid in lab_specs and lab_specs[lid] != spec:
            raise ValueError("Conflicting source lab values")
        lab_specs[lid] = spec

counts = {"created": {}, "reused": {}}


def insert_or_verify(db, model, specs):
    created = reused = 0
    for record_id, fields in specs.items():
        existing = db.get(model, record_id)
        if existing is None:
            db.add(model(id=record_id, **fields))
            created += 1
        else:
            differences = [
                name for name, value in fields.items()
                if getattr(existing, name) != value
            ]
            if differences:
                raise ValueError(
                    f"{model.__name__} {record_id}: existing fields differ: "
                    f"{differences}. No overwrite performed."
                )
            reused += 1
    db.flush()
    counts["created"][model.__name__] = created
    counts["reused"][model.__name__] = reused


with SessionLocal() as db:
    try:
        insert_or_verify(db, Patient, patient_specs)
        insert_or_verify(db, Encounter, encounter_specs)
        insert_or_verify(db, LabResult, lab_specs)
        db.commit()
    except Exception:
        db.rollback()
        raise

print("\nIMPORT COMPLETE")
print(json.dumps(counts, indent=2))

# Print an encounter whose imported panel can be scored next.
example = panels.sort_values("parsed_date").iloc[-1]
print("\nExample imported patient ID:",
      mapped_id("patient", example["PATIENT"]))
print("Example imported encounter ID:",
      mapped_id("encounter", example["ENCOUNTER"]))
print("\nOnly the selected chemistry subset was imported.")
print("No model was retrained and no scoring history was created.")
