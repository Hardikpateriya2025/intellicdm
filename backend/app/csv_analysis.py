"""Bounded CSV validation and scoring; no clinical-record writes."""
import csv
import io
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.auth import analysis_access
from app.ml import ChemistryPanel, score_panel

router = APIRouter(
    prefix="/ml/csv",
    tags=["CSV Analysis"],
    dependencies=[Depends(analysis_access)],
)

FEATURES = list(ChemistryPanel.model_fields)
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000


def validate_input(values):
    try:
        panel = ChemistryPanel.model_validate(values)
        return panel, []
    except ValidationError as exc:
        messages = [
            f"{'.'.join(map(str, item['loc']))}: {item['msg']}"
            for item in exc.errors(include_input=False, include_url=False)
        ]
        return None, messages


@router.post("/preview")
async def preview_csv(file: UploadFile = File(...)):
    try:
        raw = await file.read(MAX_BYTES + 1)
    finally:
        await file.close()

    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="CSV must be at most 2 MiB.")

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=422, detail="Use a UTF-8 CSV file."
        ) from None

    if "\x00" in text:
        raise HTTPException(status_code=422, detail="CSV contains invalid null bytes.")

    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        headers = next(reader, None)
        if not headers:
            raise HTTPException(status_code=422, detail="CSV is empty.")

        headers = [name.strip() for name in headers]
        if any(not name for name in headers) or len(set(headers)) != len(headers):
            raise HTTPException(
                status_code=422, detail="CSV headers must be nonempty and unique."
            )
        if len(headers) > 50:
            raise HTTPException(status_code=422, detail="CSV has too many columns.")

        missing = [name for name in FEATURES if name not in headers]
        if missing:
            raise HTTPException(
                status_code=422,
                detail="Missing measurement columns: " + ", ".join(missing),
            )

        rows = []
        for record_number, cells in enumerate(reader, start=1):
            if not cells or all(not cell.strip() for cell in cells):
                continue
            if len(rows) >= MAX_ROWS:
                raise HTTPException(
                    status_code=422,
                    detail=f"CSV exceeds {MAX_ROWS} nonempty data rows.",
                )
            if len(cells) != len(headers):
                raise HTTPException(
                    status_code=422,
                    detail=f"Data record {record_number} has the wrong number of columns.",
                )
            if any(len(cell) > 1000 for cell in cells):
                raise HTTPException(
                    status_code=422,
                    detail=f"Data record {record_number} contains an oversized field.",
                )

            record = dict(zip(headers, cells))
            values = {name: record[name].strip() for name in FEATURES}
            _, errors = validate_input(values)
            rows.append({
                "row_number": record_number,
                "case_id": record.get("case_id", "")[:200],
                "values": values,
                "validation_errors": errors,
            })
    except csv.Error:
        raise HTTPException(
            status_code=422, detail="Malformed CSV. Check quoting and delimiters."
        ) from None

    if not rows:
        raise HTTPException(status_code=422, detail="CSV has no data rows.")

    return {
        "rows": rows,
        "features": FEATURES,
        "ignored_columns": [name for name in headers if name not in FEATURES],
        "row_count": len(rows),
        "valid_count": sum(not row["validation_errors"] for row in rows),
        "notice": (
            "Extra columns are not model inputs. Units must match the displayed "
            "requirements. Uploaded rows are not saved as patient records."
        ),
    }


class BatchRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row_number: int = Field(ge=1)
    values: dict[str, str] = Field(max_length=8)


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[BatchRow] = Field(min_length=1, max_length=25)


@router.post("/score")
def score_csv_batch(payload: BatchRequest):
    output: list[dict[str, Any]] = []

    for row in payload.rows:
        if any(len(value) > 1000 for value in row.values.values()):
            output.append({
                "row_number": row.row_number,
                "status": "invalid",
                "errors": ["A measurement field exceeds 1000 characters."],
            })
            continue

        panel, errors = validate_input(row.values)
        if errors:
            output.append({
                "row_number": row.row_number,
                "status": "invalid",
                "errors": errors,
            })
            continue

        try:
            result = score_panel(panel)
        except HTTPException as exc:
            if exc.status_code == 422:
                output.append({
                    "row_number": row.row_number,
                    "status": "invalid",
                    "errors": [str(exc.detail)],
                })
                continue
            raise

        output.append({
            "row_number": row.row_number,
            "status": "scored",
            "result": result.model_dump(mode="json"),
        })

    return {
        "rows": output,
        "notice": "Scoring only. No patient, lab, scoring-history or review records were created.",
    }
