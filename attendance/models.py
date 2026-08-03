from __future__ import annotations

import ipaddress

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class OfficeSettings(models.Model):
    """Singleton office configuration for GPS geofence and public IP verification."""

    name = models.CharField(max_length=120, default="Main Office", help_text="Label for this office location.")
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True, help_text="Office latitude (WGS84)."
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True, help_text="Office longitude (WGS84)."
    )
    allowed_radius_meters = models.PositiveIntegerField(
        default=100, help_text="Maximum allowed distance from office coordinates (meters)."
    )
    allowed_public_ips = models.TextField(
        blank=True,
        help_text=(
            "One IP or CIDR range per line (or comma-separated). "
            "Examples: 203.0.113.10, 192.168.1.0/24, 2401:4900:1cd7:88b1::/64"
        ),
    )
    gps_verification_enabled = models.BooleanField(
        default=False, help_text="Require users to be within the office geofence."
    )
    ip_verification_enabled = models.BooleanField(
        default=False, help_text="Require requests from configured office public IP(s)."
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Office Settings"
        verbose_name_plural = "Office Settings"

    def __str__(self) -> str:
        return self.name or "Office Settings"

    @classmethod
    def get_solo(cls) -> OfficeSettings:
        obj, _ = cls.objects.get_or_create(pk=1, defaults={"name": "Main Office"})
        return obj

    def requires_verification(self) -> bool:
        return self.gps_verification_enabled or self.ip_verification_enabled

    def get_allowed_ip_list(self) -> list[str]:
        if not self.allowed_public_ips:
            return []
        raw = self.allowed_public_ips.replace(",", "\n")
        return [ip.strip() for ip in raw.splitlines() if ip.strip()]

    def is_ip_allowed(self, ip: str) -> bool:
        if not ip:
            return False
        try:
            client = ipaddress.ip_address(ip)
        except ValueError:
            return False

        # Localhost always bypasses real network checks — never allow for office WiFi verification.
        if client.is_loopback:
            return False

        # Link-local addresses are not valid office public/LAN routes for verification.
        if client.is_link_local:
            return False

        for entry in self.get_allowed_ip_list():
            try:
                if "/" in entry:
                    network = ipaddress.ip_network(entry, strict=False)
                    if network.is_loopback or network.is_link_local:
                        continue
                    if client in network:
                        return True
                else:
                    allowed = ipaddress.ip_address(entry)
                    if allowed.is_loopback or allowed.is_link_local:
                        continue
                    if client == allowed:
                        return True
            except ValueError:
                continue
        return False

    def clean(self) -> None:
        super().clean()
        if self.gps_verification_enabled and (self.latitude is None or self.longitude is None):
            raise ValidationError("Latitude and longitude are required when GPS verification is enabled.")
        if self.ip_verification_enabled and not self.get_allowed_ip_list():
            raise ValidationError("At least one public IP is required when IP verification is enabled.")


class AttendanceStatus(models.TextChoices):
    PRESENT = "Present", "Present"
    HALF_DAY = "Half Day", "Half Day"
    ABSENT = "Absent", "Absent"
    FULL_DAY = "Full Day", "Full Day"
    ON_LEAVE = "On Leave", "On Leave"


class Attendance(models.Model):
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attendance_records")
    date = models.DateField()

    check_in = models.DateTimeField(null=True, blank=True)
    check_out = models.DateTimeField(null=True, blank=True)

    working_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    overtime_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=AttendanceStatus.choices, default=AttendanceStatus.ABSENT)
    is_late = models.BooleanField(default=False)

    check_in_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_in_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_in_distance_m = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    check_in_ip = models.GenericIPAddressField(null=True, blank=True)
    check_in_user_agent = models.CharField(max_length=512, blank=True)

    check_out_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_out_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_out_distance_m = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    check_out_ip = models.GenericIPAddressField(null=True, blank=True)
    check_out_user_agent = models.CharField(max_length=512, blank=True)

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["employee", "date"], name="uniq_employee_date_attendance"),
        ]
        indexes = [
            models.Index(fields=["date"]),
            models.Index(fields=["employee", "date"]),
            models.Index(fields=["status"]),
        ]
        ordering = ["-date", "-created_at"]

    def __str__(self) -> str:
        return f"{self.employee} @ {self.date}"

    @property
    def is_half_day_checkin(self) -> bool:
        if not self.check_in:
            return False
        from django.utils import timezone as tz

        local = tz.localtime(self.check_in)
        return local.hour > 12 or (local.hour == 12 and local.minute >= 30)


class MonthlyLeaveBalance(models.Model):
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="leave_balances")
    year = models.PositiveIntegerField()
    month = models.PositiveIntegerField()

    monthly_allocation = models.PositiveSmallIntegerField(default=3)
    carried_forward = models.PositiveSmallIntegerField(default=0)
    used_leaves = models.PositiveSmallIntegerField(default=0)

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["employee", "year", "month"], name="uniq_employee_year_month_leave"),
        ]
        ordering = ["-year", "-month"]

    @property
    def total_available(self) -> int:
        return self.monthly_allocation + self.carried_forward

    @property
    def remaining(self) -> int:
        return max(0, self.total_available - self.used_leaves)

    def __str__(self) -> str:
        return f"{self.employee} {self.year}-{self.month:02d} ({self.remaining} left)"


class LeaveDeduction(models.Model):
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="leave_deductions")
    attendance = models.ForeignKey(Attendance, on_delete=models.CASCADE, related_name="leave_deductions")
    balance = models.ForeignKey(MonthlyLeaveBalance, on_delete=models.CASCADE, related_name="deductions")
    date = models.DateField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["employee", "date"], name="uniq_employee_date_leave_deduction"),
        ]
        ordering = ["-date"]

    def __str__(self) -> str:
        return f"{self.employee} -{self.date}"


class RegularizationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class AttendanceRegularizationRequest(models.Model):
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="regularization_requests"
    )
    date = models.DateField()
    description = models.TextField()

    status = models.CharField(
        max_length=20, choices=RegularizationStatus.choices, default=RegularizationStatus.PENDING
    )
    hr_note = models.CharField(max_length=255, blank=True)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="regularization_reviews",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    ceo_note = models.CharField(max_length=255, blank=True)
    ceo_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ceo_regularization_overrides",
    )
    ceo_reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["employee", "date"]),
        ]

    def __str__(self) -> str:
        return f"{self.employee} {self.date} ({self.status})"


class LeaveRequestType(models.TextChoices):
    PAID = "paid", "Paid Leave"
    CASUAL = "casual", "Casual Leave"
    SICK = "sick", "Sick Leave"
    UNPAID = "unpaid", "Unpaid Leave"


class LeaveRequestStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class LeaveRequest(models.Model):
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="leave_requests")
    leave_type = models.CharField(max_length=20, choices=LeaveRequestType.choices, default=LeaveRequestType.PAID)
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=LeaveRequestStatus.choices, default=LeaveRequestStatus.PENDING)
    hr_note = models.CharField(max_length=255, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leave_requests_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["employee", "start_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.employee} {self.start_date}–{self.end_date} ({self.status})"

    @property
    def duration_days(self) -> int:
        if not self.start_date or not self.end_date:
            return 0
        return (self.end_date - self.start_date).days + 1


def payslip_upload_to(instance, filename: str) -> str:
    return f"payslips/{instance.year}/{instance.month:02d}/{instance.employee.employee_id}_{filename}"


class PaySlip(models.Model):
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pay_slips")
    year = models.PositiveIntegerField()
    month = models.PositiveIntegerField()
    title = models.CharField(max_length=120, blank=True)
    document = models.FileField(upload_to=payslip_upload_to)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="pay_slips_uploaded"
    )
    uploaded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-year", "-month"]
        constraints = [
            models.UniqueConstraint(fields=["employee", "year", "month"], name="uniq_employee_year_month_payslip"),
        ]

    def __str__(self) -> str:
        return f"{self.employee.employee_id} {self.year}-{self.month:02d}"

    @property
    def period_label(self) -> str:
        from datetime import date

        return date(self.year, self.month, 1).strftime("%B %Y")


class PortalAccessEvent(models.TextChoices):
    LOGIN = "login", "Login"
    CHECK_IN = "check_in", "Check In"
    CHECK_OUT = "check_out", "Check Out"


class PortalAccessLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="portal_access_logs"
    )
    username_attempt = models.CharField(max_length=64, blank=True)
    event_type = models.CharField(max_length=20, choices=PortalAccessEvent.choices)
    success = models.BooleanField(default=False)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    distance_m = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    client_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    failure_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["event_type", "success"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self) -> str:
        who = self.user or self.username_attempt or "unknown"
        return f"{who} {self.event_type} ({'ok' if self.success else 'denied'})"
