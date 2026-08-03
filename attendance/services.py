from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Attendance, AttendanceStatus


class AttendanceError(Exception):
    pass


@dataclass(frozen=True)
class AttendancePolicy:
    late_after: time = time(9, 15)  # 09:15 AM
    half_day_if_check_in_after: time = time(12, 30)  # 12:30 PM
    overtime_after: time = time(18, 0)  # 06:00 PM
    full_day_hours: Decimal = Decimal("8.00")
    half_day_hours: Decimal = Decimal("4.00")


def _decimal_hours(delta: timedelta) -> Decimal:
    hours = Decimal(delta.total_seconds()) / Decimal(3600)
    return hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _local_now() -> datetime:
    return timezone.localtime(timezone.now())


def _today_local_date():
    return _local_now().date()


def _overtime_start_on_date(dt: datetime, policy: AttendancePolicy) -> datetime:
    local = timezone.localtime(dt)
    return local.replace(
        hour=policy.overtime_after.hour,
        minute=policy.overtime_after.minute,
        second=0,
        microsecond=0,
    )


def compute_attendance_metrics(
    *,
    check_in: datetime | None,
    check_out: datetime | None,
    policy: AttendancePolicy = AttendancePolicy(),
) -> dict:
    is_late = False
    working_hours = Decimal("0.00")
    overtime_hours = Decimal("0.00")
    status = AttendanceStatus.ABSENT

    if not check_in:
        return {
            "status": status,
            "working_hours": working_hours,
            "overtime_hours": overtime_hours,
            "is_late": is_late,
        }

    check_in_local = timezone.localtime(check_in)
    is_late = check_in_local.time() > policy.late_after

    if check_in and check_out:
        check_out_local = timezone.localtime(check_out)
        working_hours = _decimal_hours(check_out - check_in)
        checked_in_after_half_day = check_in_local.time() >= policy.half_day_if_check_in_after

        if working_hours < policy.half_day_hours:
            status = AttendanceStatus.ABSENT
        elif checked_in_after_half_day:
            status = AttendanceStatus.HALF_DAY
        elif working_hours >= policy.full_day_hours:
            status = AttendanceStatus.FULL_DAY
        else:
            status = AttendanceStatus.HALF_DAY

        if check_out_local.time() > policy.overtime_after:
            ot_start = _overtime_start_on_date(check_out, policy)
            effective_start = max(check_in_local, ot_start)
            if check_out_local > effective_start:
                overtime_hours = _decimal_hours(check_out_local - effective_start)
    elif check_in and not check_out:
        status = (
            AttendanceStatus.HALF_DAY
            if check_in_local.time() >= policy.half_day_if_check_in_after
            else AttendanceStatus.PRESENT
        )

    return {
        "status": status,
        "working_hours": working_hours,
        "overtime_hours": overtime_hours,
        "is_late": is_late,
    }


def _apply_metrics(attendance: Attendance, metrics: dict) -> None:
    attendance.status = metrics["status"]
    attendance.working_hours = metrics["working_hours"]
    attendance.overtime_hours = metrics["overtime_hours"]
    attendance.is_late = metrics["is_late"]


def _apply_check_in_log(attendance: Attendance, ctx: dict | None) -> list[str]:
    if not ctx:
        return []
    fields = []
    if ctx.get("latitude") is not None:
        attendance.check_in_latitude = ctx["latitude"]
        fields.append("check_in_latitude")
    if ctx.get("longitude") is not None:
        attendance.check_in_longitude = ctx["longitude"]
        fields.append("check_in_longitude")
    if ctx.get("distance_m") is not None:
        attendance.check_in_distance_m = Decimal(str(round(ctx["distance_m"], 2)))
        fields.append("check_in_distance_m")
    if ctx.get("client_ip"):
        attendance.check_in_ip = ctx["client_ip"]
        fields.append("check_in_ip")
    if ctx.get("user_agent"):
        attendance.check_in_user_agent = ctx["user_agent"]
        fields.append("check_in_user_agent")
    return fields


def _apply_check_out_log(attendance: Attendance, ctx: dict | None) -> list[str]:
    if not ctx:
        return []
    fields = []
    if ctx.get("latitude") is not None:
        attendance.check_out_latitude = ctx["latitude"]
        fields.append("check_out_latitude")
    if ctx.get("longitude") is not None:
        attendance.check_out_longitude = ctx["longitude"]
        fields.append("check_out_longitude")
    if ctx.get("distance_m") is not None:
        attendance.check_out_distance_m = Decimal(str(round(ctx["distance_m"], 2)))
        fields.append("check_out_distance_m")
    if ctx.get("client_ip"):
        attendance.check_out_ip = ctx["client_ip"]
        fields.append("check_out_ip")
    if ctx.get("user_agent"):
        attendance.check_out_user_agent = ctx["user_agent"]
        fields.append("check_out_user_agent")
    return fields


@transaction.atomic
def check_in(
    *,
    employee,
    policy: AttendancePolicy = AttendancePolicy(),
    verification_context: dict | None = None,
) -> Attendance:
    now = _local_now()
    today = now.date()

    from .leave_services import has_approved_leave_on

    if has_approved_leave_on(employee=employee, att_date=today):
        raise AttendanceError("You are on approved leave today. Check-in is not allowed.")

    metrics = compute_attendance_metrics(check_in=now, check_out=None, policy=policy)

    try:
        attendance, created = Attendance.objects.select_for_update().get_or_create(
            employee=employee,
            date=today,
            defaults={
                "check_in": now,
                "status": metrics["status"],
                "is_late": metrics["is_late"],
            },
        )
    except IntegrityError as e:
        raise AttendanceError("Attendance already exists for today.") from e

    if attendance.status == AttendanceStatus.ON_LEAVE:
        raise AttendanceError("You are on approved leave today. Check-in is not allowed.")

    if not created and attendance.check_in:
        raise AttendanceError("You have already checked in today.")

    if not attendance.check_in:
        attendance.check_in = now
        _apply_metrics(attendance, metrics)

    log_fields = _apply_check_in_log(attendance, verification_context)
    update_fields = list(
        dict.fromkeys(["check_in", "status", "is_late", "working_hours", "overtime_hours", *log_fields])
    )
    attendance.save(update_fields=update_fields)

    return attendance


@transaction.atomic
def check_out(
    *,
    employee,
    policy: AttendancePolicy = AttendancePolicy(),
    verification_context: dict | None = None,
) -> Attendance:
    now = _local_now()
    today = now.date()

    try:
        attendance = Attendance.objects.select_for_update().get(employee=employee, date=today)
    except Attendance.DoesNotExist as e:
        raise AttendanceError("You must check in before checking out.") from e

    if attendance.status == AttendanceStatus.ON_LEAVE:
        raise AttendanceError("You are on approved leave today. Check-out is not allowed.")

    if not attendance.check_in:
        raise AttendanceError("You must check in before checking out.")

    if attendance.check_out:
        raise AttendanceError("You have already checked out today.")

    if now < attendance.check_in:
        raise AttendanceError("Check-out time cannot be before check-in.")

    metrics = compute_attendance_metrics(
        check_in=attendance.check_in,
        check_out=now,
        policy=policy,
    )

    attendance.check_out = now
    _apply_metrics(attendance, metrics)
    log_fields = _apply_check_out_log(attendance, verification_context)
    attendance.save(
        update_fields=["check_out", "working_hours", "overtime_hours", "status", "is_late", *log_fields]
    )

    if attendance.status == AttendanceStatus.ABSENT:
        from .leave_services import deduct_paid_leave_for_absence

        deduct_paid_leave_for_absence(attendance=attendance)

    return attendance


def today_status(*, employee) -> Attendance | None:
    return Attendance.objects.filter(employee=employee, date=_today_local_date()).first()


@transaction.atomic
def regularize_attendance(
    *,
    employee,
    att_date,
    check_in: datetime | None,
    check_out: datetime | None,
    policy: AttendancePolicy = AttendancePolicy(),
) -> Attendance:
    if check_in and timezone.is_naive(check_in):
        check_in = timezone.make_aware(check_in, timezone.get_current_timezone())
    if check_out and timezone.is_naive(check_out):
        check_out = timezone.make_aware(check_out, timezone.get_current_timezone())

    from .leave_services import (
        deduct_paid_leave_for_absence,
        has_approved_leave_on,
        reverse_leave_deduction_for_date,
    )

    if has_approved_leave_on(employee=employee, att_date=att_date):
        raise AttendanceError(
            "Cannot regularize this date — employee has an approved leave request covering it."
        )

    attendance, _ = Attendance.objects.select_for_update().get_or_create(employee=employee, date=att_date)
    if attendance.status == AttendanceStatus.ON_LEAVE:
        raise AttendanceError("Cannot regularize — attendance is already marked On Leave.")

    attendance.check_in = check_in
    if check_out is not None:
        attendance.check_out = check_out

    metrics = compute_attendance_metrics(
        check_in=attendance.check_in,
        check_out=attendance.check_out,
        policy=policy,
    )
    _apply_metrics(attendance, metrics)
    attendance.save()

    if attendance.status == AttendanceStatus.ABSENT:
        deduct_paid_leave_for_absence(attendance=attendance)
    else:
        # Present / Half Day / Full Day — undo any prior absence deduction for this date.
        reverse_leave_deduction_for_date(employee=employee, att_date=att_date)

    return attendance
