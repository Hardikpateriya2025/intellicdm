import logging
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AnomalyReview, AnomalyScoreHistory, User
from app.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/ml/anomaly-history/{history_id}/reviews",
    tags=["Anomaly Reviews"],
)

ReviewStatus = Literal[
    "needs_investigation",
    "confirmed_data_error",
    "reviewed_no_correction_needed",
]


class ReviewCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    status: ReviewStatus
    note: str = Field(min_length=3, max_length=5000)


class ReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    score_history_id: UUID
    status: ReviewStatus
    reviewer_name: str
    reviewer_user_id: UUID | None
    note: str
    created_at: datetime


@router.post("", response_model=ReviewRead, status_code=201)
def add_review(
    history_id: UUID,
    payload: ReviewCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Serialize review submissions for the same scoring record.
    history = db.scalar(
        select(AnomalyScoreHistory)
        .where(AnomalyScoreHistory.id == history_id)
        .with_for_update()
    )
    if history is None:
        raise HTTPException(status_code=404, detail="Scoring history not found")

    review = AnomalyReview(
        score_history_id=history_id,
        reviewer_user_id=current_user.id,
        reviewer_name=current_user.display_name,
        **payload.model_dump(),
    )

    try:
        db.add(review)
        db.flush()
        db.refresh(review)
        response = ReviewRead.model_validate(review)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Failed to save anomaly review")
        raise HTTPException(
            status_code=503,
            detail="Review could not be saved.",
        ) from None

    return response


@router.get("", response_model=list[ReviewRead])
def list_reviews(
    history_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if db.get(AnomalyScoreHistory, history_id) is None:
        raise HTTPException(status_code=404, detail="Scoring history not found")

    return db.scalars(
        select(AnomalyReview)
        .where(AnomalyReview.score_history_id == history_id)
        .order_by(AnomalyReview.created_at.desc(), AnomalyReview.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
