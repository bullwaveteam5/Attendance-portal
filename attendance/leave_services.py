from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from .models import (
    Attendance,
    AttendanceStatus,
    LeaveDeduction,
    LeaveRequest,
    LeaveRequestStatus,
    LeaveRequestType,
    MonthlyLeaveBalance,
)

MONTHLY_PAID_LEAVES = 3


def _prev_year_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _daterange(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _count_absences(*, employee, year: int, month: int) -> int:
    return Attendance.objects.filter(
        employee=employee,
        date__year=year,
        date__month=month,
        status=AttendanceStatus.ABSENT,
    ).count()


@transaction.atomic
def ensure_monthly_leave_balance(*, employee, for_date: date | None = None) -> MonthlyLeaveBalance:
    for_date = for_date or date.today()
    year, month = for_date.year, for_date.month

    balance = MonthlyLeaveBalance.objects.filter(employee=employee, year=year, month=month).first()
    if balance:
        return balance

    prev_year, prev_month = _prev_year_month(year, month)
    prev_balance = MonthlyLeaveBalance.objects.filter(
        employee=employee, year=prev_year, month=prev_month
    ).first()
    prev_absences = _count_absences(employee=employee, year=prev_year, month=prev_month)

    carried_forward = 0
    if prev_balance and prev_absences == 0:
        carried_forward = prev_balance.remaining

    return MonthlyLeaveBalance.objects.create(
        employee=employee,
        year=year,
        month=month,
        monthly_allocation=MONTHLY_PAID_LEAVES,
        carried_forward=carried_forward,
        used_leaves=0,
    )


@transaction.atomic
def deduct_paid_leave_for_absence(*, attendance: Attendance) -> bool:
    if attendance.status != AttendanceStatus.ABSENT:
        return False

    if LeaveDeduction.objects.filter(employee=attendance.employee, date=attendance.date).exists():
        return False

    balance = ensure_monthly_leave_balance(employee=attendance.employee, for_date=attendance.date)
    if balance.remaining <= 0:
        return False

    balance.used_leaves += 1
    balance.save(update_fields=["used_leaves"])

    LeaveDeduction.objects.create(
        employee=attendance.employee,
        attendance=attendance,
        balance=balance,
        date=attendance.date,
    )
    return True


@transaction.atomic
def reverse_leave_deduction_for_date(*, employee, att_date: date) -> bool:
    """Undo absence leave deduction when attendance is no longer Absent."""
    deduction = LeaveDeduction.objects.filter(employee=employee, date=att_date).select_related("balance").first()
    if not deduction:
        return False
    balance = deduction.balance
    if balance.used_leaves > 0:
        balance.used_leaves -= 1
        balance.save(update_fields=["used_leaves"])
    deduction.delete()
    return True


def has_approved_leave_on(*, employee, att_date: date) -> bool:
    return LeaveRequest.objects.filter(
        employee=employee,
        status=LeaveRequestStatus.APPROVED,
        start_date__lte=att_date,
        end_date__gte=att_date,
    ).exists()


@transaction.atomic
def apply_approved_leave_request(*, leave_req: LeaveRequest) -> int:
    """
    Mark each leave day as On Leave on attendance and deduct paid leave balance.
    Overwrites any prior Present/Absent so all pages stay in sync after HR/CEO approve.
    Returns number of days applied.
    """
    applied = 0
    for day in _daterange(leave_req.start_date, leave_req.end_date):
        attendance, _ = Attendance.objects.select_for_update().get_or_create(
            employee=leave_req.employee,
            date=day,
        )

        # Reverse prior absence deduction for this date (leave replaces absence).
        reverse_leave_deduction_for_date(employee=leave_req.employee, att_date=day)

        attendance.check_in = None
        attendance.check_out = None
        attendance.working_hours = Decimal("0.00")
        attendance.overtime_hours = Decimal("0.00")
        attendance.is_late = False
        attendance.status = AttendanceStatus.ON_LEAVE
        attendance.save()

        if leave_req.leave_type == LeaveRequestType.PAID:
            balance = ensure_monthly_leave_balance(employee=leave_req.employee, for_date=day)
            if balance.remaining > 0 and not LeaveDeduction.objects.filter(
                employee=leave_req.employee, date=day
            ).exists():
                balance.used_leaves += 1
                balance.save(update_fields=["used_leaves"])
                LeaveDeduction.objects.create(
                    employee=leave_req.employee,
                    attendance=attendance,
                    balance=balance,
                    date=day,
                )
        applied += 1
    return applied


@transaction.atomic
def reverse_approved_leave_request(*, leave_req: LeaveRequest) -> int:
    """Clear On Leave attendance days created by an approved leave (e.g. if rejected later)."""
    reversed_days = 0
    for day in _daterange(leave_req.start_date, leave_req.end_date):
        attendance = Attendance.objects.filter(employee=leave_req.employee, date=day).first()
        if not attendance or attendance.status != AttendanceStatus.ON_LEAVE:
            continue
        reverse_leave_deduction_for_date(employee=leave_req.employee, att_date=day)
        attendance.delete()
        reversed_days += 1
    return reversed_days


def get_leave_summary(*, employee, for_date: date | None = None) -> dict:
    for_date = for_date or date.today()
    month_start = for_date.replace(day=1)
    if for_date.month == 12:
        month_end = date(for_date.year + 1, 1, 1) - timedelta(days=1)
    else:
        month_end = date(for_date.year, for_date.month + 1, 1) - timedelta(days=1)

    balance = ensure_monthly_leave_balance(employee=employee, for_date=for_date)
    deductions = (
        LeaveDeduction.objects.filter(
            employee=employee,
            date__year=for_date.year,
            date__month=for_date.month,
        )
        .select_related("attendance")
        .order_by("-date")
    )

    absences_this_month = _count_absences(employee=employee, year=for_date.year, month=for_date.month)
    approved_leave_requests = LeaveRequest.objects.filter(
        employee=employee,
        status=LeaveRequestStatus.APPROVED,
        start_date__lte=month_end,
        end_date__gte=month_start,
    ).order_by("-start_date")

    on_leave_days = Attendance.objects.filter(
        employee=employee,
        date__year=for_date.year,
        date__month=for_date.month,
        status=AttendanceStatus.ON_LEAVE,
    ).count()

    return {
        "balance": balance,
        "deductions": deductions,
        "absences_this_month": absences_this_month,
        "on_leave_days": on_leave_days,
        "approved_leave_requests": approved_leave_requests,
        "month_label": for_date.strftime("%B %Y"),
    }
