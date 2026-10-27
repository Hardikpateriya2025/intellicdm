from functools import lru_cache
from pathlib import Path
import json
import logging

import joblib
import numpy as np
import pandas as pd
import torch
from torch import nn
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

router = APIRouter(prefix="/ml", tags=["ML Anomaly Detection"])
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "ml/artifacts/synthea_autoencoder_v1"
V2_ARTIFACTS = ROOT / "ml/artifacts/synthea_feature_score_v2"


class ChemistryPanel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    glucose: float
    creatinine: float
    urea_nitrogen: float
    sodium: float
    potassium: float
    chloride: float
    calcium: float
    total_co2: float


class AnomalyResult(BaseModel):
    model_version: str
    scoring_version: str
    anomaly_score: float
    threshold: float
    synthetic_reference_percentile: float
    reference_panel_count: int
    largest_error_feature: str
    adjusted_feature_errors: dict[str, float]
    ml_flagged: bool
    data_quality_issues: list[str]
    flagged_for_review: bool
    units: dict[str, str]
    interpretation: str
    known_limitations: list[str]


# Preserve this helper for the existing evaluation scripts.
@lru_cache(maxsize=1)
def load_artifacts():
    config = json.loads((ARTIFACTS / "config.json").read_text())
    scaler = joblib.load(ARTIFACTS / "scaler.joblib")

    if set(config["features"]) != set(ChemistryPanel.model_fields):
        raise ValueError("Model features do not match API fields")

    widths = config["architecture"]
    layers = []
    for i in range(len(widths) - 1):
        layers.append(nn.Linear(widths[i], widths[i + 1]))
        if i < len(widths) - 2:
            layers.append(nn.ReLU())

    model = nn.Sequential(*layers)
    model.load_state_dict(torch.load(
        ARTIFACTS / "autoencoder_weights.pt",
        map_location="cpu",
        weights_only=True,
    ))
    model.eval()
    return config, scaler, model


@lru_cache(maxsize=1)
def load_v2():
    config, _, _ = load_artifacts()
    v2 = json.loads((V2_ARTIFACTS / "scoring_config.json").read_text())

    if v2["features"] != config["features"]:
        raise ValueError("Version-2 feature order mismatch")
    if v2["base_model"] != "synthea_autoencoder_v1":
        raise ValueError("Unexpected base model")

    scales = np.asarray(v2["feature_error_scales"], dtype=float)
    if (
        scales.shape != (len(config["features"]),)
        or not np.isfinite(scales).all()
        or (scales <= 0).any()
    ):
        raise ValueError("Invalid feature-error scales")

    threshold = float(v2["threshold"])
    if not np.isfinite(threshold) or threshold < 0:
        raise ValueError("Invalid version-2 threshold")

    reference = np.load(
        V2_ARTIFACTS / "validation_reference_scores.npy",
        allow_pickle=False,
    )
    if (
        reference.ndim != 1
        or reference.size == 0
        or not np.isfinite(reference).all()
    ):
        raise ValueError("Invalid version-2 reference")

    return v2, scales, np.sort(reference)


@router.post(
    "/anomaly-score",
    response_model=AnomalyResult,
    description=(
        "Version-2 synthetic-data scoring. Supply glucose, creatinine, "
        "urea_nitrogen and calcium in mg/dL; sodium, potassium, chloride "
        "and total_co2 in mmol/L. Percentiles are not probabilities. "
        "All eight measurements are required."
    ),
)
def score_panel(payload: ChemistryPanel):
    try:
        config, scaler, model = load_artifacts()
        v2, scales, reference = load_v2()
    except Exception:
        logger.exception("Unable to load ML artifacts")
        raise HTTPException(
            status_code=503,
            detail="ML artifacts unavailable. Check backend logs.",
        ) from None

    values = payload.model_dump()
    issues = [
        f"{name}: negative concentration; verify source value and units."
        for name, value in values.items()
        if value < 0
    ]

    frame = pd.DataFrame([values], columns=config["features"])
    with np.errstate(over="ignore", invalid="ignore"):
        scaled = scaler.transform(frame).astype("float32")

    if not np.isfinite(scaled).all():
        raise HTTPException(
            status_code=422,
            detail="Input values exceed numerical limits.",
        )

    with torch.inference_mode():
        tensor = torch.from_numpy(scaled)
        errors = ((model(tensor) - tensor) ** 2).numpy()[0]

    adjusted = errors / scales
    if not np.isfinite(adjusted).all():
        raise HTTPException(
            status_code=422,
            detail="Could not compute finite reconstruction errors.",
        )

    score = float(adjusted.max())
    threshold = float(v2["threshold"])
    ml_flagged = score >= threshold

    below = int(np.searchsorted(reference, score, side="left"))
    at_or_below = int(np.searchsorted(reference, score, side="right"))
    percentile = 100 * (below + at_or_below) / (2 * len(reference))

    return AnomalyResult(
        model_version="synthea_autoencoder_v1",
        scoring_version=v2["version"],
        anomaly_score=score,
        threshold=threshold,
        synthetic_reference_percentile=round(percentile, 2),
        reference_panel_count=len(reference),
        largest_error_feature=config["features"][int(adjusted.argmax())],
        adjusted_feature_errors={
            name: float(value)
            for name, value in zip(config["features"], adjusted)
        },
        ml_flagged=ml_flagged,
        data_quality_issues=issues,
        flagged_for_review=ml_flagged or bool(issues),
        units=config["units"],
        interpretation=(
            "Score is the largest adjusted per-feature reconstruction "
            "error. Percentile compares it with synthetic validation "
            "panels; it is not a probability. The largest-error feature "
            "is not a proven cause. An unflagged panel does not establish "
            "clinical normality."
        ),
        known_limitations=[
            "Evaluated on synthetic data, not clinically validated.",
            "Poor detection of simulated creatinine divide-by-10 errors.",
            "Units must match the documented input units.",
        ],
    )


from datetime import timezone
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Encounter, LabResult


@router.post("/encounters/{encounter_id}/anomaly-score")
def score_saved_encounter(
    encounter_id: UUID,
    db: Session = Depends(get_db),
):
    encounter = db.get(Encounter, encounter_id)
    if encounter is None:
        raise HTTPException(status_code=404, detail="Encounter not found")

    try:
        config, _, _ = load_artifacts()
    except Exception:
        logger.exception("Unable to load model configuration")
        raise HTTPException(
            status_code=503, detail="ML model unavailable"
        ) from None

    # Explicit aliases only: no fuzzy matching across specimen types.
    descriptions = {
        "glucose": "Glucose [Mass/volume] in Blood",
        "creatinine": "Creatinine [Mass/volume] in Blood",
        "urea_nitrogen": "Urea nitrogen [Mass/volume] in Blood",
        "sodium": "Sodium [Moles/volume] in Blood",
        "potassium": "Potassium [Moles/volume] in Blood",
        "chloride": "Chloride [Moles/volume] in Blood",
        "calcium": "Calcium [Mass/volume] in Blood",
        "total_co2": "Carbon dioxide  total [Moles/volume] in Blood",
    }

    def normalize(text):
        return " ".join(text.strip().casefold().split())

    aliases = {}
    for feature in config["features"]:
        for alias in [
            feature,
            config["codes"][feature],
            descriptions[feature],
        ]:
            aliases[normalize(alias)] = feature

    results = db.scalars(
        select(LabResult)
        .where(LabResult.encounter_id == encounter_id)
        .order_by(LabResult.collected_at.desc(), LabResult.id)
        .limit(10001)
    ).all()

    if len(results) > 10000:
        raise HTTPException(
            status_code=422,
            detail="Encounter exceeds 10,000 lab rows; use a bounded panel query.",
        )
    if not results:
        raise HTTPException(
            status_code=422, detail="No saved lab results for this encounter"
        )

    groups = {}
    for result in results:
        feature = aliases.get(normalize(result.test_name))
        if feature is None:
            continue

        timestamp = result.collected_at.astimezone(timezone.utc)
        groups.setdefault(timestamp, {}).setdefault(feature, []).append(result)

    if not groups:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "No supported blood chemistry measurements found",
                "accepted_feature_names": config["features"],
                "accepted_test_codes": config["codes"],
                "required_units": config["units"],
            },
        )

    diagnostics = []
    for timestamp in sorted(groups, reverse=True):
        group = groups[timestamp]
        missing = [f for f in config["features"] if f not in group]
        issues = []
        values = {}
        source_ids = {}

        for feature, records in group.items():
            expected_unit = config["units"][feature]
            if any(r.unit.strip() != expected_unit for r in records):
                issues.append(f"{feature}: expected unit {expected_unit}")
                continue

            distinct = {r.value for r in records}
            if len(distinct) != 1:
                issues.append(f"{feature}: conflicting duplicate values")
                continue

            value = float(records[0].value)
            if not np.isfinite(value):
                issues.append(f"{feature}: non-finite value")
                continue

            values[feature] = value
            source_ids[feature] = [str(r.id) for r in records]

        if not missing and not issues:
            scored = score_panel(ChemistryPanel(**values))
            return save_score_history(db, {
                "encounter_id": str(encounter_id),
                "patient_id": str(encounter.patient_id),
                "collected_at": timestamp.isoformat(),
                "selection": "latest_complete_valid_panel",
                "newer_unusable_panel_count": len(diagnostics),
                "newer_unusable_panels": diagnostics[:5],
                "source_lab_result_ids": source_ids,
                "input_measurements": values,
                "result": scored.model_dump(),
            })

        diagnostics.append({
            "collected_at": timestamp.isoformat(),
            "missing_features": missing,
            "issues": issues,
        })

    raise HTTPException(
        status_code=422,
        detail={
            "message": "No complete compatible panel at a single collection time",
            "required_units": config["units"],
            "recent_panel_diagnostics": diagnostics[:5],
        },
    )


from datetime import datetime
from fastapi import Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy.exc import SQLAlchemyError
from app.models import AnomalyScoreHistory


def save_score_history(db: Session, payload: dict):
    snapshot = jsonable_encoder(payload)
    result = snapshot["result"]

    record = AnomalyScoreHistory(
        encounter_id=UUID(snapshot["encounter_id"]),
        collected_at=datetime.fromisoformat(snapshot["collected_at"]),
        model_version=result["model_version"],
        scoring_version=result["scoring_version"],
        anomaly_score=result["anomaly_score"],
        threshold=result["threshold"],
        flagged_for_review=result["flagged_for_review"],
        snapshot=snapshot,
    )

    try:
        db.add(record)
        db.flush()
        db.refresh(record)
        history_id = str(record.id)
        scored_at = record.created_at.isoformat()
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Could not save scoring history")
        raise HTTPException(
            status_code=503,
            detail="Scoring history could not be saved.",
        ) from None

    return {
        **snapshot,
        "history_id": history_id,
        "scored_at": scored_at,
    }


@router.get("/encounters/{encounter_id}/anomaly-history")
def list_score_history(
    encounter_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if db.get(Encounter, encounter_id) is None:
        raise HTTPException(status_code=404, detail="Encounter not found")

    records = db.scalars(
        select(AnomalyScoreHistory)
        .where(AnomalyScoreHistory.encounter_id == encounter_id)
        .order_by(
            AnomalyScoreHistory.created_at.desc(),
            AnomalyScoreHistory.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    ).all()

    return [
        {
            "history_id": str(record.id),
            "scored_at": record.created_at,
            "snapshot": record.snapshot,
        }
        for record in records
    ]
