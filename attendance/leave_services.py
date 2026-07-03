from __future__ import annotations

from datetime import date

from django.db import transaction

from .models import Attendance, AttendanceStatus, LeaveDeduction, MonthlyLeaveBalance

MONTHLY_PAID_LEAVES = 3


def _prev_year_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


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


def get_leave_summary(*, employee, for_date: date | None = None) -> dict:
    for_date = for_date or date.today()
    balance = ensure_monthly_leave_balance(employee=employee, for_date=for_date)
    deductions = LeaveDeduction.objects.filter(
        employee=employee,
        date__year=for_date.year,
        date__month=for_date.month,
    ).select_related("attendance").order_by("-date")

    absences_this_month = _count_absences(
        employee=employee, year=for_date.year, month=for_date.month
    )

    return {
        "balance": balance,
        "deductions": deductions,
        "absences_this_month": absences_this_month,
        "month_label": for_date.strftime("%B %Y"),
    }
