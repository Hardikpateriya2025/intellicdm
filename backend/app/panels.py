"""Save the model's eight chemistry measurements in one transaction."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth import clinical_access
from app.database import get_db
from app.lab_schemas import LabResultRead
from app.models import Encounter, Patient, LabResult

UNITS = {
    "glucose": "mg/dL",
    "creatinine": "mg/dL",
    "urea_nitrogen": "mg/dL",
    "sodium": "mmol/L",
    "potassium": "mmol/L",
    "chloride": "mmol/L",
    "calcium": "mg/dL",
    "total_co2": "mmol/L",
}


class PanelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    collected_at: AwareDatetime
    glucose: Decimal
    creatinine: Decimal
    urea_nitrogen: Decimal
    sodium: Decimal
    potassium: Decimal
    chloride: Decimal
    calcium: Decimal
    total_co2: Decimal

    @field_validator("collected_at")
    @classmethod
    def past_collection(cls, value):
        if value > datetime.now(timezone.utc):
            raise ValueError("Collection time cannot be in the future")
        return value


router = APIRouter(
    tags=["Chemistry Panels"],
    dependencies=[Depends(clinical_access)],
)


@router.post(
    "/encounters/{encounter_id}/chemistry-panel",
    response_model=list[LabResultRead],
    status_code=201,
)
def create_panel(
    encounter_id: UUID,
    payload: PanelCreate,
    db: Session = Depends(get_db),
):
    encounter = db.scalar(
        select(Encounter)
        .where(Encounter.id == encounter_id)
        .with_for_update()
    )
    if encounter is None:
        raise HTTPException(status_code=404, detail="Encounter not found")

    patient = db.get(Patient, encounter.patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    if payload.collected_at.date() < patient.date_of_birth:
        raise HTTPException(
            status_code=422,
            detail="Collection date cannot precede the patient's date of birth",
        )

    existing = db.scalar(
        select(LabResult.id)
        .where(
            LabResult.encounter_id == encounter_id,
            LabResult.collected_at == payload.collected_at,
        )
        .limit(1)
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Lab rows already exist at this collection time. "
                "Inspect them before entering another panel."
            ),
        )

    rows = [
        LabResult(
            encounter_id=encounter_id,
            test_name=name,
            value=getattr(payload, name),
            unit=unit,
            collected_at=payload.collected_at,
        )
        for name, unit in UNITS.items()
    ]

    try:
        db.add_all(rows)
        db.flush()
        result = [LabResultRead.model_validate(row) for row in rows]
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="Panel could not be saved.",
        ) from None

    return result
