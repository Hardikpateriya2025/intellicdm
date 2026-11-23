import sys
from getpass import getpass
from uuid import uuid4

from sqlalchemy import select

from app.auth import hasher
from app.database import SessionLocal
from app.models import User

username = input("Admin username (lowercase): ").strip().casefold()
password = getpass("Password (12+ characters): ")
if len(username) < 3 or len(password) < 12:
    sys.exit("Username needs 3+ characters and password 12+.")
with SessionLocal() as db:
    if db.scalar(select(User.id).where(User.username == username)):
        sys.exit("That username already exists.")
    db.add(User(id=uuid4(), username=username, display_name="Administrator",
                password_hash=hasher.hash(password), role="admin", is_active=True))
    db.commit()
print("Admin created.")
