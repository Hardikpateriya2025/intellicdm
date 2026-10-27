from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Patient, Encounter, LabResult

router = APIRouter(prefix="/ai", tags=["Lab Trends"])

Feature = Literal[
    "glucose", "creatinine", "urea_nitrogen", "sodium",
    "potassium", "chloride", "calcium", "total_co2",
]

ALIASES = {
    "glucose": ["glucose", "2339-0", "Glucose [Mass/volume] in Blood"],
    "creatinine": [
        "creatinine", "38483-4", "Creatinine [Mass/volume] in Blood"
    ],
    "urea_nitrogen": [
        "urea_nitrogen", "6299-2", "Urea nitrogen [Mass/volume] in Blood"
    ],
    "sodium": ["sodium", "2947-0", "Sodium [Moles/volume] in Blood"],
    "potassium": [
        "potassium", "6298-4", "Potassium [Moles/volume] in Blood"
    ],
    "chloride": [
        "chloride", "2069-3", "Chloride [Moles/volume] in Blood"
    ],
    "calcium": ["calcium", "49765-1", "Calcium [Mass/volume] in Blood"],
    "total_co2": [
        "total_co2", "20565-8",
        "Carbon dioxide total [Moles/volume] in Blood"
    ],
}


@router.get("/patients/{patient_id}/lab-trends/{feature}")
def lab_trend(
    patient_id: UUID,
    feature: Feature,
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    if db.get(Patient, patient_id) is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    accepted = [" ".join(a.casefold().split()) for a in ALIASES[feature]]
    normalized = func.lower(
        func.regexp_replace(func.trim(LabResult.test_name), r"\s+", " ", "g")
    )

    # Fetch newest rows first, then display the selected rows chronologically.
    rows = db.scalars(
        select(LabResult)
        .join(Encounter, LabResult.encounter_id == Encounter.id)
        .where(
            Encounter.patient_id == patient_id,
            normalized.in_(accepted),
        )
        .order_by(LabResult.collected_at.desc(), LabResult.id.desc())
        .limit(limit + 1)
    ).all()

    truncated = len(rows) > limit
    rows = rows[:limit]
    rows.sort(key=lambda r: (r.collected_at, str(r.id)))

    series = {}
    for row in rows:
        unit = row.unit.strip()
        series.setdefault(unit, []).append({
            "lab_id": str(row.id),
            "encounter_id": str(row.encounter_id),
            "collected_at": row.collected_at.isoformat(),
            "value": str(row.value),
        })

    output = []
    for unit, points in series.items():
        values = [Decimal(p["value"]) for p in points]
        finite = all(v.is_finite() for v in values)

        by_time = {}
        for point in points:
            instant = datetime.fromisoformat(point["collected_at"])
            by_time.setdefault(instant, set()).add(Decimal(point["value"]))

        conflicts = any(len(v) > 1 for v in by_time.values())
        delta = None
        reason = None

        if not finite:
            reason = "Non-finite values are present."
        elif conflicts:
            reason = "Conflicting values occur at the same collection time."
        elif len(by_time) < 2:
            reason = "At least two distinct collection times are needed."
        elif truncated:
            reason = "Results are truncated; full-history change is not calculated."
        else:
            delta = str(values[-1] - values[0])

        output.append({
            "unit": unit,
            "points": points,
            "distinct_collection_times": len(by_time),
            "conflicting_same_time_values": conflicts,
            "latest_minus_earliest": delta,
            "change_unavailable_reason": reason,
        })

    return {
        "patient_id": str(patient_id),
        "feature": feature,
        "returned_lab_rows": len(rows),
        "truncated": truncated,
        "selection": "Most recent matching rows, displayed chronologically",
        "series_by_unit": output,
        "notice": (
            "Stored measurements only. Units are not converted. "
            "A numerical change is not a clinical interpretation."
        ),
    }
