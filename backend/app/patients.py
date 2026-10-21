from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Patient
from app.schemas import PatientCreate, PatientRead

router = APIRouter(prefix="/patients", tags=["Patients"])

@router.post("", response_model=PatientRead, status_code=201)
def create_patient(payload: PatientCreate, db: Session = Depends(get_db)):
    patient = Patient(**payload.model_dump())
    db.add(patient)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if getattr(exc.orig, "sqlstate", None) == "23505":
            raise HTTPException(
                status_code=409,
                detail="A patient with this medical record number already exists",
            ) from exc
        raise

    db.refresh(patient)
    return patient

@router.get("", response_model=list[PatientRead])
def list_patients(
    q: str | None = Query(default=None, min_length=1, max_length=100),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    statement = (
        select(Patient)
        .order_by(Patient.created_at.desc(), Patient.id)
        .offset(offset)
        .limit(limit)
    )
    if q and q.strip():
        search = q.strip()
        statement = statement.where(
            or_(
                Patient.first_name.icontains(search, autoescape=True),
                Patient.last_name.icontains(search, autoescape=True),
                Patient.medical_record_number.icontains(search, autoescape=True),
                (Patient.first_name + " " + Patient.last_name).icontains(
                    search, autoescape=True
                ),
            )
        )
    return db.scalars(statement).all()

@router.get("/{patient_id}", response_model=PatientRead)
def get_patient(patient_id: UUID, db: Session = Depends(get_db)):
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


from app.lab_schemas import LabResultRead
from app.models import Encounter, LabResult

@router.get("/{patient_id}/labs", response_model=list[LabResultRead])
def patient_lab_history(
    patient_id: UUID,
    test_name: str | None = Query(default=None, min_length=1, max_length=200),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    if db.get(Patient, patient_id) is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    statement = (
        select(LabResult)
        .join(Encounter, LabResult.encounter_id == Encounter.id)
        .where(Encounter.patient_id == patient_id)
        .order_by(LabResult.collected_at.desc(), LabResult.id)
        .offset(offset)
        .limit(limit)
    )

    if test_name is not None:
        statement = statement.where(
            LabResult.test_name == test_name.strip()
        )

    return db.scalars(statement).all()
