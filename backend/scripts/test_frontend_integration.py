import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from getpass import getpass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

BASE = "http://127.0.0.1:8000"
token = None


def request(path, payload=None, method="GET", authenticated=True, form=False):
    headers = {}
    if authenticated and token:
        headers["Authorization"] = f"Bearer {token}"

    body = None
    if payload is not None:
        if form:
            body = urlencode(payload).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"

    req = Request(BASE + path, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=30) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        raw = exc.read().decode()
        try:
            result = json.loads(raw)
        except ValueError:
            result = {"detail": raw}
        return exc.code, result
    except (URLError, TimeoutError) as exc:
        raise SystemExit(f"Connection failed. Check the backend terminal: {exc}")


def expect(status, expected, result, label):
    if status != expected:
        raise SystemExit(
            f"FAIL: {label}\nExpected HTTP {expected}; received {status}\n"
            + json.dumps(result, indent=2)
        )
    print("PASS:", label)


status, result = request("/health", authenticated=False)
expect(status, 200, result, "Backend responds")

status, result = request("/dashboard", authenticated=False)
expect(status, 401, result, "Dashboard rejects unauthenticated requests")

username = input("Admin or doctor username: ").strip()
password = getpass("Password (hidden): ")

status, result = request(
    "/auth/token",
    {"username": username, "password": password},
    method="POST",
    authenticated=False,
    form=True,
)
password = None
expect(status, 200, result, "Login")
token = result["access_token"]

status, user = request("/auth/me")
expect(status, 200, user, "Authenticated account")
if user["role"] not in {"admin", "doctor"}:
    raise SystemExit("Use an admin or doctor account for these checks.")

status, dashboard = request("/dashboard")
expect(status, 200, dashboard, "Dashboard loads")
for key in [
    "patients", "encounters", "lab_results",
    "scoring_records", "pending_reviews",
]:
    value = dashboard["counts"].get(key)
    assert type(value) is int and value >= 0, (key, value)
print("PASS: Dashboard counts have the expected format")

suffix = uuid4().hex[:12]
status, patient = request(
    "/patients",
    {
        "medical_record_number": f"UI-TEST-{suffix}",
        "first_name": "Synthetic",
        "last_name": f"Integration-{suffix}",
        "date_of_birth": "2000-01-01",
    },
    method="POST",
)
expect(status, 201, patient, "Synthetic patient created")
patient_id = patient["id"]
print("Test patient ID:", patient_id)

visited = datetime.now(timezone.utc) - timedelta(days=2)
collected = visited + timedelta(minutes=15)

status, encounter = request(
    f"/patients/{patient_id}/encounters",
    {
        "visited_at": visited.isoformat(),
        "reason": "Synthetic frontend integration test",
        "notes": "Development fixture only. Not a clinical assessment.",
    },
    method="POST",
)
expect(status, 201, encounter, "Encounter created")
encounter_id = encounter["id"]
print("Test encounter ID:", encounter_id)

panel = {
    "collected_at": collected.isoformat(),
    "glucose": "100",
    "creatinine": "0.9",
    "urea_nitrogen": "14",
    "sodium": "140",
    "potassium": "4.2",
    "chloride": "103",
    "calcium": "9.5",
    "total_co2": "25",
}
panel_path = f"/encounters/{encounter_id}/chemistry-panel"
labs_path = f"/encounters/{encounter_id}/labs?limit=100"

invalid = dict(panel)
invalid.pop("potassium")
status, result = request(panel_path, invalid, method="POST")
expect(status, 422, result, "Incomplete panel rejected")

status, rows = request(labs_path)
expect(status, 200, rows, "Lab listing loads")
assert rows == [], rows
print("PASS: Rejected panel created no lab rows")

status, saved = request(panel_path, panel, method="POST")
expect(status, 201, saved, "Complete chemistry panel saved")
assert len(saved) == 8, saved

expected_units = {
    "glucose": "mg/dL",
    "creatinine": "mg/dL",
    "urea_nitrogen": "mg/dL",
    "sodium": "mmol/L",
    "potassium": "mmol/L",
    "chloride": "mmol/L",
    "calcium": "mg/dL",
    "total_co2": "mmol/L",
}

status, rows = request(labs_path)
expect(status, 200, rows, "Saved panel retrieved")
assert len(rows) == 8, rows
assert {row["test_name"] for row in rows} == set(expected_units), rows

for row in rows:
    name = row["test_name"]
    assert Decimal(str(row["value"])) == Decimal(panel[name]), row
    assert row["unit"] == expected_units[name], row
    assert row["encounter_id"] == encounter_id, row
    assert datetime.fromisoformat(
        row["collected_at"].replace("Z", "+00:00")
    ) == collected, row
print("PASS: All eight values, units, timestamps and encounter links preserved")

status, result = request(panel_path, panel, method="POST")
expect(status, 409, result, "Duplicate collection-time panel rejected")

status, rows = request(labs_path)
expect(status, 200, rows, "Lab listing remains accessible")
assert len(rows) == 8, rows
print("PASS: Duplicate attempt added no rows")

status, trend = request(
    f"/ai/patients/{patient_id}/lab-trends/glucose"
)
expect(status, 200, trend, "Glucose trend endpoint")
series = next(
    item for item in trend["series_by_unit"]
    if item["unit"] == "mg/dL"
)
assert len(series["points"]) == 1, series
assert Decimal(str(series["points"][0]["value"])) == Decimal("100"), series
assert series["latest_minus_earliest"] is None, series
print("PASS: Single measurement has no invented trend change")

status, result = request(
    f"/encounters/{uuid4()}/chemistry-panel",
    panel,
    method="POST",
)
expect(status, 404, result, "Unknown encounter rejected")

print("\nALL CHECKS PASSED")
print("Search the frontend for:", patient["medical_record_number"])
print("Created: 1 synthetic patient, 1 encounter, 8 lab results.")
print("These test records remain saved.")
print("No training, scoring or reviews were performed.")
