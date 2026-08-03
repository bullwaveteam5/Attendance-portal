from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class HolidayEventType(models.TextChoices):
    HOLIDAY = "holiday", "Holiday"
    EXTRA_WORKING = "extra_working", "Extra Working Day"


class HolidayApprovalStatus(models.TextChoices):
    PENDING = "pending", "Pending Approval"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class Holiday(models.Model):
    date = models.DateField(unique=True)
    name = models.CharField(max_length=120)
    is_optional = models.BooleanField(default=False)
    event_type = models.CharField(
        max_length=20,
        choices=HolidayEventType.choices,
        default=HolidayEventType.HOLIDAY,
    )
    approval_status = models.CharField(
        max_length=20,
        choices=HolidayApprovalStatus.choices,
        default=HolidayApprovalStatus.PENDING,
    )
    hr_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="holidays_hr_approved",
    )
    hr_approved_at = models.DateTimeField(null=True, blank=True)
    ceo_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="holidays_ceo_approved",
    )
    ceo_approved_at = models.DateTimeField(null=True, blank=True)
    approval_note = models.CharField(max_length=255, blank=True)
    ceo_message = models.TextField(blank=True)
    announced_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="holiday_announcements",
    )
    announced_at = models.DateTimeField(null=True, blank=True)
    announcement_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["date"]
        indexes = [
            models.Index(fields=["date"]),
            models.Index(fields=["event_type"]),
            models.Index(fields=["approval_status"]),
        ]

    def __str__(self) -> str:
        return f"{self.date} - {self.name}"

    @property
    def is_extra_working_day(self) -> bool:
        return self.event_type == HolidayEventType.EXTRA_WORKING

    @property
    def is_visible_to_employees(self) -> bool:
        return self.approval_status == HolidayApprovalStatus.APPROVED

    @property
    def hr_approved(self) -> bool:
        # Do not show a green check after rejection (rejecter is still stored for audit).
        if self.approval_status == HolidayApprovalStatus.REJECTED:
            return False
        # Seeded / legacy fully-approved rows may lack approver FKs.
        if self.approval_status == HolidayApprovalStatus.APPROVED:
            return True
        return self.hr_approved_by_id is not None

    @property
    def ceo_approved(self) -> bool:
        if self.approval_status == HolidayApprovalStatus.REJECTED:
            return False
        if self.approval_status == HolidayApprovalStatus.APPROVED:
            return True
        return self.ceo_approved_by_id is not None

    def apply_role_approval(self, user, *, note: str = "") -> None:
        """Record HR or CEO approval; fully approved only when both have approved."""
        from accounts.models import UserRole

        now = timezone.now()
        if note:
            self.approval_note = note.strip()[:255]
        if user.role == UserRole.ADMIN:
            self.hr_approved_by = user
            self.hr_approved_at = now
        elif user.role == UserRole.CEO:
            self.ceo_approved_by = user
            self.ceo_approved_at = now
            self.announced_by = user
            self.announced_at = now
        else:
            return

        if self.hr_approved_by_id and self.ceo_approved_by_id:
            self.approval_status = HolidayApprovalStatus.APPROVED
            self.announcement_active = bool((self.ceo_message or "").strip())
        else:
            self.approval_status = HolidayApprovalStatus.PENDING
            self.announcement_active = False

    def reject_by(self, user, *, note: str = "") -> None:
        from accounts.models import UserRole

        now = timezone.now()
        if note:
            self.approval_note = note.strip()[:255]
        if user.role == UserRole.ADMIN:
            self.hr_approved_by = user
            self.hr_approved_at = now
        elif user.role == UserRole.CEO:
            self.ceo_approved_by = user
            self.ceo_approved_at = now
        self.approval_status = HolidayApprovalStatus.REJECTED
        self.announcement_active = False


class HolidayAnnouncementRead(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="holiday_reads")
    holiday = models.ForeignKey(Holiday, on_delete=models.CASCADE, related_name="reads")
    read_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "holiday"], name="uniq_user_holiday_read"),
        ]
