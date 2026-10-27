from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AnomalyReview, AnomalyScoreHistory, Encounter

router = APIRouter(prefix="/ml", tags=["Review Queue"])


@router.get("/review-queue")
def review_queue(
    status: Literal[
        "pending",
        "unreviewed",
        "needs_investigation",
        "confirmed_data_error",
        "reviewed_no_correction_needed",
        "all",
    ] = Query(default="pending"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    ranked = select(
        AnomalyReview.id.label("review_id"),
        AnomalyReview.score_history_id,
        AnomalyReview.status.label("review_status"),
        AnomalyReview.reviewer_name,
        AnomalyReview.reviewer_user_id,
        AnomalyReview.note,
        AnomalyReview.created_at.label("reviewed_at"),
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

    statement = (
        select(
            AnomalyScoreHistory,
            Encounter.patient_id,
            latest.c.review_id,
            latest.c.review_status,
            latest.c.reviewer_name,
            latest.c.reviewer_user_id,
            latest.c.note,
            latest.c.reviewed_at,
        )
        .join(
            Encounter,
            Encounter.id == AnomalyScoreHistory.encounter_id,
        )
        .outerjoin(
            latest,
            latest.c.score_history_id == AnomalyScoreHistory.id,
        )
        .where(AnomalyScoreHistory.flagged_for_review.is_(True))
    )

    if status == "pending":
        statement = statement.where(or_(
            latest.c.review_id.is_(None),
            latest.c.review_status == "needs_investigation",
        ))
    elif status == "unreviewed":
        statement = statement.where(latest.c.review_id.is_(None))
    elif status != "all":
        statement = statement.where(latest.c.review_status == status)

    rows = db.execute(
        statement
        .order_by(
            AnomalyScoreHistory.created_at.desc(),
            AnomalyScoreHistory.id.desc(),
        )
        .offset(offset)
        .limit(limit + 1)
    ).all()

    items = []
    for row in rows[:limit]:
        score = row[0]
        items.append({
            "history_id": score.id,
            "patient_id": row.patient_id,
            "encounter_id": score.encounter_id,
            "collected_at": score.collected_at,
            "scored_at": score.created_at,
            "model_version": score.model_version,
            "scoring_version": score.scoring_version,
            "anomaly_score": score.anomaly_score,
            "threshold": score.threshold,
            "flagged_for_review": score.flagged_for_review,
            "review_status": row.review_status or "unreviewed",
            "latest_review": None if row.review_id is None else {
                "id": row.review_id,
                "status": row.review_status,
                "reviewer_name": row.reviewer_name,
                "note": row.note,
                "created_at": row.reviewed_at,
                "reviewer_user_id": row.reviewer_user_id,
                "reviewer_account_authenticated": (
                    row.reviewer_user_id is not None
                ),
                "attribution": (
                    "authenticated_account"
                    if row.reviewer_user_id is not None
                    else "legacy_self_reported"
                ),
                "reviewer_identity_verified": False,
            },
        })

    return {
        "status_filter": status,
        "limit": limit,
        "offset": offset,
        "returned": len(items),
        "has_more": len(rows) > limit,
        "items": items,
        "scope": (
            "Flagged scoring-history records, newest first. "
            "Repeated scores are separate entries. Reviews apply "
            "only to their exact scoring-history record."
        ),
        "notice": (
            "Pending means unreviewed or needs_investigation. "
            "Review status does not establish a diagnosis."
        ),
    }
