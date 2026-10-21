from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.encounter_schemas import EncounterCreate, EncounterRead
from app.models import Encounter, Patient

router = APIRouter(
    prefix="/patients/{patient_id}/encounters",
    tags=["Encounters"],
)

@router.post("", response_model=EncounterRead, status_code=201)
def create_encounter(
    patient_id: UUID,
    payload: EncounterCreate,
    db: Session = Depends(get_db),
):
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    if payload.visited_at.date() < patient.date_of_birth:
        raise HTTPException(
            status_code=422,
            detail="Visit date cannot be before the patient's date of birth",
        )

    encounter = Encounter(
        patient_id=patient_id,
        **payload.model_dump(),
    )
    db.add(encounter)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(encounter)
    return encounter

@router.get("", response_model=list[EncounterRead])
def list_encounters(
    patient_id: UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    if db.get(Patient, patient_id) is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    statement = (
        select(Encounter)
        .where(Encounter.patient_id == patient_id)
        .order_by(Encounter.visited_at.desc(), Encounter.id)
        .offset(offset)
        .limit(limit)
    )
    return db.scalars(statement).all()
