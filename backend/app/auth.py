from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User

router = APIRouter(prefix="/auth", tags=["Authentication"])
oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/token")
hasher = PasswordHash.recommended()
dummy_hash = hasher.hash("unused-dummy-password-for-timing")
ISSUER = "intellicdm"
AUDIENCE = "intellicdm-api"


def unauthorized():
    return HTTPException(
        status_code=401,
        detail="Invalid credentials or expired token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def public_user(user):
    return {
        "id": str(user.id),
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "is_active": user.is_active,
    }


@router.post("/token")
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    username = form.username.strip().casefold()
    if len(username) > 100 or not 1 <= len(form.password) <= 128:
        raise unauthorized()

    user = db.scalar(select(User).where(User.username == username))
    valid = hasher.verify(
        form.password,
        user.password_hash if user is not None else dummy_hash,
    )
    if not valid or user is None or not user.is_active:
        raise unauthorized()

    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": str(user.id),
            "iat": now,
            "exp": now + timedelta(minutes=30),
            "jti": str(uuid4()),
            "iss": ISSUER,
            "aud": AUDIENCE,
        },
        settings.auth_secret.get_secret_value(),
        algorithm="HS256",
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 1800,
    }


def get_current_user(
    token: str = Depends(oauth2),
    db: Session = Depends(get_db),
):
    try:
        claims = jwt.decode(
            token,
            settings.auth_secret.get_secret_value(),
            algorithms=["HS256"],
            issuer=ISSUER,
            audience=AUDIENCE,
            options={"require": ["sub", "iat", "exp", "jti", "iss", "aud"]},
        )
        user_id = UUID(claims["sub"])
    except (InvalidTokenError, ValueError, TypeError, KeyError):
        raise unauthorized() from None

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized()
    return user


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return public_user(user)


def clinical_access(
    request: Request,
    user: User = Depends(get_current_user),
):
    if user.role not in {"admin", "doctor", "reviewer"}:
        raise HTTPException(status_code=403, detail="Role not permitted.")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if user.role not in {"admin", "doctor"}:
            raise HTTPException(
                status_code=403,
                detail="Only admins and doctors can modify clinical records.",
            )
    return user


def analysis_access(user: User = Depends(get_current_user)):
    if user.role not in {"admin", "doctor", "reviewer"}:
        raise HTTPException(status_code=403, detail="Role not permitted.")
    return user


def review_access(
    request: Request,
    user: User = Depends(get_current_user),
):
    if user.role not in {"admin", "doctor", "reviewer"}:
        raise HTTPException(status_code=403, detail="Role not permitted.")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if user.role not in {"admin", "reviewer"}:
            raise HTTPException(
                status_code=403,
                detail="Only admins and reviewers can submit reviews.",
            )
    return user
