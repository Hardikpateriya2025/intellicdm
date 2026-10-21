from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from pydantic import (
    computed_field,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

class LabResultCreate(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        allow_inf_nan=False,
    )

    test_name: str = Field(min_length=1, max_length=200)
    value: Decimal
    unit: str = Field(min_length=1, max_length=50)
    reference_low: Decimal | None = None
    reference_high: Decimal | None = None
    collected_at: AwareDatetime

    @field_validator("collected_at")
    @classmethod
    def validate_collection_time(cls, value: datetime) -> datetime:
        if value > datetime.now(timezone.utc):
            raise ValueError("Collection time cannot be in the future")
        return value

    @model_validator(mode="after")
    def validate_reference_range(self):
        if (
            self.reference_low is not None
            and self.reference_high is not None
            and self.reference_low > self.reference_high
        ):
            raise ValueError("Reference low cannot exceed reference high")
        return self

class LabResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    encounter_id: UUID
    test_name: str
    value: Decimal
    unit: str
    reference_low: Decimal | None
    reference_high: Decimal | None
    collected_at: datetime
    created_at: datetime

    @computed_field
    @property
    def reference_flag(self) -> str:
        if self.reference_low is not None and self.value < self.reference_low:
            return "below_range"
        if self.reference_high is not None and self.value > self.reference_high:
            return "above_range"
        if self.reference_low is not None and self.reference_high is not None:
            return "within_range"
        return "insufficient_reference"
