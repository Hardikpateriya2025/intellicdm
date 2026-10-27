import getpass
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

BASE = "http://127.0.0.1:8000"
file = Path.home() / "Desktop/intellicdm-patient-import-demo.csv"

if not file.exists():
    raise SystemExit(f"CSV not found: {file}")

def request(path, data=None, headers=None):
    req = Request(BASE + path, data=data, headers=headers or {})
    try:
        with urlopen(req, timeout=120) as response:
            return json.load(response)
    except HTTPError as exc:
        raise SystemExit(f"HTTP {exc.code}: {exc.read().decode()}")

username = input("Admin or doctor username: ").strip()
password = getpass.getpass("Password: ")

login = request(
    "/auth/token",
    urlencode({"username": username, "password": password}).encode(),
    {"Content-Type": "application/x-www-form-urlencoded"},
)
del password
auth = {"Authorization": "Bearer " + login["access_token"]}

before = request("/dashboard", headers=auth)

boundary = "IntelliCDM" + uuid4().hex
body = (
    f"--{boundary}\r\n"
    'Content-Disposition: form-data; name="units_confirmed"\r\n\r\n'
    "true\r\n"
    f"--{boundary}\r\n"
    'Content-Disposition: form-data; name="file"; filename="demo.csv"\r\n'
    "Content-Type: text/csv\r\n\r\n"
).encode() + file.read_bytes() + f"\r\n--{boundary}--\r\n".encode()

result = request(
    "/csv/patient-records/save",
    body,
    {
        **auth,
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    },
)

print("\nSave result:")
print(json.dumps(result, indent=2))

assert result["created"] == {
    "patients": 0,
    "encounters": 0,
    "lab_results": 0,
}, "New records were created. Confirm this exact CSV was previously saved."

assert result["reused_panels"] == 2, result

after = request("/dashboard", headers=auth)
for key in ("patients", "encounters", "lab_results"):
    assert before["counts"][key] == after["counts"][key], (
        f"{key} count changed."
    )

print("\nPASS: Both existing panels were reused.")
print("PASS: No duplicate patients, visits or lab results were created.")
