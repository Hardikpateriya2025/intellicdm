from datetime import datetime, timezone
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

class EncounterCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    visited_at: AwareDatetime
    reason: str = Field(min_length=1, max_length=500)
    notes: str | None = Field(default=None, max_length=10000)

    @field_validator("visited_at")
    @classmethod
    def validate_visit_time(cls, value: datetime) -> datetime:
        if value > datetime.now(timezone.utc):
            raise ValueError("A completed visit cannot be in the future")
        return value

class EncounterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    patient_id: UUID
    visited_at: datetime
    reason: str
    notes: str | None
    created_at: datetime
