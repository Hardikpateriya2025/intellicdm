from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.lab_schemas import LabResultCreate, LabResultRead
from app.models import Encounter, LabResult, Patient

router = APIRouter(
    prefix="/encounters/{encounter_id}/labs",
    tags=["Lab Results"],
)

@router.post("", response_model=LabResultRead, status_code=201)
def create_lab_result(
    encounter_id: UUID,
    payload: LabResultCreate,
    db: Session = Depends(get_db),
):
    encounter = db.get(Encounter, encounter_id)
    if encounter is None:
        raise HTTPException(status_code=404, detail="Encounter not found")

    patient = db.get(Patient, encounter.patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    if payload.collected_at.date() < patient.date_of_birth:
        raise HTTPException(
            status_code=422,
            detail="Collection date cannot be before the patient's date of birth",
        )

    result = LabResult(
        encounter_id=encounter_id,
        **payload.model_dump(),
    )
    db.add(result)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(result)
    return result

@router.get("", response_model=list[LabResultRead])
def list_lab_results(
    encounter_id: UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    if db.get(Encounter, encounter_id) is None:
        raise HTTPException(status_code=404, detail="Encounter not found")

    statement = (
        select(LabResult)
        .where(LabResult.encounter_id == encounter_id)
        .order_by(LabResult.collected_at.desc(), LabResult.id)
        .offset(offset)
        .limit(limit)
    )
    return db.scalars(statement).all()
