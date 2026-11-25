from __future__ import annotations

from datetime import date, timezone
from typing import Annotated
from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, StringConstraints, model_validator
from uuid import UUID

from .models import BookingStatus, ServiceType


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120, pattern=r"^[^\x00]*$")]


def supported_utc(value):
    try:
        return value.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        raise ValueError("Timestamp exceeds the supported UTC datetime range")


UtcInstant = Annotated[AwareDatetime, AfterValidator(supported_utc)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterIn(InputModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    display_name: Name


class LoginIn(InputModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ProfileUpdateIn(InputModel):
    display_name: Name


class PetIn(InputModel):
    name: Name


class ScheduleIn(InputModel):
    grooming_start: UtcInstant | None = None
    boarding_start: date | None = None
    boarding_end: date | None = None

    @model_validator(mode="after")
    def validate_schedule_shape(self):
        grooming = self.grooming_start is not None
        boarding = self.boarding_start is not None or self.boarding_end is not None
        if grooming == boarding:
            raise ValueError("Provide either grooming_start or boarding_start/boarding_end")
        if boarding and (self.boarding_start is None or self.boarding_end is None or self.boarding_end <= self.boarding_start):
            raise ValueError("Boarding end date must be after start date")
        return self


class BookingCreateIn(ScheduleIn):
    pet_id: UUID
    service_id: UUID


class RescheduleIn(ScheduleIn):
    pass


class AdminStatusIn(InputModel):
    status: BookingStatus


class GroomingCompleteIn(InputModel):
    service_notes: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000, pattern=r"^[^\x00]*$")] | None = None


class BoardingNoteIn(InputModel):
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000, pattern=r"^[^\x00]*$")]


class StaffCreateIn(InputModel):
    display_name: Name | None = None
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    is_active: bool = True


class StaffUpdateIn(InputModel):
    # Supervisor correction (Nov 2026): Admin cannot change an existing Staff password. With extra="forbid",
    # a request that still sends "password" is rejected (422) instead of being silently ignored.
    display_name: Name | None = None
    email: EmailStr
    is_active: bool


class PasswordChangeIn(InputModel):
    """A signed-in Staff member changing their own password."""
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)

    @model_validator(mode="after")
    def new_password_differs(self):
        if self.new_password == self.current_password:
            raise ValueError("New password must be different from the current password")
        return self


class ServiceCreateIn(InputModel):
    display_order: int = Field(default=0, ge=0, le=100000, strict=True)
    name: Name
    service_type: ServiceType
    is_active: bool = True
    duration_minutes: int | None = Field(default=None, gt=0, le=2147483647, strict=True)

    @model_validator(mode="after")
    def typed_duration(self):
        if (self.service_type == ServiceType.GROOMING) != (self.duration_minutes is not None):
            raise ValueError("Grooming requires a positive duration; Boarding must not have one")
        return self


class ServiceUpdateIn(InputModel):
    display_order: int | None = Field(default=None, ge=0, le=100000, strict=True)
    name: Name
    is_active: bool
    duration_minutes: int | None = Field(default=None, gt=0, le=2147483647, strict=True)


class ReminderSettingIn(InputModel):
    enabled: bool
    lead_minutes: int | None = Field(default=None, ge=1, le=525600, strict=True)

    @model_validator(mode="after")
    def configured(self):
        if self.enabled and self.lead_minutes is None:
            raise ValueError("Admin must configure a lead time before enabling reminders")
        return self


class DurationIn(InputModel):
    duration_minutes: int = Field(gt=0, le=2147483647, strict=True)


class StaffWindowIn(InputModel):
    starts_at: UtcInstant
    ends_at: UtcInstant
    is_active: bool = True

    @model_validator(mode="after")
    def ordered(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("Availability end must be after start")
        return self


class StaffAssignmentIn(InputModel):
    staff_user_id: UUID | None
    starts_at: UtcInstant | None = None
    ends_at: UtcInstant | None = None
    effective_at: UtcInstant | None = None

    @model_validator(mode="after")
    def ordered(self):
        if (self.starts_at is None) != (self.ends_at is None):
            raise ValueError("Provide both duty-window timestamps")
        if self.starts_at is not None and self.ends_at <= self.starts_at:
            raise ValueError("Duty-window end must be after start")
        if self.staff_user_id is None and self.starts_at is not None:
            raise ValueError("Unassignment must not contain a duty window")
        return self


class AccommodationIn(InputModel):
    name: Name
    category: Name
    capacity: int = Field(gt=0, le=2147483647, strict=True)
    is_active: bool = True
    notes: Annotated[str, StringConstraints(pattern=r"^[^\x00]*$")] | None = None


class AllocationIn(InputModel):
    accommodation_id: UUID


class AvailabilityQueryIn(ScheduleIn):
    service_id: UUID
