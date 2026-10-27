import json
from getpass import getpass
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from uuid import uuid4

BASE = "http://127.0.0.1:8000"
token = None
passed = 0

def call(path, authenticated=True, form=None):
    headers = {}
    body = None
    if authenticated and token:
        headers["Authorization"] = f"Bearer {token}"
    if form is not None:
        body = urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = Request(
        BASE + path,
        data=body,
        headers=headers,
        method="POST" if form is not None else "GET",
    )
    try:
        with urlopen(req, timeout=30) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"detail": raw}
    except (URLError, TimeoutError) as exc:
        raise SystemExit(f"Backend connection failed: {exc}")

def check(condition, label, detail=None):
    global passed
    if not condition:
        raise SystemExit(
            f"FAIL: {label}\n"
            + json.dumps(detail, indent=2, default=str)
        )
    passed += 1
    print("PASS:", label)

def read(path):
    status, data = call(path)
    check(status == 200, f"GET {path}", data)
    return data

status, data = call("/health", authenticated=False)
check(status == 200 and data.get("service") == "IntelliCDM",
      "Correct backend is running", data)

for path in ["/dashboard", "/patients", "/admin/users", "/ml/review-queue"]:
    status, data = call(path, authenticated=False)
    check(status == 401, f"Authentication required: {path}", data)

username = input("Username: ").strip()
password = getpass("Password (hidden): ")
status, data = call(
    "/auth/token",
    authenticated=False,
    form={"username": username, "password": password},
)
password = None
check(status == 200, "Login", data)
token = data["access_token"]

user = read("/auth/me")
print("Signed-in role:", user["role"])

dashboard = read("/dashboard")
keys = ["patients", "encounters", "lab_results",
        "scoring_records", "pending_reviews"]
check(
    all(type(dashboard.get("counts", {}).get(key)) is int
        and dashboard["counts"][key] >= 0 for key in keys),
    "Dashboard count format",
    dashboard,
)

status, accounts = call("/admin/users?limit=5&offset=0")
if user["role"] == "admin":
    check(status == 200 and isinstance(accounts.get("items"), list),
          "Admin can list accounts", accounts)
    check(
        all("password" not in item and "password_hash" not in item
            for item in accounts["items"]),
        "Account list excludes password fields",
    )
else:
    check(status == 403, "Non-admin cannot list accounts", accounts)

patients = read("/patients?limit=5&offset=0")
check(isinstance(patients, list), "Patient-list format")

if patients:
    patient_id = patients[0]["id"]
    encounters = read(f"/patients/{patient_id}/encounters?limit=5&offset=0")
    check(
        all(item["patient_id"] == patient_id for item in encounters),
        "Encounter list stays within selected patient",
    )

    trend = read(f"/ai/patients/{patient_id}/lab-trends/glucose")
    check(
        trend.get("patient_id") == patient_id
        and trend.get("feature") == "glucose"
        and isinstance(trend.get("series_by_unit"), list),
        "Trend response matches selected patient and measurement",
    )

    if encounters:
        encounter_id = encounters[0]["id"]
        labs = read(f"/encounters/{encounter_id}/labs?limit=5&offset=0")
        check(
            all(item["encounter_id"] == encounter_id for item in labs),
            "Lab list stays within selected encounter",
        )
        read(f"/ml/encounters/{encounter_id}/anomaly-history?limit=5&offset=0")
else:
    print("SKIP: No patients available for patient-specific checks.")

queue = read("/ml/review-queue?status=all&limit=5&offset=0")
check(isinstance(queue.get("items"), list), "Review-queue format")

if queue["items"]:
    item = queue["items"][0]
    history_id = item["history_id"]
    evidence = read(f"/ml/anomaly-history/{history_id}/snapshot")
    check(
        evidence.get("history_id") == history_id
        and evidence.get("encounter_id") == item["encounter_id"],
        "Evidence matches the selected score and encounter",
    )
    check(
        isinstance(evidence.get("snapshot"), dict),
        "Saved snapshot is present",
    )

    reviews = read(f"/ml/anomaly-history/{history_id}/reviews?limit=5")
    check(
        all(review["score_history_id"] == history_id for review in reviews),
        "Reviews belong to the selected scoring record",
    )
else:
    print("SKIP: No flagged scoring records available to inspect.")

status, data = call(f"/ml/anomaly-history/{uuid4()}/snapshot")
check(status == 404, "Unknown scoring record returns 404", data)

print(f"\nCOMPLETE: {passed} checks passed.")
print("No database records were changed.")
print("These checks do not evaluate AI accuracy or browser interactions.")
