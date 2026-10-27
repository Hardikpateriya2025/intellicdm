"""Authenticated, read-only workspace totals."""
from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth import analysis_access
from app.database import get_db
from app.models import (
    Patient,
    Encounter,
    LabResult,
    AnomalyScoreHistory,
    AnomalyReview,
)

router = APIRouter(
    tags=["Workspace"],
    dependencies=[Depends(analysis_access)],
)


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    ranked = select(
        AnomalyReview.score_history_id,
        AnomalyReview.status,
        func.row_number().over(
            partition_by=AnomalyReview.score_history_id,
            order_by=(
                AnomalyReview.created_at.desc(),
                AnomalyReview.id.desc(),
            ),
        ).label("position"),
    ).subquery()

    latest = select(ranked).where(
        ranked.c.position == 1
    ).subquery()

    pending = (
        select(func.count())
        .select_from(AnomalyScoreHistory)
        .outerjoin(
            latest,
            latest.c.score_history_id == AnomalyScoreHistory.id,
        )
        .where(
            AnomalyScoreHistory.flagged_for_review.is_(True),
            or_(
                latest.c.score_history_id.is_(None),
                latest.c.status == "needs_investigation",
            ),
        )
        .scalar_subquery()
    )

    # All totals use the same SQL statement snapshot.
    statement = select(
        select(func.count())
        .select_from(Patient)
        .scalar_subquery()
        .label("patients"),

        select(func.count())
        .select_from(Encounter)
        .scalar_subquery()
        .label("encounters"),

        select(func.count())
        .select_from(LabResult)
        .scalar_subquery()
        .label("lab_results"),

        select(func.count())
        .select_from(AnomalyScoreHistory)
        .scalar_subquery()
        .label("scoring_records"),

        pending.label("pending_reviews"),
    )

    counts = dict(db.execute(statement).mappings().one())

    return {
        "counts": counts,
        "scope": (
            "Current database totals. Pending reviews count flagged "
            "scoring records whose latest review is absent or needs "
            "investigation. Repeated scores count separately."
        ),
    }


# Dashboard activity: saved database records only.
@router.get("/dashboard/activity")
def dashboard_activity(db: Session = Depends(get_db)):
    from datetime import datetime, timezone

    ranked = select(
        AnomalyReview.score_history_id,
        AnomalyReview.status,
        func.row_number().over(
            partition_by=AnomalyReview.score_history_id,
            order_by=(
                AnomalyReview.created_at.desc(),
                AnomalyReview.id.desc(),
            ),
        ).label("position"),
    ).subquery()

    latest = select(ranked).where(
        ranked.c.position == 1
    ).subquery()

    def patient_info(patient):
        return {
            "patient_id": str(patient.id),
            "patient_name": f"{patient.first_name} {patient.last_name}",
            "medical_record_number": patient.medical_record_number,
        }

    encounters = db.execute(
        select(Encounter, Patient)
        .join(Patient, Encounter.patient_id == Patient.id)
        .order_by(Encounter.visited_at.desc(), Encounter.id.desc())
        .limit(5)
    ).all()

    score_query = (
        select(
            AnomalyScoreHistory,
            Patient,
            latest.c.status.label("review_status"),
        )
        .join(
            Encounter,
            AnomalyScoreHistory.encounter_id == Encounter.id,
        )
        .join(Patient, Encounter.patient_id == Patient.id)
        .outerjoin(
            latest,
            latest.c.score_history_id == AnomalyScoreHistory.id,
        )
    )

    recent = db.execute(
        score_query.order_by(
            AnomalyScoreHistory.created_at.desc(),
            AnomalyScoreHistory.id.desc(),
        ).limit(5)
    ).all()

    pending = db.execute(
        score_query.where(
            AnomalyScoreHistory.flagged_for_review.is_(True),
            or_(
                latest.c.score_history_id.is_(None),
                latest.c.status == "needs_investigation",
            ),
        ).order_by(
            AnomalyScoreHistory.created_at.desc(),
            AnomalyScoreHistory.id.desc(),
        ).limit(5)
    ).all()

    def score_info(row):
        score, patient, status = row
        return {
            **patient_info(patient),
            "history_id": str(score.id),
            "encounter_id": str(score.encounter_id),
            "scored_at": score.created_at,
            "collected_at": score.collected_at,
            "anomaly_score": score.anomaly_score,
            "threshold": score.threshold,
            "flagged_for_review": score.flagged_for_review,
            "review_status": status or "unreviewed",
            "model_version": score.model_version,
            "scoring_version": score.scoring_version,
        }

    return {
        "generated_at": datetime.now(timezone.utc),
        "recent_encounters": [
            {
                **patient_info(patient),
                "encounter_id": str(encounter.id),
                "visited_at": encounter.visited_at,
                "reason": encounter.reason,
            }
            for encounter, patient in encounters
        ],
        "recent_scores": [score_info(row) for row in recent],
        "pending_reviews": [score_info(row) for row in pending],
        "scope": (
            "Up to five records per section. Encounters are ordered by "
            "visit time; scores and pending reviews by scoring time. "
            "Repeated scores remain separate records. CSV testing results "
            "are not included because CSV analysis does not save scoring history."
        ),
    }
