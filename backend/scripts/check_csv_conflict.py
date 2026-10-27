import csv
import getpass
import io
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

BASE = "http://127.0.0.1:8000"
path = Path.home() / "Desktop/intellicdm-patient-import-demo.csv"

def request(endpoint, data=None, headers=None):
    req = Request(BASE + endpoint, data=data, headers=headers or {})
    try:
        with urlopen(req, timeout=120) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())

original = path.read_bytes()
reader = csv.DictReader(io.StringIO(original.decode("utf-8-sig")))
fields = reader.fieldnames
rows = list(reader)
assert len(rows) == 2, "Expected the original two-row demo CSV."

username = input("Admin or doctor username: ").strip()
password = getpass.getpass("Password: ")

status, login = request(
    "/auth/token",
    urlencode({"username": username, "password": password}).encode(),
    {"Content-Type": "application/x-www-form-urlencoded"},
)
del password
assert status == 200, login
auth = {"Authorization": "Bearer " + login["access_token"]}

status, before = request("/dashboard", headers=auth)
assert status == 200, before

# Deliberately conflict with the already-saved second panel.
rows[1]["glucose"] = "123" if rows[1]["glucose"] != "123" else "124"

buffer = io.StringIO(newline="")
writer = csv.DictWriter(buffer, fieldnames=fields)
writer.writeheader()
writer.writerows(rows)

boundary = "IntelliCDM" + uuid4().hex
body = (
    f"--{boundary}\r\n"
    'Content-Disposition: form-data; name="units_confirmed"\r\n\r\n'
    "true\r\n"
    f"--{boundary}\r\n"
    'Content-Disposition: form-data; name="file"; filename="conflict-test.csv"\r\n'
    "Content-Type: text/csv\r\n\r\n"
).encode() + buffer.getvalue().encode() + (
    f"\r\n--{boundary}--\r\n"
).encode()

status, result = request(
    "/csv/patient-records/save",
    body,
    {
        **auth,
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    },
)

assert status == 409, (
    f"Expected conflict rejection, received HTTP {status}: {result}"
)
print("PASS: Conflicting saved measurement rejected.")
print("Server explanation:", result.get("detail"))

status, after = request("/dashboard", headers=auth)
assert status == 200, after

for key in ("patients", "encounters", "lab_results"):
    assert before["counts"][key] == after["counts"][key], (
        f"Unexpected change in {key} count."
    )

assert path.read_bytes() == original
print("PASS: Patient, visit and lab counts are unchanged.")
print("PASS: Original CSV file is unchanged.")
print("\nConflict-rejection checks passed.")
