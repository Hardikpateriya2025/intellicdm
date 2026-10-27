"""Atomic import of patient-linked chemistry panels from CSV."""
import csv
import io
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import (
    AwareDatetime, BaseModel, ConfigDict, Field, ValidationError,
    model_validator,
)
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth import clinical_access
from app.database import get_db
from app.models import Patient, Encounter, LabResult

router = APIRouter(
    prefix="/csv/patient-records",
    tags=["CSV Patient Records"],
    dependencies=[Depends(clinical_access)],
)

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 200

SPEC = {
    "glucose": ("mg/dL", "2339-0", "Glucose [Mass/volume] in Blood"),
    "creatinine": ("mg/dL", "38483-4", "Creatinine [Mass/volume] in Blood"),
    "urea_nitrogen": ("mg/dL", "6299-2", "Urea nitrogen [Mass/volume] in Blood"),
    "sodium": ("mmol/L", "2947-0", "Sodium [Moles/volume] in Blood"),
    "potassium": ("mmol/L", "6298-4", "Potassium [Moles/volume] in Blood"),
    "chloride": ("mmol/L", "2069-3", "Chloride [Moles/volume] in Blood"),
    "calcium": ("mg/dL", "49765-1", "Calcium [Mass/volume] in Blood"),
    "total_co2": ("mmol/L", "20565-8", "Carbon dioxide, total [Moles/volume] in Blood"),
}

Measurement = Annotated[
    Decimal, Field(max_digits=18, decimal_places=6, allow_inf_nan=False)
]


class PatientPanelRow(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, allow_inf_nan=False
    )

    medical_record_number: str = Field(min_length=1, max_length=50)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    date_of_birth: date
    visited_at: AwareDatetime
    collected_at: AwareDatetime
    encounter_reason: str = Field(min_length=1, max_length=500)
    glucose: Measurement
    creatinine: Measurement
    urea_nitrogen: Measurement
    sodium: Measurement
    potassium: Measurement
    chloride: Measurement
    calcium: Measurement
    total_co2: Measurement

    @model_validator(mode="after")
    def validate_dates(self):
        now = datetime.now(timezone.utc)
        if self.date_of_birth > now.date():
            raise ValueError("Date of birth cannot be in the future")
        if self.visited_at > now or self.collected_at > now:
            raise ValueError("Visit and collection times cannot be in the future")
        if (
            self.visited_at.date() < self.date_of_birth
            or self.collected_at.date() < self.date_of_birth
        ):
            raise ValueError("Visit and collection dates cannot precede birth")
        return self


def parse_csv(raw):
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, "CSV must be at most 2 MiB.")
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(422, "Use UTF-8 CSV encoding.") from None
    if "\x00" in content:
        raise HTTPException(422, "CSV contains null bytes.")

    required = list(PatientPanelRow.model_fields)
    output = []
    try:
        reader = csv.reader(io.StringIO(content, newline=""), strict=True)
        headers = next(reader, None)
        if not headers:
            raise HTTPException(422, "CSV is empty.")
        headers = [value.strip() for value in headers]
        if (
            len(headers) > 50
            or any(not value for value in headers)
            or len(headers) != len(set(headers))
        ):
            raise HTTPException(422, "Headers must be unique, nonempty, and at most 50.")
        missing = sorted(set(required) - set(headers))
        if missing:
            raise HTTPException(
                422, "Missing patient-record columns: " + ", ".join(missing)
            )

        for number, cells in enumerate(reader, 1):
            if not cells or all(not value.strip() for value in cells):
                continue
            if len(output) >= MAX_ROWS:
                raise HTTPException(
                    422, f"Patient-record imports allow at most {MAX_ROWS} panels per file."
                )
            if len(cells) != len(headers) or any(len(value) > 1000 for value in cells):
                raise HTTPException(422, f"Data record {number}: invalid field count or size.")
            values = dict(zip(headers, cells))
            try:
                row = PatientPanelRow.model_validate(
                    {key: values[key] for key in required}
                )
            except ValidationError as exc:
                problems = "; ".join(
                    f"{'.'.join(map(str, item['loc']))}: {item['msg']}"
                    for item in exc.errors(include_input=False, include_url=False)
                )
                raise HTTPException(422, f"Data record {number}: {problems}") from None
            output.append((number, row))
    except csv.Error:
        raise HTTPException(422, "Malformed CSV quoting or delimiters.") from None

    if not output:
        raise HTTPException(422, "CSV contains no patient records.")
    return output, sorted(set(headers) - set(required))


def read_upload(file):
    try:
        return file.file.read(MAX_BYTES + 1)
    finally:
        file.file.close()


@router.post("/validate")
def validate_patient_csv(file: UploadFile = File(...)):
    rows, ignored = parse_csv(read_upload(file))
    return {
        "panels": len(rows),
        "patient_identifiers": len({row.medical_record_number for _, row in rows}),
        "ignored_columns": ignored,
        "sample": [
            {
                "record": number,
                "medical_record_number": row.medical_record_number,
                "patient_name": f"{row.first_name} {row.last_name}",
                "visited_at": row.visited_at,
                "collected_at": row.collected_at,
            }
            for number, row in rows[:5]
        ],
        "notice": (
            "Format validation only. Existing-record conflicts are checked when saving. "
            "Extra columns are not saved. Times must include a timezone."
        ),
    }


def normalize(value):
    return " ".join(value.strip().casefold().split())


ALIASES = {
    normalize(alias): name
    for name, (_, code, description) in SPEC.items()
    for alias in (name, code, description)
}


def conflict(number, message):
    raise HTTPException(
        409, f"Data record {number}: {message} No records from this request were saved."
    )


@router.post("/save")
def save_patient_csv(
    file: UploadFile = File(...),
    units_confirmed: bool = Form(...),
    db: Session = Depends(get_db),
):
    if not units_confirmed:
        raise HTTPException(422, "Confirm the documented measurement units before saving.")

    rows, ignored = parse_csv(read_upload(file))
    created = {"patients": 0, "encounters": 0, "lab_results": 0}
    reused_panels = 0
    patient_cache = {}
    encounter_cache = {}
    patient_ids = set()
    encounter_ids = set()

    try:
        # Serialize CSV imports. Other clinical writers still use row locks
        # and the unique MRN database constraint.
        db.execute(text("SELECT pg_advisory_xact_lock(734821905)"))

        for number, row in rows:
            mrn = row.medical_record_number
            patient = patient_cache.get(mrn)
            if patient is None:
                patient = db.scalar(
                    select(Patient)
                    .where(Patient.medical_record_number == mrn)
                    .with_for_update()
                )
                if patient is None:
                    patient = Patient(
                        medical_record_number=mrn,
                        first_name=row.first_name,
                        last_name=row.last_name,
                        date_of_birth=row.date_of_birth,
                    )
                    db.add(patient)
                    db.flush()
                    created["patients"] += 1
                patient_cache[mrn] = patient

            if (
                normalize(patient.first_name) != normalize(row.first_name)
                or normalize(patient.last_name) != normalize(row.last_name)
                or patient.date_of_birth != row.date_of_birth
            ):
                conflict(number, "This MRN already has different patient details.")

            key = (patient.id, row.visited_at.astimezone(timezone.utc))
            encounter = encounter_cache.get(key)
            if encounter is None:
                matches = db.scalars(
                    select(Encounter)
                    .where(
                        Encounter.patient_id == patient.id,
                        Encounter.visited_at == row.visited_at,
                    )
                    .order_by(Encounter.id)
                    .with_for_update()
                ).all()
                if len(matches) > 1:
                    conflict(number, "Multiple encounters have this patient and visit time.")
                encounter = matches[0] if matches else None
                if encounter is None:
                    encounter = Encounter(
                        patient_id=patient.id,
                        visited_at=row.visited_at,
                        reason=row.encounter_reason,
                        notes="Imported from a patient-record CSV.",
                    )
                    db.add(encounter)
                    db.flush()
                    created["encounters"] += 1
                encounter_cache[key] = encounter

            if normalize(encounter.reason) != normalize(row.encounter_reason):
                conflict(number, "The existing encounter has a different visit reason.")

            existing = db.scalars(
                select(LabResult).where(
                    LabResult.encounter_id == encounter.id,
                    LabResult.collected_at == row.collected_at,
                )
            ).all()

            matched = {}
            for lab in existing:
                name = ALIASES.get(normalize(lab.test_name))
                if name:
                    matched.setdefault(name, []).append(lab)

            if matched:
                if set(matched) != set(SPEC):
                    conflict(number, "A partial chemistry panel already exists at this time.")
                for name, labs in matched.items():
                    unit = SPEC[name][0]
                    if any(
                        lab.value != getattr(row, name) or lab.unit != unit
                        for lab in labs
                    ):
                        conflict(number, f"Existing {name} value or unit differs.")
                reused_panels += 1
            else:
                for name, (unit, _, _) in SPEC.items():
                    db.add(LabResult(
                        encounter_id=encounter.id,
                        test_name=name,
                        value=getattr(row, name),
                        unit=unit,
                        collected_at=row.collected_at,
                    ))
                db.flush()
                created["lab_results"] += 8

            patient_ids.add(str(patient.id))
            encounter_ids.add(str(encounter.id))

        response = {
            "status": "saved",
            "processed_panels": len(rows),
            "created": created,
            "reused_panels": reused_panels,
            "patient_ids": sorted(patient_ids),
            "encounter_ids": sorted(encounter_ids),
            "ignored_columns": ignored,
            "notice": (
                "Patient, encounter and lab records are saved in PostgreSQL. "
                "No existing values were overwritten. Original CSV bytes, model "
                "results and reviews were not saved. Score an imported encounter "
                "in its patient workspace to create scoring history."
            ),
        }
        db.commit()
        return response
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409,
            "Concurrent or conflicting records were detected. Nothing from this "
            "request was saved. Refresh and retry after checking the records.",
        ) from None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            503, "The database could not complete the import. No partial import was committed."
        ) from None
