from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user, hasher, public_user
from app.database import get_db
from app.models import User


def require_admin(user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user


router = APIRouter(
    prefix="/admin/users",
    tags=["User Administration"],
    dependencies=[Depends(require_admin)],
)


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(
        min_length=3, max_length=100,
        pattern=r"^[a-z0-9][a-z0-9_.-]*$",
    )
    display_name: str = Field(min_length=1, max_length=100)
    password: SecretStr = Field(min_length=12, max_length=128)
    role: Literal["doctor", "reviewer"]


@router.post("", status_code=201)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
):
    display_name = payload.display_name.strip()
    if not display_name:
        raise HTTPException(status_code=422, detail="Display name is required.")

    existing = db.scalar(
        select(User.id).where(User.username == payload.username)
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Username already exists.")

    user = User(
        id=uuid4(),
        username=payload.username,
        display_name=display_name,
        password_hash=hasher.hash(payload.password.get_secret_value()),
        role=payload.role,
        is_active=True,
    )
    try:
        db.add(user)
        db.flush()
        result = public_user(user)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Account conflicts with an existing record."
        ) from None
    return result


@router.get("")
def list_users(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    users = db.scalars(
        select(User)
        .order_by(User.username, User.id)
        .offset(offset)
        .limit(limit + 1)
    ).all()
    return {
        "items": [public_user(user) for user in users[:limit]],
        "limit": limit,
        "offset": offset,
        "has_more": len(users) > limit,
    }
