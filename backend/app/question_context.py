import re
from sqlalchemy import func
from app.trends import ALIASES
from datetime import datetime, time, timedelta, timezone
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from app.ai import lab_display_name
from app.models import (
    Patient, Encounter, LabResult,
    AnomalyScoreHistory, AnomalyReview,
)


def build_question_records(patient_id, db, date_from=None, date_to=None, question=''):
    if db.get(Patient, patient_id) is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Inclusive calendar dates interpreted in India time.
    india = timezone(timedelta(hours=5, minutes=30))
    conditions = [Encounter.patient_id == patient_id]
    if date_from is not None:
        conditions.append(
            Encounter.visited_at >= datetime.combine(
                date_from, time.min, tzinfo=india
            )
        )
    if date_to is not None:
        conditions.append(
            Encounter.visited_at < datetime.combine(
                date_to, time.max, tzinfo=india
            ) + timedelta(microseconds=1)
        )

    encounters = db.scalars(
        select(Encounter)
        .where(*conditions)
        .order_by(Encounter.visited_at.desc(), Encounter.id.desc())
        .limit(4)
    ).all()

    selected = encounters[:3]
    coverage = {
        "description": (
            "Up to 3 most recent encounters matching the encounter-date filters; up to 8 most recent lab "
            "rows per encounter; latest score and its latest review "
            "per encounter. This is not the complete patient history."
        ),
        "older_encounters_omitted": len(encounters) > 3,
        "encounter_date_filter": {
            "from": date_from.isoformat() if date_from else None,
            "to": date_to.isoformat() if date_to else None,
            "timezone": "Asia/Kolkata",
            "meaning": "Inclusive encounter dates, not lab collection dates",
        },
        "encounter_ids": [str(e.id) for e in selected],
        "encounters": [],
        "diagnosis_information": (
            "No structured diagnosis records are included."
        ),
    }

    def normalize(value):
        return " ".join(value.casefold().replace("_", " ").split())

    normalized_question = normalize(question)
    selected_features = []
    accepted_names = set()

    for feature, aliases in ALIASES.items():
        # Recognize feature names, codes and explicit display names.
        terms = aliases + [feature, lab_display_name(feature)]
        if any(
            re.search(
                r"(?<!\\w)" + re.escape(normalize(term)) + r"(?!\\w)",
                normalized_question,
            )
            for term in terms
        ):
            selected_features.append(feature)
            accepted_names.update(
                " ".join(alias.casefold().split()) for alias in aliases
            )

    coverage["measurement_filter_applied"] = bool(selected_features)
    coverage["selected_measurements"] = selected_features
    coverage["lab_selection"] = (
        "Only explicitly matched test names/codes; units are not converted."
        if selected_features else
        "No supported measurement named; using recent lab rows."
    )
    if selected_features:
        coverage["description"] += (
            " Lab rows are restricted to the named measurements: "
            + ", ".join(selected_features) + "."
        )
    coverage["lab_limit_meaning"] = (
        "Eight rows total per encounter across selected measurements, "
        "not eight per measurement."
    )

    records = {"coverage": coverage}

    for encounter in selected:
        eid = str(encounter.id)
        records["encounter:" + eid] = {
            "id": eid,
            "visited_at": encounter.visited_at,
            "reason": encounter.reason,
            "notes": encounter.notes,
        }

        lab_conditions = [LabResult.encounter_id == encounter.id]
        if selected_features:
            normalized_test_name = func.lower(
                func.regexp_replace(
                    func.trim(LabResult.test_name), r"\s+", " ", "g"
                )
            )
            lab_conditions.append(normalized_test_name.in_(accepted_names))

        labs = db.scalars(
            select(LabResult)
            .where(*lab_conditions)
            .order_by(LabResult.collected_at.desc(), LabResult.id.desc())
            .limit(9)
        ).all()

        coverage["encounters"].append({
            "encounter_id": eid,
            "returned_lab_rows": min(len(labs), 8),
            "older_lab_rows_omitted": len(labs) > 8,
        })

        for lab in labs[:8]:
            records["lab:" + str(lab.id)] = {
                "id": lab.id,
                "encounter_id": eid,
                "test_name": lab.test_name,
                "display_name": lab_display_name(lab.test_name),
                "value": str(lab.value),
                "unit": lab.unit,
                "collected_at": lab.collected_at,
            }

        history = db.scalar(
            select(AnomalyScoreHistory)
            .where(AnomalyScoreHistory.encounter_id == encounter.id)
            .order_by(
                AnomalyScoreHistory.created_at.desc(),
                AnomalyScoreHistory.id.desc(),
            )
            .limit(1)
        )

        review = None
        if history is not None:
            result = history.snapshot["result"]
            records["score:" + str(history.id)] = {
                "history_id": history.id,
                "encounter_id": eid,
                "scored_at": history.created_at,
                "panel_collected_at": history.collected_at,
                "model_version": history.model_version,
                "scoring_version": history.scoring_version,
                "anomaly_score": history.anomaly_score,
                "threshold": history.threshold,
                "flagged_for_review": history.flagged_for_review,
                "largest_reconstruction_discrepancy": result.get(
                    "largest_error_feature"
                ),
                "input_measurements": history.snapshot.get(
                    "input_measurements"
                ),
                "units": result.get("units"),
                "limitations": result.get("known_limitations", []),
                "meaning": (
                    "Historical panel score, not a diagnosis. "
                    "Largest discrepancy does not identify a proven error."
                ),
            }

            review = db.scalar(
                select(AnomalyReview)
                .where(AnomalyReview.score_history_id == history.id)
                .order_by(
                    AnomalyReview.created_at.desc(),
                    AnomalyReview.id.desc(),
                )
                .limit(1)
            )

        records["review_status:" + eid] = {
            "encounter_id": eid,
            "selected_history_id": str(history.id) if history else None,
            "score_recorded": history is not None,
            "review_status": review.status if review else "not_recorded",
            "scope": "Latest review of this encounter's selected score only",
        }

        if review is not None:
            records["review:" + str(review.id)] = {
                "review_id": review.id,
                "score_history_id": review.score_history_id,
                "encounter_id": eid,
                "status": review.status,
                "reviewer_name": review.reviewer_name,
                "reviewer_user_id": review.reviewer_user_id,
                "reviewer_account_authenticated": review.reviewer_user_id is not None,
                "attribution": (
                    "authenticated_account"
                    if review.reviewer_user_id is not None
                    else "legacy_self_reported"
                ),
                "note": review.note,
                "created_at": review.created_at,
                "reviewer_identity_verified": False,
            }

    # Serialize before releasing the database transaction.
    records = jsonable_encoder(records)
    coverage = records["coverage"]
    db.rollback()
    return records, coverage
