"""Read the immutable input snapshot associated with a saved score."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import analysis_access
from app.database import get_db
from app.models import AnomalyScoreHistory

router = APIRouter(
    tags=["Scoring Evidence"],
    dependencies=[Depends(analysis_access)],
)


@router.get("/ml/anomaly-history/{history_id}/snapshot")
def get_score_snapshot(
    history_id: UUID,
    db: Session = Depends(get_db),
):
    history = db.get(AnomalyScoreHistory, history_id)
    if history is None:
        raise HTTPException(
            status_code=404,
            detail="Scoring history not found",
        )

    return {
        "history_id": history.id,
        "encounter_id": history.encounter_id,
        "scored_at": history.created_at,
        "snapshot": history.snapshot,
    }
