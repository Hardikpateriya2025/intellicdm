import json
import sys
from datetime import datetime, timezone, date
from decimal import Decimal
from getpass import getpass
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from app.database import SessionLocal
from app.models import Patient, Encounter, LabResult

BASE = "http://127.0.0.1:8000"
PATIENT = UUID("7e7ea970-aebb-548c-bbfd-a45730fedeaa")
CODES = {"2339-0", "38483-4"}
QUESTION = (
    "List recorded glucose and creatinine values, units, and collection dates "
    "across the recent encounters. Cite each matching lab record without "
    "medical interpretation."
)
checks = []
manual = []


def request(path, payload=None, token=None, form=False):
    headers = {}
    body = None
    if payload is not None:
        body = (
            urlencode(payload).encode()
            if form else json.dumps(payload).encode()
        )
        headers["Content-Type"] = (
            "application/x-www-form-urlencoded" if form else "application/json"
        )
    if token:
        headers["Authorization"] = "Bearer " + token
    req = Request(BASE + path, data=body, headers=headers)
    try:
        with urlopen(req, timeout=200) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def check(name, action):
    try:
        action()
        checks.append({"name": name, "passed": True})
        print("PASS:", name)
    except Exception as exc:
        checks.append({
            "name": name,
            "passed": False,
            "error": str(exc),
        })
        print("FAIL:", name, "-", exc)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


# Independent database expectations for this imported synthetic fixture.
with SessionLocal() as db:
    require(db.get(Patient, PATIENT) is not None, "Demo patient missing.")
    encounters = db.scalars(
        select(Encounter)
        .where(Encounter.patient_id == PATIENT)
        .order_by(Encounter.visited_at.desc(), Encounter.id.desc())
        .limit(3)
    ).all()
    encounter_ids = [str(row.id) for row in encounters]
    expected = {}
    for encounter in encounters:
        rows = db.scalars(
            select(LabResult)
            .where(
                LabResult.encounter_id == encounter.id,
                LabResult.test_name.in_(CODES),
            )
            .order_by(LabResult.collected_at.desc(), LabResult.id.desc())
            .limit(8)
        ).all()
        for row in rows:
            expected[str(row.id)] = {
                "encounter_id": str(row.encounter_id),
                "test_name": row.test_name,
                "value": str(row.value),
                "unit": row.unit,
                "collected_at": row.collected_at.isoformat(),
            }

    # Select a date that matches no encounters for this patient.
    earliest = db.scalar(
        select(Encounter.visited_at)
        .where(Encounter.patient_id == PATIENT)
        .order_by(Encounter.visited_at)
        .limit(1)
    )
    require(
        earliest is not None and earliest.year > 1900,
        "Fixture does not support the chosen empty date range.",
    )

require(len(expected) == 6, "Expected six fixture lab rows; inspect fixture.")
username = input("Username [hardik]: ").strip() or "hardik"
status, login = request(
    "/auth/token",
    {"username": username, "password": getpass("Password: ")},
    form=True,
)
if status != 200:
    raise SystemExit(f"Login failed: HTTP {status}")
token = login["access_token"]
path = f"/ai/patients/{PATIENT}/questions"


def expect_status(payload, expected_status, target=path, authenticated=True):
    status, result = request(
        target, payload, token if authenticated else None
    )
    require(
        status == expected_status,
        f"Expected HTTP {expected_status}, received {status}",
    )
    return result


def validate_list(result, expected_rows):
    require(
        result.get("answer_method") == "database_measurement_list",
        "Expected deterministic measurement-list route.",
    )
    rows = result.get("measurements", [])
    require(len(rows) == len(expected_rows), "Wrong measurement count.")
    require(
        {row["id"] for row in rows} == set(expected_rows),
        "Returned lab IDs differ from expected records.",
    )
    require(
        set(result["source_refs"]) == set(result["sources"]),
        "Citation/source mismatch.",
    )

    for row in rows:
        saved = expected_rows[row["id"]]
        for key in ["encounter_id", "test_name", "value", "unit"]:
            require(row[key] == saved[key], f"Incorrect {key}: {row['id']}")
        require(
            datetime.fromisoformat(row["collected_at"])
            == datetime.fromisoformat(saved["collected_at"]),
            "Incorrect collection timestamp.",
        )
        ref = row["source_ref"]
        source = result["sources"][ref]
        require(
            source["source_identifier"] == "lab:" + row["id"],
            "Incorrect source identifier.",
        )
        require(
            source["record"] == {
                key: value for key, value in row.items()
                if key != "source_ref"
            },
            "Measurement differs from cited source.",
        )
        fragment = (
            f"{row['value']} {row['unit']}; "
            f"collected at {row['collected_at']}; "
            f"encounter {row['encounter_id']} [{ref}]"
        )
        require(fragment in result["answer"], "Narrative altered or omitted a row.")

    with SessionLocal() as db:
        for row in rows:
            encounter = db.get(Encounter, UUID(row["encounter_id"]))
            require(
                encounter is not None and encounter.patient_id == PATIENT,
                "A returned lab belongs to another patient.",
            )


def multiple_encounters():
    result = expect_status({"question": QUESTION}, 200)
    require(
        result["retrieved_encounter_ids"] == encounter_ids,
        "Unexpected encounter selection.",
    )
    validate_list(result, expected)


def filtered_encounter():
    result = expect_status({
        "question": QUESTION,
        "encounter_date_from": "2023-09-24",
        "encounter_date_to": "2023-09-24",
    }, 200)
    older_id = "f4af5666-2d4a-5bdb-a486-9bccd817a101"
    require(
        result["retrieved_encounter_ids"] == [older_id],
        "Date filter selected the wrong encounter.",
    )
    selected = {
        key: row for key, row in expected.items()
        if row["encounter_id"] == older_id
    }
    require(len(selected) == 2, "Expected two records for the filtered encounter.")
    validate_list(result, selected)


def empty_range():
    result = expect_status({
        "question": QUESTION,
        "encounter_date_from": "1900-01-01",
        "encounter_date_to": "1900-01-01",
    }, 200)
    require(result["insufficient_information"] is True, "Missing-data flag absent.")
    require(
        result["retrieval_coverage"]["encounter_ids"] == [],
        "Empty range returned encounters.",
    )


check("Unauthenticated questions rejected", lambda: expect_status(
    {"question": QUESTION}, 401, authenticated=False
))
check("Six exact measurements, citations and patient ownership", multiple_encounters)
check("Encounter-date filter preserves exact records", filtered_encounter)
check("Empty date range reports missing information", empty_range)
check("Reversed dates rejected", lambda: expect_status({
    "question": QUESTION,
    "encounter_date_from": "2026-10-20",
    "encounter_date_to": "2026-10-18",
}, 422))
check("Blank question rejected", lambda: expect_status({"question": "   "}, 422))
check("Unknown request field rejected", lambda: expect_status({
    "question": QUESTION, "unexpected_field": True,
}, 422))
check("Unknown patient rejected", lambda: expect_status(
    {"question": QUESTION}, 404,
    target=f"/ai/patients/{uuid4()}/questions",
))

# LLM answers are recorded separately: successful generation is not factual accuracy.
print("\nGenerating one answer for manual factual review...")
question = (
    "Summarize the encounter reasons in the recent records. "
    "Cite the supporting encounters and do not add medical interpretation."
)
try:
    status, result = request(path, {"question": question}, token)
    manual.append({
        "question": question,
        "http_status": status,
        "response": result,
        "review_status": "pending_manual_review",
        "rubric": [
            "Every factual claim is supported by its cited record.",
            "Dates, encounter associations and values are accurate.",
            "No unsupported diagnoses or explanations are added.",
            "The answer does not imply complete patient-history coverage.",
        ],
    })
    print("Manual-review response HTTP status:", status)
    print("ANSWER:", result.get("answer", result))
except Exception as exc:
    manual.append({
        "question": question,
        "error": str(exc),
        "review_status": "generation_failed",
    })

folder = Path("ml/artifacts/qa_evaluation")
folder.mkdir(parents=True, exist_ok=True)
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
output = folder / f"report_{stamp}.json"
report = {
    "created_at": datetime.now(timezone.utc).isoformat(),
    "scope": "Development evaluation on existing synthetic fixtures.",
    "checks": checks,
    "passed": sum(item["passed"] for item in checks),
    "failed": sum(not item["passed"] for item in checks),
    "manual_review": manual,
    "limitations": (
        "Checks cover these fixtures and request formats only. "
        "Patient ownership is checked for returned measurement rows; "
        "this is not a complete cross-patient isolation evaluation. "
        "LLM factual accuracy is not automatically scored."
    ),
}
output.write_text(json.dumps(report, indent=2))
print(f"\nRESULT: {report['passed']} passed, {report['failed']} failed")
print("Saved:", output.resolve())
print("No database records were changed.")
sys.exit(1 if report["failed"] else 0)
