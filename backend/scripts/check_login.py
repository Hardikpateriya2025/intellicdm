import getpass
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

base = "http://127.0.0.1:8000"
username = input("Username: ").strip()
password = getpass.getpass("Password (hidden): ")

req = Request(
    base + "/auth/token",
    data=urlencode({
        "username": username,
        "password": password,
    }).encode(),
    headers={"Content-Type": "application/x-www-form-urlencoded"},
)
del password

try:
    with urlopen(req, timeout=30) as response:
        result = json.load(response)
    print("PASS: Username and password accepted.")
except HTTPError as exc:
    print("Login failed:", exc.code)
    print(exc.read().decode())
    raise SystemExit()

req = Request(
    base + "/auth/me",
    headers={"Authorization": "Bearer " + result["access_token"]},
)
try:
    with urlopen(req, timeout=30) as response:
        user = json.load(response)
    print("PASS: Login token accepted.")
    print("Signed in as:", user["username"], "| Role:", user["role"])
except HTTPError as exc:
    print("Session check failed:", exc.code)
    print(exc.read().decode())
