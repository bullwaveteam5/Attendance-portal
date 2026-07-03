from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class HolidayEventType(models.TextChoices):
    HOLIDAY = "holiday", "Holiday"
    EXTRA_WORKING = "extra_working", "Extra Working Day"


class Holiday(models.Model):
    date = models.DateField(unique=True)
    name = models.CharField(max_length=120)
    is_optional = models.BooleanField(default=False)
    event_type = models.CharField(
        max_length=20,
        choices=HolidayEventType.choices,
        default=HolidayEventType.HOLIDAY,
    )
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
        ]

    def __str__(self) -> str:
        return f"{self.date} - {self.name}"

    @property
    def is_extra_working_day(self) -> bool:
        return self.event_type == HolidayEventType.EXTRA_WORKING


class HolidayAnnouncementRead(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="holiday_reads")
    holiday = models.ForeignKey(Holiday, on_delete=models.CASCADE, related_name="reads")
    read_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "holiday"], name="uniq_user_holiday_read"),
        ]
