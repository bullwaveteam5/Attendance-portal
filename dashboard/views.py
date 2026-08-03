from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db.models import Count, Q, Sum
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie

from accounts.forms import EmployeeIdAuthenticationForm, InitialAdminSetupForm, PersonalProfileForm
from django.contrib.auth.forms import PasswordChangeForm
from datetime import date
from accounts.decorators import (
    admin_or_ceo_required,
    admin_required,
    ceo_required,
    director_required,
    employee_required,
    self_attendance_required,
)
from accounts.models import EmployeePersonalProfile, PraiseLetter, User, UserRole
from accounts.hierarchy import build_org_hierarchy
from attendance.models import (
    Attendance,
    AttendanceRegularizationRequest,
    AttendanceStatus,
    LeaveRequest,
    LeaveRequestStatus,
    LeaveRequestType,
    MonthlyLeaveBalance,
    PaySlip,
    RegularizationStatus,
)
from attendance.services import AttendanceError, check_in, check_out, regularize_attendance, today_status
from attendance.leave_services import (
    apply_approved_leave_request,
    ensure_monthly_leave_balance,
    get_leave_summary,
    reverse_leave_deduction_for_date,
)
from attendance.location import LocationVerificationError, log_portal_access, verify_office_access
from dashboard.mixins import OfficeLocationLoginMixin

from .forms import (
    AttendanceRegularizeForm,
    CeoHolidayAnnounceForm,
    CeoRegularizationOverrideForm,
    EmployeeRegularizationRequestForm,
    EmployeeUpsertForm,
    HolidayForm,
    HrRegularizationApproveForm,
    PraiseLetterForm,
    CompanyHierarchyForm,
    LeaveRequestForm,
    HrLeaveReviewForm,
    PaySlipUploadForm,
)
from .models import Holiday, HolidayAnnouncementRead, HolidayApprovalStatus, HolidayEventType


def _month_calendar_events(for_date: date, *, approved_only: bool = True) -> dict:
    month_start = for_date.replace(day=1)
    month_end = (month_start + timezone.timedelta(days=32)).replace(day=1) - timezone.timedelta(days=1)
    qs = Holiday.objects.filter(date__gte=month_start, date__lte=month_end).order_by("date")
    if approved_only:
        qs = qs.filter(approval_status=HolidayApprovalStatus.APPROVED)
    return {
        "upcoming_holidays": qs.filter(event_type=HolidayEventType.HOLIDAY),
        "extra_working_days": qs.filter(event_type=HolidayEventType.EXTRA_WORKING),
        "all_calendar_events": qs,
    }


def _notify_holiday_announcements(request: HttpRequest) -> None:
    read_ids = HolidayAnnouncementRead.objects.filter(user=request.user).values_list("holiday_id", flat=True)
    unread = (
        Holiday.objects.filter(
            announcement_active=True,
            approval_status=HolidayApprovalStatus.APPROVED,
        )
        .exclude(ceo_message="")
        .exclude(pk__in=read_ids)
        .order_by("-announced_at")[:3]
    )
    for h in unread:
        label = "Extra Working Day" if h.event_type == HolidayEventType.EXTRA_WORKING else "Holiday"
        messages.info(
            request,
            f"CEO Notice — {label} on {h.date} ({h.name}): {h.ceo_message[:160]}{'...' if len(h.ceo_message) > 160 else ''}",
        )
    if unread.exists():
        HolidayAnnouncementRead.objects.bulk_create(
            [HolidayAnnouncementRead(user=request.user, holiday=h) for h in unread],
            ignore_conflicts=True,
        )


def _own_attendance_context(user: User) -> dict:
    record = today_status(employee=user)
    on_leave = bool(record and record.status == AttendanceStatus.ON_LEAVE)
    return {
        "my_attendance_record": record,
        "my_on_leave": on_leave,
        "my_can_check_in": (not on_leave) and not (record and record.check_in),
        "my_can_check_out": (not on_leave) and bool(record and record.check_in and not record.check_out),
    }


def _present_statuses():
    return (AttendanceStatus.PRESENT, AttendanceStatus.FULL_DAY, AttendanceStatus.HALF_DAY)


def _count_present_today(today) -> int:
    return (
        Attendance.objects.filter(
            date=today,
            employee__role=UserRole.EMPLOYEE,
            status__in=_present_statuses(),
        )
        .values("employee_id")
        .distinct()
        .count()
    )


def _count_on_leave_today(today) -> int:
    return Attendance.objects.filter(
        date=today,
        employee__role=UserRole.EMPLOYEE,
        status=AttendanceStatus.ON_LEAVE,
    ).count()


def _today_employee_attendance_board(today) -> list[dict]:
    """
    Live roster for HR/CEO: every active employee with today's check-in/out
    (or Not marked) so records stay visible as people punch in/out.
    """
    employees = list(
        User.objects.filter(role=UserRole.EMPLOYEE, is_active=True).order_by("employee_id")
    )
    records = {
        row.employee_id: row
        for row in Attendance.objects.filter(date=today, employee__role=UserRole.EMPLOYEE).select_related(
            "employee"
        )
    }
    board = []
    for emp in employees:
        att = records.get(emp.id)
        board.append(
            {
                "employee": emp,
                "record": att,
                "check_in": att.check_in if att else None,
                "check_out": att.check_out if att else None,
                "status": att.status if att else "Not marked",
                "is_late": bool(att and att.is_late),
                "working_hours": att.working_hours if att else None,
                "overtime_hours": att.overtime_hours if att else None,
            }
        )
    return board


def _attendance_redirect_url(user: User) -> str:
    role = getattr(user, "role", None)
    if role == UserRole.ADMIN:
        return "admin_dashboard"
    if role == UserRole.CEO:
        return "ceo_dashboard"
    if role == UserRole.DIRECTOR:
        return "director_dashboard"
    return "employee_dashboard"


def _personal_info_back_url(user: User) -> str:
    role = getattr(user, "role", None)
    if role == UserRole.ADMIN:
        return "admin_dashboard"
    if role == UserRole.CEO:
        return "ceo_dashboard"
    if role == UserRole.DIRECTOR:
        return "director_dashboard"
    return "employee_dashboard"


@method_decorator(ensure_csrf_cookie, name="dispatch")
class EmployeeLoginView(OfficeLocationLoginMixin, LoginView):
    template_name = "auth/login.html"
    authentication_form = EmployeeIdAuthenticationForm

    def get_success_url(self) -> str:
        user = self.request.user
        role = getattr(user, "role", None)
        if role == UserRole.ADMIN:
            return "/hr/dashboard/"
        if role == UserRole.CEO:
            return "/ceo/dashboard/"
        if role == UserRole.DIRECTOR:
            return "/director/dashboard/"
        return "/employee/dashboard/"

    def form_valid(self, form):
        user = form.get_user()
        role = getattr(user, "role", None)
        if role not in (UserRole.EMPLOYEE,):
            form.add_error(None, "Please use the correct portal for your role (HR, CEO, or Director).")
            return self.form_invalid(form)
        return OfficeLocationLoginMixin.form_valid(self, form)


@method_decorator(ensure_csrf_cookie, name="dispatch")
class HrLoginView(OfficeLocationLoginMixin, LoginView):
    template_name = "auth/login.html"
    authentication_form = EmployeeIdAuthenticationForm

    def get_success_url(self) -> str:
        return "/hr/dashboard/"

    def form_valid(self, form):
        user = form.get_user()
        if getattr(user, "role", None) != UserRole.ADMIN:
            form.add_error(None, "This portal is for HR Admin accounts only.")
            return self.form_invalid(form)
        return OfficeLocationLoginMixin.form_valid(self, form)


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CeoLoginView(OfficeLocationLoginMixin, LoginView):
    template_name = "auth/login.html"
    authentication_form = EmployeeIdAuthenticationForm

    def get_success_url(self) -> str:
        return "/ceo/dashboard/"

    def form_valid(self, form):
        user = form.get_user()
        if getattr(user, "role", None) != UserRole.CEO:
            form.add_error(None, "This portal is for CEO accounts only.")
            return self.form_invalid(form)
        return OfficeLocationLoginMixin.form_valid(self, form)


@method_decorator(ensure_csrf_cookie, name="dispatch")
class DirectorLoginView(OfficeLocationLoginMixin, LoginView):
    template_name = "auth/login.html"
    authentication_form = EmployeeIdAuthenticationForm

    def get_success_url(self) -> str:
        return "/director/dashboard/"

    def form_valid(self, form):
        user = form.get_user()
        if getattr(user, "role", None) != UserRole.DIRECTOR:
            form.add_error(None, "This portal is for Director accounts only.")
            return self.form_invalid(form)
        return OfficeLocationLoginMixin.form_valid(self, form)


@login_required
def logout_view(request: HttpRequest) -> HttpResponse:
    logout(request)
    return redirect("home")

def landing_page(request: HttpRequest) -> HttpResponse:
    if User.objects.count() == 0:
        return redirect("initial_setup")
    dashboard_url = None
    if request.user.is_authenticated:
        role = getattr(request.user, "role", None)
        if role == UserRole.ADMIN:
            dashboard_url = "/hr/dashboard/"
        elif role == UserRole.CEO:
            dashboard_url = "/ceo/dashboard/"
        elif role == UserRole.DIRECTOR:
            dashboard_url = "/director/dashboard/"
        else:
            dashboard_url = "/employee/dashboard/"
    return render(
        request,
        "landing.html",
        {
            "dashboard_url": dashboard_url,
            "has_users": True,
        },
    )


@login_required
def password_change(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "Password updated successfully.")
            return redirect("home")
    else:
        form = PasswordChangeForm(user=request.user)
    return render(request, "account/password_change.html", {"form": form})


@login_required
def personal_info(request: HttpRequest) -> HttpResponse:
    profile, _ = EmployeePersonalProfile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        form = PersonalProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Personal information saved successfully.")
            return redirect("personal_info")
    else:
        form = PersonalProfileForm(instance=profile)
    return render(
        request,
        "account/personal_info.html",
        {
            "form": form,
            "profile": profile,
            "profile_user": request.user,
            "read_only": False,
            "back_url": _personal_info_back_url(request.user),
        },
    )


@login_required
@admin_or_ceo_required
def hr_employee_personal_info(request: HttpRequest, pk: int) -> HttpResponse:
    employee = get_object_or_404(User, pk=pk)
    profile, _ = EmployeePersonalProfile.objects.get_or_create(user=employee)
    return render(
        request,
        "account/personal_info.html",
        {
            "form": None,
            "profile": profile,
            "profile_user": employee,
            "read_only": True,
            "back_url": "employee_list",
        },
    )


def initial_setup(request: HttpRequest) -> HttpResponse:
    if User.objects.count() > 0:
        return redirect("home")

    if request.method == "POST" and User.objects.exists():
        return HttpResponseBadRequest("Initial setup is already complete.")

    if request.method == "POST":
        form = InitialAdminSetupForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("home")
    else:
        form = InitialAdminSetupForm()

    return render(request, "auth/setup.html", {"form": form})


@login_required
@employee_required
def employee_dashboard(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    soon = (
        Holiday.objects.filter(
            date__gte=today,
            date__lte=today + timezone.timedelta(days=7),
            approval_status=HolidayApprovalStatus.APPROVED,
            event_type=HolidayEventType.HOLIDAY,
        )
        .order_by("date")[:3]
    )
    if soon:
        messages.info(request, f"Upcoming holiday: {soon[0].name} on {soon[0].date}")
    today_md = (today.month, today.day)
    if request.user.date_of_birth and (request.user.date_of_birth.month, request.user.date_of_birth.day) == today_md:
        messages.info(request, "Happy Birthday! Have an amazing year ahead.")
    if (
        request.user.anniversary_date
        and (request.user.anniversary_date.month, request.user.anniversary_date.day) == today_md
    ):
        messages.info(request, "Happy Work Anniversary! Thank you for your contribution.")
    _notify_holiday_announcements(request)
    record = today_status(employee=request.user)
    on_leave_today = bool(record and record.status == AttendanceStatus.ON_LEAVE)
    can_check_in = (not on_leave_today) and not (record and record.check_in)
    can_check_out = (not on_leave_today) and bool(record and record.check_in and not record.check_out)
    history = Attendance.objects.filter(employee=request.user).order_by("-date")[:60]
    calendar = _month_calendar_events(today, approved_only=True)
    praise_letters = PraiseLetter.objects.filter(employee=request.user).select_related("issued_by").order_by("-issued_at")[:10]
    unread_praise = PraiseLetter.objects.filter(employee=request.user, is_read=False).order_by("-issued_at")
    for letter in unread_praise[:2]:
        messages.success(
            request,
            f"CEO Praise Letter — {letter.title}: {letter.message[:150]}{'...' if len(letter.message) > 150 else ''}",
        )
    if unread_praise.exists():
        unread_praise.update(is_read=True)
    leave_summary = get_leave_summary(employee=request.user, for_date=today)
    my_regularizations = AttendanceRegularizationRequest.objects.filter(employee=request.user).order_by("-created_at")[:10]
    my_leave_requests = LeaveRequest.objects.filter(employee=request.user).order_by("-created_at")[:8]
    return render(
        request,
        "employee/dashboard.html",
        {
            "today": today,
            "record": record,
            "history": history,
            "upcoming_holidays": calendar["upcoming_holidays"],
            "extra_working_days": calendar["extra_working_days"],
            "praise_letters": praise_letters,
            "portal_mode": "self",
            "can_check_in": can_check_in,
            "can_check_out": can_check_out,
            "on_leave_today": on_leave_today,
            "holiday_month": today.strftime("%B %Y"),
            "leave_summary": leave_summary,
            "my_regularizations": my_regularizations,
            "my_leave_requests": my_leave_requests,
        },
    )


@login_required
def org_hierarchy_view(request: HttpRequest) -> HttpResponse:
    org = build_org_hierarchy(viewer=request.user)
    back_url = "employee_dashboard"
    if request.user.role == UserRole.ADMIN:
        back_url = "admin_dashboard"
    elif request.user.role == UserRole.CEO:
        back_url = "ceo_dashboard"
    elif request.user.role == UserRole.DIRECTOR:
        back_url = "director_dashboard"
    return render(
        request,
        "org/hierarchy.html",
        {"org": org, "back_url": back_url, "can_edit": request.user.role == UserRole.DIRECTOR},
    )


@login_required
@director_required
def director_dashboard(request: HttpRequest) -> HttpResponse:
    org = build_org_hierarchy(viewer=request.user)
    employee_count = User.objects.filter(role=UserRole.EMPLOYEE, is_active=True).count()
    return render(
        request,
        "director/dashboard.html",
        {
            "org": org,
            "employee_count": employee_count,
            "hr_count": User.objects.filter(role=UserRole.ADMIN, is_active=True).count(),
        },
    )


@login_required
@director_required
def director_hierarchy_manage(request: HttpRequest) -> HttpResponse:
    from accounts.hierarchy import get_company_hierarchy

    config = get_company_hierarchy()
    if request.method == "POST":
        form = CompanyHierarchyForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, "Organization hierarchy updated.")
            return redirect("org_hierarchy")
    else:
        form = CompanyHierarchyForm(instance=config)
    return render(request, "director/hierarchy_manage.html", {"form": form})


@login_required
@admin_or_ceo_required
def hr_employee_portal(request: HttpRequest, pk: int) -> HttpResponse:
    employee = get_object_or_404(User, pk=pk, role=UserRole.EMPLOYEE)
    today = timezone.localdate()
    record = today_status(employee=employee)
    can_check_in = False
    can_check_out = False
    history = Attendance.objects.filter(employee=employee).order_by("-date")[:60]
    calendar = _month_calendar_events(today, approved_only=True)
    praise_letters = PraiseLetter.objects.filter(employee=employee).select_related("issued_by").order_by("-issued_at")[:10]
    leave_summary = get_leave_summary(employee=employee, for_date=today)
    my_regularizations = AttendanceRegularizationRequest.objects.filter(employee=employee).order_by("-created_at")[:10]
    my_leave_requests = LeaveRequest.objects.filter(employee=employee).order_by("-created_at")[:8]
    viewer = "CEO" if request.user.role == UserRole.CEO else "HR"
    messages.info(request, f"{viewer} view: {employee.employee_id} - {employee.username} (read-only).")
    portal_mode = "ceo_view" if request.user.role == UserRole.CEO else "hr_view"
    return render(
        request,
        "employee/dashboard.html",
        {
            "today": today,
            "record": record,
            "history": history,
            "upcoming_holidays": calendar["upcoming_holidays"],
            "extra_working_days": calendar["extra_working_days"],
            "praise_letters": praise_letters,
            "portal_mode": portal_mode,
            "portal_employee": employee,
            "can_check_in": can_check_in,
            "can_check_out": can_check_out,
            "on_leave_today": bool(record and record.status == AttendanceStatus.ON_LEAVE),
            "holiday_month": today.strftime("%B %Y"),
            "leave_summary": leave_summary,
            "my_regularizations": my_regularizations,
            "my_leave_requests": my_leave_requests,
        },
    )


@login_required
@employee_required
def employee_praise_letters(request: HttpRequest) -> HttpResponse:
    letters = PraiseLetter.objects.filter(employee=request.user).select_related("issued_by").order_by("-issued_at")
    PraiseLetter.objects.filter(employee=request.user, is_read=False).update(is_read=True)
    return render(request, "employee/praise_letters.html", {"letters": letters})


@login_required
@employee_required
def request_regularization(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = EmployeeRegularizationRequestForm(request.POST, employee=request.user)
        if form.is_valid():
            req = form.save(commit=False)
            req.employee = request.user
            req.save()
            messages.success(request, "Regularization request sent to HR.")
            return redirect("employee_dashboard")
    else:
        form = EmployeeRegularizationRequestForm(employee=request.user)
    return render(request, "employee/regularization_request.html", {"form": form})


def _wants_json(request: HttpRequest) -> bool:
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _attendance_action_response(request: HttpRequest, user: User, *, success_message: str) -> HttpResponse:
    if _wants_json(request):
        return JsonResponse({"success": True, "message": success_message})
    messages.success(request, success_message)
    return redirect(_attendance_redirect_url(user))


def _attendance_error_response(request: HttpRequest, message: str, *, status: int = 400) -> HttpResponse:
    if _wants_json(request):
        payload = {"success": False, "message": message}
        lowered = message.lower()
        if "not near the company" in lowered or "outside the office" in lowered or "cannot access" in lowered:
            payload["code"] = "outside_office"
            status = 403
        return JsonResponse(payload, status=status)
    messages.error(request, message)
    return render(request, "employee/action_error.html", {"message": message}, status=status)


@login_required
@self_attendance_required
def employee_check_in(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    try:
        ctx = verify_office_access(
            request,
            latitude=request.POST.get("latitude"),
            longitude=request.POST.get("longitude"),
        )
        check_in(employee=request.user, verification_context=ctx)
        log_portal_access(
            request,
            event_type="check_in",
            success=True,
            user=request.user,
            latitude=ctx.get("latitude"),
            longitude=ctx.get("longitude"),
            distance_m=ctx.get("distance_m"),
            client_ip=ctx.get("client_ip", ""),
            user_agent=ctx.get("user_agent", ""),
        )
    except LocationVerificationError as e:
        log_portal_access(
            request,
            event_type="check_in",
            success=False,
            user=request.user,
            failure_reason=str(e),
        )
        return _attendance_error_response(request, str(e))
    except AttendanceError as e:
        return _attendance_error_response(request, str(e))
    return _attendance_action_response(request, request.user, success_message="Checked in successfully.")


@login_required
@self_attendance_required
def employee_check_out(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    try:
        ctx = verify_office_access(
            request,
            latitude=request.POST.get("latitude"),
            longitude=request.POST.get("longitude"),
        )
        check_out(employee=request.user, verification_context=ctx)
        log_portal_access(
            request,
            event_type="check_out",
            success=True,
            user=request.user,
            latitude=ctx.get("latitude"),
            longitude=ctx.get("longitude"),
            distance_m=ctx.get("distance_m"),
            client_ip=ctx.get("client_ip", ""),
            user_agent=ctx.get("user_agent", ""),
        )
    except LocationVerificationError as e:
        log_portal_access(
            request,
            event_type="check_out",
            success=False,
            user=request.user,
            failure_reason=str(e),
        )
        return _attendance_error_response(request, str(e))
    except AttendanceError as e:
        return _attendance_error_response(request, str(e))
    return _attendance_action_response(request, request.user, success_message="Checked out successfully.")


@login_required
@admin_or_ceo_required
def admin_dashboard(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    soon = (
        Holiday.objects.filter(
            date__gte=today,
            date__lte=today + timezone.timedelta(days=7),
            approval_status=HolidayApprovalStatus.APPROVED,
            event_type=HolidayEventType.HOLIDAY,
        )
        .order_by("date")[:3]
    )
    if soon:
        messages.info(request, f"Upcoming holiday: {soon[0].name} on {soon[0].date}")
    _notify_holiday_announcements(request)
    today_md = (today.month, today.day)
    bdays = User.objects.filter(role=UserRole.EMPLOYEE, date_of_birth__month=today_md[0], date_of_birth__day=today_md[1])
    anns = User.objects.filter(
        role=UserRole.EMPLOYEE, anniversary_date__month=today_md[0], anniversary_date__day=today_md[1]
    )
    if bdays.exists():
        messages.info(request, f"Birthdays today: {', '.join([u.username for u in bdays[:5]])}")
    if anns.exists():
        messages.info(request, f"Work anniversaries today: {', '.join([u.username for u in anns[:5]])}")

    total_employees = User.objects.filter(role=UserRole.EMPLOYEE).count()
    present_today = _count_present_today(today)
    on_leave_today = _count_on_leave_today(today)
    late_today = Attendance.objects.filter(
        date=today, is_late=True, employee__role=UserRole.EMPLOYEE
    ).count()
    half_day_today = Attendance.objects.filter(
        date=today, status=AttendanceStatus.HALF_DAY, employee__role=UserRole.EMPLOYEE
    ).count()
    overtime_today_total = (
        Attendance.objects.filter(date=today, employee__role=UserRole.EMPLOYEE).aggregate(
            total=Sum("overtime_hours")
        )["total"]
        or 0
    )
    today_overtime = (
        Attendance.objects.select_related("employee")
        .filter(date=today, overtime_hours__gt=0, employee__role=UserRole.EMPLOYEE)
        .order_by("-overtime_hours")[:20]
    )

    accounted = present_today + on_leave_today
    absent_today = max(total_employees - accounted, 0)

    # Live employee-only board (includes staff who have not marked yet).
    today_attendance_board = _today_employee_attendance_board(today)
    recent = (
        Attendance.objects.select_related("employee")
        .filter(date=today, employee__role=UserRole.EMPLOYEE)
        .order_by("-check_in", "employee__employee_id")
    )
    # HR/CEO dashboard shows all calendar entries (incl. pending) so approvals stay visible.
    calendar = _month_calendar_events(today, approved_only=False)
    pending_regularizations = AttendanceRegularizationRequest.objects.filter(
        status=RegularizationStatus.PENDING
    ).select_related("employee")[:8]
    pending_leave_requests = (
        LeaveRequest.objects.filter(status=LeaveRequestStatus.PENDING)
        .select_related("employee")
        .order_by("-created_at")[:10]
    )
    pending_leave_count = LeaveRequest.objects.filter(status=LeaveRequestStatus.PENDING).count()
    pending_holidays = (
        Holiday.objects.filter(approval_status=HolidayApprovalStatus.PENDING)
        .order_by("date")[:8]
    )
    pending_holiday_count = Holiday.objects.filter(approval_status=HolidayApprovalStatus.PENDING).count()
    if pending_leave_count:
        messages.warning(
            request,
            f"{pending_leave_count} leave request(s) waiting for HR/CEO approval.",
        )
    if pending_holiday_count:
        messages.info(
            request,
            f"{pending_holiday_count} holiday/extra-day entry(ies) waiting for dual HR + CEO approval.",
        )
    recent_praise_letters = PraiseLetter.objects.select_related("employee", "issued_by").order_by("-issued_at")[:8]

    return render(
        request,
        "admin/dashboard.html",
        {
            "today": today,
            "total_employees": total_employees,
            "present_today": present_today,
            "absent_today": max(absent_today, 0),
            "on_leave_today": on_leave_today,
            "late_today": late_today,
            "half_day_today": half_day_today,
            "overtime_today_total": overtime_today_total,
            "today_overtime": today_overtime,
            "recent": recent,
            "today_attendance_board": today_attendance_board,
            "upcoming_holidays": calendar["upcoming_holidays"],
            "extra_working_days": calendar["extra_working_days"],
            "pending_regularizations": pending_regularizations,
            "pending_leave_requests": pending_leave_requests,
            "pending_leave_count": pending_leave_count,
            "pending_holidays": pending_holidays,
            "pending_holiday_count": pending_holiday_count,
            "recent_praise_letters": recent_praise_letters,
            "holiday_month": today.strftime("%B %Y"),
            "export_month": today.month,
            "export_year": today.year,
            "month_choices": list(range(1, 13)),
            "is_ceo_mode": request.user.role == UserRole.CEO,
            **_own_attendance_context(request.user),
        },
    )


@login_required
@ceo_required
def ceo_holiday_announce(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = CeoHolidayAnnounceForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            holiday, _created = Holiday.objects.update_or_create(
                date=data["date"],
                defaults={
                    "name": data["name"],
                    "event_type": data["event_type"],
                    "ceo_message": data["ceo_message"],
                    "is_optional": False,
                    "approval_status": HolidayApprovalStatus.PENDING,
                    "hr_approved_by": None,
                    "hr_approved_at": None,
                },
            )
            holiday.apply_role_approval(request.user)
            holiday.save()
            HolidayAnnouncementRead.objects.filter(holiday=holiday).delete()
            label = "Extra working day" if holiday.event_type == HolidayEventType.EXTRA_WORKING else "Holiday"
            if holiday.approval_status == HolidayApprovalStatus.APPROVED:
                messages.success(request, f"{label} on {holiday.date} is approved and visible to staff.")
            else:
                messages.success(
                    request,
                    f"CEO approved {label.lower()} on {holiday.date}. Waiting for HR approval before staff can see it.",
                )
            return redirect("holiday_list")
    else:
        form = CeoHolidayAnnounceForm()
    return render(request, "ceo/holidays/announce.html", {"form": form})


@login_required
@ceo_required
def praise_letter_list(request: HttpRequest) -> HttpResponse:
    qs = PraiseLetter.objects.select_related("employee", "issued_by").order_by("-issued_at")
    employee_id = request.GET.get("employee_id", "").strip()
    if employee_id:
        qs = qs.filter(employee__employee_id__icontains=employee_id)
    return render(request, "ceo/praise/list.html", {"letters": qs[:300], "employee_id": employee_id})


@login_required
@ceo_required
def praise_letter_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = PraiseLetterForm(request.POST, request.FILES)
        if form.is_valid():
            letter = form.save(commit=False)
            letter.issued_by = request.user
            letter.save()
            messages.success(
                request,
                f"Praise letter sent to {letter.employee.employee_id} — {letter.employee.username}.",
            )
            return redirect("praise_letter_list")
    else:
        employee_pk = request.GET.get("employee")
        initial = {}
        if employee_pk:
            emp = User.objects.filter(pk=employee_pk, role=UserRole.EMPLOYEE).first()
            if emp:
                initial["employee"] = emp
        form = PraiseLetterForm(initial=initial)
    return render(request, "ceo/praise/form.html", {"form": form, "title": "Issue Praise Letter"})


@login_required
@ceo_required
def praise_letter_detail(request: HttpRequest, pk: int) -> HttpResponse:
    letter = get_object_or_404(PraiseLetter.objects.select_related("employee", "issued_by"), pk=pk)
    return render(request, "ceo/praise/detail.html", {"letter": letter})


@login_required
@ceo_required
def ceo_regularization_override(request: HttpRequest, pk: int) -> HttpResponse:
    reg_req = get_object_or_404(
        AttendanceRegularizationRequest.objects.select_related("employee", "reviewed_by"), pk=pk
    )

    if request.method == "POST":
        action = request.POST.get("action")
        form = CeoRegularizationOverrideForm(request.POST)
        if action == "reject":
            # Only undo attendance if HR (or prior CEO) had already approved it.
            if reg_req.status == RegularizationStatus.APPROVED:
                reverse_leave_deduction_for_date(employee=reg_req.employee, att_date=reg_req.date)
                Attendance.objects.filter(employee=reg_req.employee, date=reg_req.date).delete()
            reg_req.status = RegularizationStatus.REJECTED
            reg_req.ceo_note = request.POST.get("ceo_note", "").strip()
            reg_req.ceo_reviewed_by = request.user
            reg_req.ceo_reviewed_at = timezone.now()
            reg_req.save()
            messages.success(request, "CEO overruled — regularization rejected. Attendance updated everywhere.")
            return redirect("regularization_request_list")

        if form.is_valid():
            check_in = form.cleaned_data.get("check_in")
            if not check_in:
                form.add_error("check_in", "Check-in time is required when approving.")
            else:
                try:
                    regularize_attendance(
                        employee=reg_req.employee,
                        att_date=reg_req.date,
                        check_in=check_in,
                        check_out=None,
                    )
                except AttendanceError as e:
                    messages.error(request, str(e))
                    return render(
                        request,
                        "ceo/regularization/override.html",
                        {"reg_req": reg_req, "form": form},
                    )
                reg_req.status = RegularizationStatus.APPROVED
                reg_req.ceo_note = form.cleaned_data.get("ceo_note", "")
                reg_req.ceo_reviewed_by = request.user
                reg_req.ceo_reviewed_at = timezone.now()
                reg_req.save()
                messages.success(request, "CEO overruled — regularization approved. Visible on all attendance pages.")
                return redirect(f"{reverse('regularization_request_list')}?status=approved")
    else:
        form = CeoRegularizationOverrideForm()

    return render(
        request,
        "ceo/regularization/override.html",
        {"reg_req": reg_req, "form": form},
    )


@login_required
@admin_or_ceo_required
def holiday_list(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    month = request.GET.get("month", "").strip()
    year = request.GET.get("year", "").strip()
    status = request.GET.get("status", "").strip()

    try:
        month_i = int(month) if month else today.month
        year_i = int(year) if year else today.year
        month_i = max(1, min(12, month_i))
    except ValueError:
        month_i = today.month
        year_i = today.year

    month_start = date(year_i, month_i, 1)
    month_end = (month_start + timezone.timedelta(days=32)).replace(day=1) - timezone.timedelta(days=1)

    qs = (
        Holiday.objects.filter(date__gte=month_start, date__lte=month_end)
        .select_related("hr_approved_by", "ceo_approved_by")
        .order_by("date")
    )
    if status in {HolidayApprovalStatus.PENDING, HolidayApprovalStatus.APPROVED, HolidayApprovalStatus.REJECTED}:
        qs = qs.filter(approval_status=status)

    pending_count = Holiday.objects.filter(approval_status=HolidayApprovalStatus.PENDING).count()
    return render(
        request,
        "admin/holidays/list.html",
        {
            "holidays": qs,
            "month": month_i,
            "year": year_i,
            "month_label": month_start.strftime("%B %Y"),
            "is_ceo_mode": request.user.role == UserRole.CEO,
            "is_hr_mode": request.user.role == UserRole.ADMIN,
            "status_filter": status,
            "pending_count": pending_count,
        },
    )


@login_required
@admin_or_ceo_required
def holiday_create(request: HttpRequest) -> HttpResponse:
    ceo_mode = request.user.role == UserRole.CEO
    if request.method == "POST":
        form = HolidayForm(request.POST, ceo_mode=ceo_mode)
        if form.is_valid():
            holiday = form.save(commit=False, announced_by=request.user if ceo_mode else None)
            holiday.approval_status = HolidayApprovalStatus.PENDING
            holiday.hr_approved_by = None
            holiday.hr_approved_at = None
            holiday.ceo_approved_by = None
            holiday.ceo_approved_at = None
            holiday.announcement_active = False
            holiday.save()
            holiday.apply_role_approval(request.user)
            holiday.save()
            if holiday.approval_status == HolidayApprovalStatus.APPROVED:
                messages.success(request, "Calendar entry approved and visible to employees.")
            else:
                waiting = "CEO" if request.user.role == UserRole.ADMIN else "HR"
                messages.success(request, f"Calendar entry saved. Waiting for {waiting} approval.")
            return redirect("holiday_list")
    else:
        form = HolidayForm(ceo_mode=ceo_mode)
    title = "Add Holiday / Extra Working Day"
    return render(request, "admin/holidays/form.html", {"form": form, "title": title, "ceo_mode": ceo_mode})


@login_required
@admin_or_ceo_required
def holiday_update(request: HttpRequest, pk: int) -> HttpResponse:
    holiday = get_object_or_404(Holiday, pk=pk)
    ceo_mode = request.user.role == UserRole.CEO
    if request.method == "POST":
        form = HolidayForm(request.POST, instance=holiday, ceo_mode=ceo_mode)
        if form.is_valid():
            holiday = form.save(commit=False, announced_by=request.user if ceo_mode else None)
            # Edits require fresh dual approval so staff don't see unreviewed changes.
            holiday.approval_status = HolidayApprovalStatus.PENDING
            holiday.hr_approved_by = None
            holiday.hr_approved_at = None
            holiday.ceo_approved_by = None
            holiday.ceo_approved_at = None
            holiday.announcement_active = False
            holiday.save()
            holiday.apply_role_approval(request.user)
            holiday.save()
            waiting = "CEO" if request.user.role == UserRole.ADMIN else "HR"
            if holiday.approval_status == HolidayApprovalStatus.APPROVED:
                messages.success(request, "Calendar entry updated and approved.")
            else:
                messages.success(request, f"Calendar entry updated. Waiting for {waiting} approval.")
            return redirect("holiday_list")
    else:
        form = HolidayForm(instance=holiday, ceo_mode=ceo_mode)
    return render(
        request,
        "admin/holidays/form.html",
        {"form": form, "title": "Update Calendar Entry", "ceo_mode": ceo_mode},
    )


@login_required
@admin_or_ceo_required
def holiday_approve(request: HttpRequest, pk: int) -> HttpResponse:
    holiday = get_object_or_404(Holiday, pk=pk)
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    action = request.POST.get("action", "approve")
    note = request.POST.get("note", "").strip()
    if action == "reject":
        holiday.reject_by(request.user, note=note)
        holiday.save()
        HolidayAnnouncementRead.objects.filter(holiday=holiday).delete()
        messages.success(request, f"Rejected calendar entry for {holiday.date}. Hidden from employee pages.")
    else:
        holiday.apply_role_approval(request.user, note=note)
        holiday.save()
        if holiday.approval_status == HolidayApprovalStatus.APPROVED:
            HolidayAnnouncementRead.objects.filter(holiday=holiday).delete()
            messages.success(
                request,
                f"{holiday.name} on {holiday.date} is fully approved (HR + CEO) and now visible to all employees.",
            )
        else:
            waiting = "CEO" if request.user.role == UserRole.ADMIN else "HR"
            messages.success(request, f"Your approval saved. Waiting for {waiting} before staff can see it.")
    return redirect("holiday_list")


@login_required
@admin_or_ceo_required
def holiday_delete(request: HttpRequest, pk: int) -> HttpResponse:
    holiday = get_object_or_404(Holiday, pk=pk)
    if request.method == "POST":
        holiday.delete()
        messages.success(request, "Holiday deleted.")
        return redirect("holiday_list")
    return render(request, "admin/holidays/delete.html", {"holiday": holiday})


@login_required
@admin_or_ceo_required
def employee_list(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    qs = (
        User.objects.filter(role=UserRole.EMPLOYEE)
        .annotate(
            pending_leaves=Count(
                "leave_requests",
                filter=Q(leave_requests__status=LeaveRequestStatus.PENDING),
            ),
            total_leaves=Count("leave_requests"),
        )
        .order_by("employee_id")
    )
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(employee_id__icontains=q) | Q(username__icontains=q) | Q(department__icontains=q))

    employees = list(qs)
    today_map = {
        row.employee_id: row
        for row in Attendance.objects.filter(
            date=today, employee_id__in=[e.id for e in employees]
        )
    }
    for emp in employees:
        balance = ensure_monthly_leave_balance(employee=emp, for_date=today)
        emp.leave_remaining = balance.remaining
        emp.leave_used = balance.used_leaves
        att = today_map.get(emp.id)
        emp.today_record = att
        emp.today_status = att.status if att else "Not marked"
        emp.today_check_in = att.check_in if att else None
        emp.today_check_out = att.check_out if att else None

    return render(
        request,
        "admin/employees/list.html",
        {
            "employees": employees,
            "q": q,
            "leave_month": today.strftime("%B %Y"),
            "today": today,
        },
    )


@login_required
@admin_or_ceo_required
def employee_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = EmployeeUpsertForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Employee created successfully.")
            return redirect("employee_list")
    else:
        form = EmployeeUpsertForm(initial={"role": UserRole.EMPLOYEE, "is_active": True})
    return render(request, "admin/employees/form.html", {"form": form, "title": "Add Employee"})


@login_required
@admin_or_ceo_required
def employee_update(request: HttpRequest, pk: int) -> HttpResponse:
    employee = get_object_or_404(User, pk=pk, role=UserRole.EMPLOYEE)
    today = timezone.localdate()
    leave_summary = get_leave_summary(employee=employee, for_date=today)
    leave_requests = LeaveRequest.objects.filter(employee=employee).order_by("-created_at")[:8]
    if request.method == "POST":
        form = EmployeeUpsertForm(request.POST, instance=employee)
        if form.is_valid():
            # Prevent role escalation via employee edit form.
            updated = form.save(commit=False)
            updated.role = UserRole.EMPLOYEE
            updated.is_staff = False
            updated.save()
            messages.success(request, "Employee record updated. Leave and attendance data are unchanged.")
            return redirect("hr_employee_record", pk=employee.pk)
    else:
        form = EmployeeUpsertForm(instance=employee)
    return render(
        request,
        "admin/employees/form.html",
        {
            "form": form,
            "title": "Update Employee",
            "employee": employee,
            "leave_summary": leave_summary,
            "leave_requests": leave_requests,
        },
    )


@login_required
@admin_or_ceo_required
def hr_employee_record(request: HttpRequest, pk: int) -> HttpResponse:
    """Full live employee record for HR and CEO: profile, leave, attendance, regularization."""
    employee = get_object_or_404(User, pk=pk, role=UserRole.EMPLOYEE)
    today = timezone.localdate()
    try:
        month = int(request.GET.get("month", today.month))
        year = int(request.GET.get("year", today.year))
        month = max(1, min(12, month))
        year = max(2020, min(2100, year))
    except (TypeError, ValueError):
        month, year = today.month, today.year

    leave_summary = get_leave_summary(employee=employee, for_date=date(year, month, 1))
    leave_requests = (
        LeaveRequest.objects.filter(employee=employee)
        .select_related("reviewed_by")
        .order_by("-created_at")
    )
    attendance_records = list(
        Attendance.objects.filter(employee=employee, date__year=year, date__month=month).order_by("-date")
    )
    regularizations = (
        AttendanceRegularizationRequest.objects.filter(employee=employee)
        .select_related("reviewed_by", "ceo_reviewed_by")
        .order_by("-created_at")[:20]
    )
    balances = MonthlyLeaveBalance.objects.filter(employee=employee).order_by("-year", "-month")[:12]
    payslips = PaySlip.objects.filter(employee=employee).order_by("-year", "-month")[:12]
    praise_letters = PraiseLetter.objects.filter(employee=employee).select_related("issued_by").order_by("-issued_at")[:8]

    leave_counts = {
        "total": leave_requests.count(),
        "pending": leave_requests.filter(status=LeaveRequestStatus.PENDING).count(),
        "approved": leave_requests.filter(status=LeaveRequestStatus.APPROVED).count(),
        "rejected": leave_requests.filter(status=LeaveRequestStatus.REJECTED).count(),
    }

    return render(
        request,
        "admin/employees/record.html",
        {
            "employee": employee,
            "leave_summary": leave_summary,
            "leave_requests": leave_requests[:100],
            "leave_counts": leave_counts,
            "attendance_records": attendance_records,
            "regularizations": regularizations,
            "balances": balances,
            "payslips": payslips,
            "praise_letters": praise_letters,
            "month": month,
            "year": year,
            "month_label": date(year, month, 1).strftime("%B %Y"),
            "month_choices": list(range(1, 13)),
            "is_ceo_mode": request.user.role == UserRole.CEO,
        },
    )


@login_required
@admin_or_ceo_required
def employee_delete(request: HttpRequest, pk: int) -> HttpResponse:
    employee = get_object_or_404(User, pk=pk, role=UserRole.EMPLOYEE)
    if request.method == "POST":
        employee.delete()
        return redirect("employee_list")
    return render(request, "admin/employees/delete.html", {"employee": employee})


@login_required
@admin_or_ceo_required
def admin_attendance_list(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    # Employee check-in/out only — HR/CEO self punches are not mixed into staff records.
    qs = Attendance.objects.select_related("employee").filter(employee__role=UserRole.EMPLOYEE)

    raw_date = request.GET.get("date")
    raw_month = request.GET.get("month")
    raw_year = request.GET.get("year")
    # Default landing: today's live punches so new check-in/out appear immediately.
    if raw_date is None and raw_month is None and raw_year is None:
        filter_date = today.isoformat()
    else:
        filter_date = (raw_date or "").strip()

    employee_id = request.GET.get("employee_id", "").strip()
    department = request.GET.get("department", "").strip()
    status = request.GET.get("status", "").strip()
    month_i = _parse_int((raw_month or str(today.month)).strip()) or today.month
    year_i = _parse_int((raw_year or str(today.year)).strip()) or today.year
    month_i = max(1, min(12, month_i))
    year_i = max(2020, min(2100, year_i))

    if filter_date:
        qs = qs.filter(date=filter_date)
        period_label = filter_date
    else:
        qs = qs.filter(date__year=year_i, date__month=month_i)
        period_label = date(year_i, month_i, 1).strftime("%B %Y")

    if employee_id:
        qs = qs.filter(employee__employee_id__icontains=employee_id)
    if department:
        qs = qs.filter(employee__department__icontains=department)
    if status in {
        AttendanceStatus.PRESENT,
        AttendanceStatus.HALF_DAY,
        AttendanceStatus.ABSENT,
        AttendanceStatus.FULL_DAY,
        AttendanceStatus.ON_LEAVE,
    }:
        qs = qs.filter(status=status)

    records = list(qs.order_by("-date", "employee__employee_id")[:1000])
    today_attendance_board = _today_employee_attendance_board(today) if filter_date == today.isoformat() else []
    month_labels = [
        (1, "January"),
        (2, "February"),
        (3, "March"),
        (4, "April"),
        (5, "May"),
        (6, "June"),
        (7, "July"),
        (8, "August"),
        (9, "September"),
        (10, "October"),
        (11, "November"),
        (12, "December"),
    ]
    response = render(
        request,
        "admin/attendance/list.html",
        {
            "records": records,
            "record_count": len(records),
            "period_label": period_label,
            "present_count": sum(1 for r in records if r.status in (AttendanceStatus.PRESENT, AttendanceStatus.FULL_DAY)),
            "half_day_count": sum(1 for r in records if r.status == AttendanceStatus.HALF_DAY),
            "absent_count": sum(1 for r in records if r.status == AttendanceStatus.ABSENT),
            "on_leave_count": sum(1 for r in records if r.status == AttendanceStatus.ON_LEAVE),
            "today_attendance_board": today_attendance_board,
            "show_today_board": bool(today_attendance_board),
            "filters": {
                "date": filter_date,
                "employee_id": employee_id,
                "department": department,
                "month": str(month_i),
                "year": str(year_i),
                "status": status,
            },
            "month_choices": list(range(1, 13)),
            "month_labels": month_labels,
            "is_ceo_mode": request.user.role == UserRole.CEO,
            "today": today,
        },
    )
    return response




def _parse_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _attendance_export_queryset(request: HttpRequest):
    qs = Attendance.objects.select_related("employee").filter(employee__role=UserRole.EMPLOYEE)
    scope = request.GET.get("scope", "").strip().lower()
    date = request.GET.get("date", "").strip()
    employee_id = request.GET.get("employee_id", "").strip()
    department = request.GET.get("department", "").strip()
    month = _parse_int(request.GET.get("month", "").strip())
    year = _parse_int(request.GET.get("year", "").strip())

    if scope == "all":
        pass
    elif date:
        qs = qs.filter(date=date)
    elif month and year:
        qs = qs.filter(date__year=year, date__month=month)
    else:
        today = timezone.localdate()
        qs = qs.filter(date__year=today.year, date__month=today.month)

    if employee_id:
        qs = qs.filter(employee__employee_id__icontains=employee_id)
    if department:
        qs = qs.filter(employee__department__icontains=department)

    return qs.order_by("-date", "employee__employee_id")


def _attendance_export_filename(request: HttpRequest, ext: str) -> str:
    scope = request.GET.get("scope", "").strip().lower()
    if scope == "all":
        return f"attendance_all.{ext}"
    date = request.GET.get("date", "").strip()
    month = _parse_int(request.GET.get("month", "").strip())
    year = _parse_int(request.GET.get("year", "").strip())
    if date:
        return f"attendance_{date}.{ext}"
    if month and year:
        return f"attendance_{year}_{month:02d}.{ext}"
    today = timezone.localdate()
    return f"attendance_{today.year}_{today.month:02d}.{ext}"


@login_required
@admin_or_ceo_required
def attendance_regularize(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = AttendanceRegularizeForm(request.POST)
        if form.is_valid():
            try:
                att = form.save()
            except AttendanceError as e:
                messages.error(request, str(e))
                return render(request, "admin/attendance/regularize.html", {"form": form})
            messages.success(
                request,
                f"Attendance regularized for {att.employee.employee_id} on {att.date}. Visible on all pages.",
            )
            return redirect("admin_attendance_list")
    else:
        form = AttendanceRegularizeForm()
    return render(request, "admin/attendance/regularize.html", {"form": form})


@login_required
@admin_or_ceo_required
def regularization_request_list(request: HttpRequest) -> HttpResponse:
    qs = AttendanceRegularizationRequest.objects.select_related("employee", "reviewed_by").all()
    status = request.GET.get("status", RegularizationStatus.PENDING).strip()
    if status:
        qs = qs.filter(status=status)
    return render(
        request,
        "admin/regularization/list.html",
        {
            "requests": qs[:300],
            "status": status,
            "is_ceo_mode": request.user.role == UserRole.CEO,
        },
    )


@login_required
@admin_or_ceo_required
def regularization_review(request: HttpRequest, pk: int) -> HttpResponse:
    reg_req = get_object_or_404(
        AttendanceRegularizationRequest.objects.select_related("employee"), pk=pk
    )

    if reg_req.status != RegularizationStatus.PENDING:
        messages.info(request, "This request is already processed.")
        return redirect("regularization_request_list")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "reject":
            reg_req.status = RegularizationStatus.REJECTED
            reg_req.hr_note = request.POST.get("hr_note", "").strip()
            reg_req.reviewed_by = request.user
            reg_req.reviewed_at = timezone.now()
            reg_req.save()
            messages.success(request, "Regularization request rejected.")
            return redirect("regularization_request_list")

        form = HrRegularizationApproveForm(request.POST)
        if form.is_valid():
            try:
                regularize_attendance(
                    employee=reg_req.employee,
                    att_date=reg_req.date,
                    check_in=form.cleaned_data["check_in"],
                    check_out=None,
                )
            except AttendanceError as e:
                messages.error(request, str(e))
                return render(
                    request,
                    "admin/regularization/review.html",
                    {"reg_req": reg_req, "form": form},
                )
            reg_req.status = RegularizationStatus.APPROVED
            reg_req.hr_note = form.cleaned_data.get("hr_note", "")
            reg_req.reviewed_by = request.user
            reg_req.reviewed_at = timezone.now()
            reg_req.save()
            messages.success(request, "Attendance marked and request approved. Visible on all attendance pages.")
            return redirect(f"{reverse('regularization_request_list')}?status=approved")
    else:
        form = HrRegularizationApproveForm()

    return render(
        request,
        "admin/regularization/review.html",
        {"reg_req": reg_req, "form": form},
    )


@login_required
@admin_or_ceo_required
def export_attendance_csv(request: HttpRequest) -> HttpResponse:
    import csv

    qs = _attendance_export_queryset(request)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{_attendance_export_filename(request, "csv")}"'

    writer = csv.writer(response)
    writer.writerow(
        [
            "Employee ID",
            "Name",
            "Department",
            "Date",
            "Check In",
            "Check Out",
            "Working Hours",
            "Overtime Hours",
            "Status",
            "Late",
        ]
    )
    for r in qs:
        writer.writerow(
            [
                r.employee.employee_id,
                r.employee.username,
                r.employee.department,
                r.date,
                r.check_in,
                r.check_out,
                r.working_hours,
                r.overtime_hours,
                r.status,
                "Yes" if r.is_late else "No",
            ]
        )
    return response


@login_required
@admin_or_ceo_required
def export_attendance_pdf(request: HttpRequest) -> HttpResponse:
    from io import BytesIO

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas

    qs = _attendance_export_queryset(request)

    buf = BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    y = height - 2 * cm
    p.setFont("Helvetica-Bold", 14)
    p.drawString(2 * cm, y, f"Attendance Report — {_attendance_export_filename(request, 'pdf').replace('.pdf', '')}")
    y -= 1.2 * cm

    p.setFont("Helvetica", 9)
    headers = ["EmpID", "Name", "Dept", "Date", "In", "Out", "Hrs", "OT", "Status", "Late"]
    p.drawString(2 * cm, y, " | ".join(headers))
    y -= 0.6 * cm
    p.line(2 * cm, y, width - 2 * cm, y)
    y -= 0.4 * cm

    for r in qs[:600]:
        if y < 2 * cm:
            p.showPage()
            y = height - 2 * cm
            p.setFont("Helvetica", 9)
        row = [
            r.employee.employee_id,
            r.employee.username[:14],
            (r.employee.department or "")[:10],
            str(r.date),
            r.check_in.strftime("%H:%M") if r.check_in else "",
            r.check_out.strftime("%H:%M") if r.check_out else "",
            str(r.working_hours),
            str(r.overtime_hours),
            r.status,
            "Y" if r.is_late else "N",
        ]
        p.drawString(2 * cm, y, " | ".join(row))
        y -= 0.5 * cm

    p.showPage()
    p.save()
    pdf = buf.getvalue()
    buf.close()

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="attendance_report.pdf"'
    response.write(pdf)
    return response


@login_required
@ceo_required
def ceo_dashboard(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    month_start = today.replace(day=1)

    total_employees = User.objects.filter(role=UserRole.EMPLOYEE).count()
    hr_count = User.objects.filter(role=UserRole.ADMIN).count()
    present_today = _count_present_today(today)
    on_leave_today = _count_on_leave_today(today)
    absent_today = max(total_employees - present_today - on_leave_today, 0)
    pending_regularizations = AttendanceRegularizationRequest.objects.filter(
        status=RegularizationStatus.PENDING
    ).count()
    pending_leave_count = LeaveRequest.objects.filter(status=LeaveRequestStatus.PENDING).count()
    pending_leave_requests = (
        LeaveRequest.objects.filter(status=LeaveRequestStatus.PENDING)
        .select_related("employee")
        .order_by("-created_at")[:10]
    )
    pending_holiday_count = Holiday.objects.filter(approval_status=HolidayApprovalStatus.PENDING).count()
    pending_holidays = Holiday.objects.filter(approval_status=HolidayApprovalStatus.PENDING).order_by("date")[:8]
    if pending_leave_count:
        messages.warning(
            request,
            f"{pending_leave_count} leave request(s) waiting for approval — open Leave Records to review.",
        )
    if pending_holiday_count:
        messages.info(
            request,
            f"{pending_holiday_count} holiday entry(ies) need the other role's approval (HR + CEO).",
        )
    _notify_holiday_announcements(request)
    praise_letters_sent = PraiseLetter.objects.filter(issued_by=request.user).count()
    praise_letters_month = PraiseLetter.objects.filter(issued_at__date__gte=month_start).count()
    ceo_overrides = AttendanceRegularizationRequest.objects.filter(ceo_reviewed_by__isnull=False).count()

    hr_team = []
    for hr in User.objects.filter(role=UserRole.ADMIN).order_by("employee_id"):
        hr_team.append(
            {
                "user": hr,
                "regularizations_this_month": AttendanceRegularizationRequest.objects.filter(
                    reviewed_by=hr, reviewed_at__date__gte=month_start
                ).count(),
            }
        )

    recent_praise = PraiseLetter.objects.select_related("employee").order_by("-issued_at")[:8]
    recent_overrides = (
        AttendanceRegularizationRequest.objects.filter(ceo_reviewed_by__isnull=False)
        .select_related("employee", "reviewed_by", "ceo_reviewed_by")
        .order_by("-ceo_reviewed_at")[:8]
    )
    pending_regs = AttendanceRegularizationRequest.objects.filter(
        status=RegularizationStatus.PENDING
    ).select_related("employee")[:8]
    today_attendance_board = _today_employee_attendance_board(today)
    recent = (
        Attendance.objects.select_related("employee")
        .filter(date=today, employee__role=UserRole.EMPLOYEE)
        .order_by("-check_in", "employee__employee_id")
    )

    return render(
        request,
        "ceo/dashboard.html",
        {
            "today": today,
            "total_employees": total_employees,
            "hr_count": hr_count,
            "present_today": present_today,
            "absent_today": absent_today,
            "on_leave_today": on_leave_today,
            "pending_regularizations": pending_regularizations,
            "pending_leave_count": pending_leave_count,
            "pending_leave_requests": pending_leave_requests,
            "pending_holiday_count": pending_holiday_count,
            "pending_holidays": pending_holidays,
            "praise_letters_sent": praise_letters_sent,
            "praise_letters_month": praise_letters_month,
            "ceo_overrides": ceo_overrides,
            "hr_team": hr_team,
            "recent_praise": recent_praise,
            "recent_overrides": recent_overrides,
            "pending_regs": pending_regs,
            "today_attendance_board": today_attendance_board,
            "recent": recent,
            "export_month": today.month,
            "export_year": today.year,
            "month_choices": list(range(1, 13)),
            **_own_attendance_context(request.user),
        },
    )


@login_required
@ceo_required
def ceo_hr_overview(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    month_start = today.replace(day=1)
    hr_team = []
    for hr in User.objects.filter(role=UserRole.ADMIN).order_by("employee_id"):
        hr_team.append(
            {
                "user": hr,
                "regularizations_this_month": AttendanceRegularizationRequest.objects.filter(
                    reviewed_by=hr, reviewed_at__date__gte=month_start
                ).count(),
            }
        )
    pending_regularizations = (
        AttendanceRegularizationRequest.objects.filter(status=RegularizationStatus.PENDING)
        .select_related("employee")
        .order_by("-created_at")[:50]
    )
    hr_decisions = (
        AttendanceRegularizationRequest.objects.exclude(status=RegularizationStatus.PENDING)
        .select_related("employee", "reviewed_by", "ceo_reviewed_by")
        .order_by("-reviewed_at")[:50]
    )
    return render(
        request,
        "ceo/hr/overview.html",
        {
            "hr_team": hr_team,
            "pending_regularizations": pending_regularizations,
            "hr_decisions": hr_decisions,
            "today": today,
        },
    )


def _file_download_response(file_field, download_name: str | None = None) -> FileResponse:
    name = download_name or file_field.name.split("/")[-1]
    return FileResponse(file_field.open("rb"), as_attachment=True, filename=name)


@login_required
def praise_letter_download(request: HttpRequest, pk: int) -> HttpResponse:
    letter = get_object_or_404(PraiseLetter.objects.select_related("employee"), pk=pk)
    # Owner, or HR/CEO viewing that employee's portal / praise list.
    can_download = (
        letter.employee_id == request.user.id
        or request.user.role in {UserRole.ADMIN, UserRole.CEO}
    )
    if not can_download:
        return HttpResponseBadRequest("You cannot download this praise letter.")
    if not letter.document:
        return HttpResponseBadRequest("No file attached to this praise letter.")
    return _file_download_response(letter.document, f"praise_{letter.employee.employee_id}_{letter.pk}.pdf")


@login_required
@employee_required
def employee_attendance_records(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    try:
        month = int(request.GET.get("month", today.month))
        year = int(request.GET.get("year", today.year))
        month = max(1, min(12, month))
        year = max(2020, min(2100, year))
    except (TypeError, ValueError):
        month, year = today.month, today.year

    records = list(
        Attendance.objects.filter(employee=request.user, date__year=year, date__month=month).order_by("-date")
    )
    half_days = sum(1 for r in records if r.status == AttendanceStatus.HALF_DAY)
    month_labels = [
        (1, "January"),
        (2, "February"),
        (3, "March"),
        (4, "April"),
        (5, "May"),
        (6, "June"),
        (7, "July"),
        (8, "August"),
        (9, "September"),
        (10, "October"),
        (11, "November"),
        (12, "December"),
    ]
    response = render(
        request,
        "employee/attendance_records.html",
        {
            "records": records,
            "filter_month": month,
            "filter_year": year,
            "month_choices": list(range(1, 13)),
            "month_labels": month_labels,
            "half_days": half_days,
            "record_count": len(records),
            "period_label": date(year, month, 1).strftime("%B %Y"),
        },
    )
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    return response


@login_required
@employee_required
def employee_leave_requests(request: HttpRequest) -> HttpResponse:
    requests_qs = LeaveRequest.objects.filter(employee=request.user).order_by("-created_at")
    return render(request, "employee/leave_requests.html", {"leave_requests": requests_qs})


@login_required
@employee_required
def leave_request_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = LeaveRequestForm(request.POST)
        if form.is_valid():
            req = form.save(commit=False)
            req.employee = request.user
            req.save()
            messages.success(
                request,
                "Leave request submitted. HR and CEO can see it under Leave Records and approve or reject it.",
            )
            return redirect("employee_leave_requests")
    else:
        form = LeaveRequestForm()
    return render(request, "employee/leave_request_form.html", {"form": form})


@login_required
@employee_required
def employee_payslips(request: HttpRequest) -> HttpResponse:
    slips = PaySlip.objects.filter(employee=request.user).order_by("-year", "-month")
    return render(request, "employee/payslips.html", {"payslips": slips})


@login_required
@employee_required
def employee_payslip_download(request: HttpRequest, pk: int) -> HttpResponse:
    slip = get_object_or_404(PaySlip, pk=pk, employee=request.user)
    return _file_download_response(slip.document, f"payslip_{slip.employee.employee_id}_{slip.year}_{slip.month:02d}.pdf")


def _hr_leave_queryset(request: HttpRequest):
    """Shared filters for HR leave list + CSV export (live DB records)."""
    # Default to pending so HR/CEO land on the approval queue.
    status = request.GET.get("status", "pending").strip()
    employee_q = request.GET.get("employee", "").strip()
    department = request.GET.get("department", "").strip()
    leave_type = request.GET.get("leave_type", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()

    qs = LeaveRequest.objects.select_related("employee", "reviewed_by").order_by("-created_at")
    if status in ("pending", "approved", "rejected"):
        qs = qs.filter(status=status)
    if employee_q:
        qs = qs.filter(
            Q(employee__employee_id__icontains=employee_q) | Q(employee__username__icontains=employee_q)
        )
    if department:
        qs = qs.filter(employee__department__icontains=department)
    if leave_type in {c.value for c in LeaveRequestType}:
        qs = qs.filter(leave_type=leave_type)
    if date_from:
        try:
            qs = qs.filter(end_date__gte=date.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            qs = qs.filter(start_date__lte=date.fromisoformat(date_to))
        except ValueError:
            pass
    return qs, {
        "status_filter": status or "all",
        "employee": employee_q,
        "department": department,
        "leave_type": leave_type,
        "date_from": date_from,
        "date_to": date_to,
    }


@login_required
@admin_or_ceo_required
def hr_leave_request_list(request: HttpRequest) -> HttpResponse:
    qs, filters = _hr_leave_queryset(request)
    counts = LeaveRequest.objects.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(status=LeaveRequestStatus.PENDING)),
        approved=Count("id", filter=Q(status=LeaveRequestStatus.APPROVED)),
        rejected=Count("id", filter=Q(status=LeaveRequestStatus.REJECTED)),
    )
    departments = (
        User.objects.filter(role=UserRole.EMPLOYEE)
        .exclude(department="")
        .values_list("department", flat=True)
        .distinct()
        .order_by("department")
    )
    response = render(
        request,
        "admin/leave/list.html",
        {
            "leave_requests": qs[:500],
            "counts": counts,
            "leave_types": LeaveRequestType.choices,
            "departments": departments,
            "result_count": qs.count(),
            **filters,
        },
    )
    response["Cache-Control"] = "no-store"
    return response


@login_required
@admin_or_ceo_required
def hr_leave_export_csv(request: HttpRequest) -> HttpResponse:
    import csv

    qs, _filters = _hr_leave_queryset(request)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="leave_applications.csv"'
    writer = csv.writer(response)
    writer.writerow(
        [
            "Employee ID",
            "Employee Name",
            "Department",
            "Leave Type",
            "Start Date",
            "End Date",
            "Days",
            "Reason",
            "Status",
            "HR Note",
            "Reviewed By",
            "Reviewed At",
            "Submitted At",
        ]
    )
    for lr in qs.iterator(chunk_size=200):
        writer.writerow(
            [
                lr.employee.employee_id,
                lr.employee.username,
                lr.employee.department or "",
                lr.get_leave_type_display(),
                lr.start_date.isoformat(),
                lr.end_date.isoformat(),
                lr.duration_days,
                lr.reason,
                lr.get_status_display(),
                lr.hr_note,
                lr.reviewed_by.employee_id if lr.reviewed_by_id else "",
                timezone.localtime(lr.reviewed_at).strftime("%Y-%m-%d %H:%M") if lr.reviewed_at else "",
                timezone.localtime(lr.created_at).strftime("%Y-%m-%d %H:%M"),
            ]
        )
    return response


@login_required
@admin_or_ceo_required
def hr_leave_balances(request: HttpRequest) -> HttpResponse:
    """Org-wide paid leave balances for the selected month (live)."""
    today = timezone.localdate()
    try:
        month = int(request.GET.get("month", today.month))
        year = int(request.GET.get("year", today.year))
        month = max(1, min(12, month))
        year = max(2020, min(2100, year))
    except (TypeError, ValueError):
        month, year = today.month, today.year

    for_date = date(year, month, 1)
    q = request.GET.get("q", "").strip()
    employees = User.objects.filter(role=UserRole.EMPLOYEE, is_active=True).order_by("employee_id")
    if q:
        employees = employees.filter(
            Q(employee_id__icontains=q) | Q(username__icontains=q) | Q(department__icontains=q)
        )

    rows = []
    for emp in employees:
        balance = ensure_monthly_leave_balance(employee=emp, for_date=for_date)
        summary = get_leave_summary(employee=emp, for_date=for_date)
        pending = LeaveRequest.objects.filter(employee=emp, status=LeaveRequestStatus.PENDING).count()
        rows.append(
            {
                "employee": emp,
                "balance": balance,
                "absences": summary["absences_this_month"],
                "on_leave_days": summary["on_leave_days"],
                "pending": pending,
            }
        )

    return render(
        request,
        "admin/leave/balances.html",
        {
            "rows": rows,
            "month": month,
            "year": year,
            "month_label": for_date.strftime("%B %Y"),
            "q": q,
            "month_choices": list(range(1, 13)),
        },
    )


@login_required
@admin_or_ceo_required
def hr_employee_leave_history(request: HttpRequest, pk: int) -> HttpResponse:
    """Full leave application + balance record for one employee."""
    employee = get_object_or_404(User, pk=pk, role=UserRole.EMPLOYEE)
    today = timezone.localdate()
    status = request.GET.get("status", "all").strip()
    leave_qs = LeaveRequest.objects.filter(employee=employee).select_related("reviewed_by").order_by("-created_at")
    if status in ("pending", "approved", "rejected"):
        leave_qs = leave_qs.filter(status=status)

    leave_summary = get_leave_summary(employee=employee, for_date=today)
    balances = MonthlyLeaveBalance.objects.filter(employee=employee).order_by("-year", "-month")[:24]

    return render(
        request,
        "admin/leave/employee_history.html",
        {
            "employee": employee,
            "leave_requests": leave_qs,
            "leave_summary": leave_summary,
            "balances": balances,
            "status_filter": status or "all",
        },
    )


@login_required
@admin_or_ceo_required
def hr_leave_request_review(request: HttpRequest, pk: int) -> HttpResponse:
    leave_req = get_object_or_404(
        LeaveRequest.objects.select_related("employee", "reviewed_by"), pk=pk
    )
    today = timezone.localdate()
    leave_summary = get_leave_summary(employee=leave_req.employee, for_date=today)
    prior_requests = (
        LeaveRequest.objects.filter(employee=leave_req.employee)
        .exclude(pk=leave_req.pk)
        .order_by("-created_at")[:12]
    )
    can_decide = leave_req.status == LeaveRequestStatus.PENDING

    if request.method == "POST":
        if not can_decide:
            messages.info(request, "This leave request is already processed. Record is kept for history.")
            return redirect("hr_leave_request_review", pk=pk)

        action = request.POST.get("action")
        form = HrLeaveReviewForm(request.POST)
        if form.is_valid():
            leave_req.hr_note = form.cleaned_data.get("hr_note", "")
            leave_req.reviewed_by = request.user
            leave_req.reviewed_at = timezone.now()
            if action == "approve":
                leave_req.status = LeaveRequestStatus.APPROVED
                leave_req.save()
                days = apply_approved_leave_request(leave_req=leave_req)
                messages.success(
                    request,
                    f"Leave approved for {days} day(s). Updated on employee portal, attendance, "
                    f"and leave balance for {leave_req.employee.employee_id}.",
                )
                return redirect(f"{reverse('hr_leave_request_list')}?status=approved&employee={leave_req.employee.employee_id}")
            elif action == "reject":
                leave_req.status = LeaveRequestStatus.REJECTED
                leave_req.save()
                messages.success(request, "Leave request rejected. Record retained in HR leave history.")
                return redirect(f"{reverse('hr_leave_request_list')}?status=rejected&employee={leave_req.employee.employee_id}")
            else:
                messages.error(request, "Invalid action.")
                return redirect("hr_leave_request_review", pk=pk)
    else:
        form = HrLeaveReviewForm(initial={"hr_note": leave_req.hr_note})

    return render(
        request,
        "admin/leave/review.html",
        {
            "leave_req": leave_req,
            "form": form,
            "leave_summary": leave_summary,
            "prior_requests": prior_requests,
            "can_decide": can_decide,
        },
    )


@login_required
@admin_or_ceo_required
def hr_payslip_list(request: HttpRequest) -> HttpResponse:
    slips = PaySlip.objects.select_related("employee", "uploaded_by").order_by("-year", "-month")[:300]
    return render(request, "admin/payslips/list.html", {"payslips": slips})


@login_required
@admin_or_ceo_required
def hr_payslip_download(request: HttpRequest, pk: int) -> HttpResponse:
    slip = get_object_or_404(PaySlip.objects.select_related("employee"), pk=pk)
    if not slip.document:
        return HttpResponseBadRequest("No file attached to this pay slip.")
    return _file_download_response(
        slip.document,
        f"payslip_{slip.employee.employee_id}_{slip.year}_{slip.month:02d}.pdf",
    )


@login_required
@admin_or_ceo_required
def hr_payslip_upload(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    if request.method == "POST":
        form = PaySlipUploadForm(request.POST, request.FILES)
        if form.is_valid():
            data = form.cleaned_data
            slip, _created = PaySlip.objects.update_or_create(
                employee=data["employee"],
                year=data["year"],
                month=data["month"],
                defaults={
                    "title": data.get("title") or "",
                    "document": data["document"],
                    "uploaded_by": request.user,
                },
            )
            messages.success(
                request,
                f"Pay slip uploaded for {slip.employee.employee_id} — {slip.period_label}.",
            )
            return redirect("hr_payslip_list")
    else:
        form = PaySlipUploadForm(initial={"year": today.year, "month": today.month})
    return render(request, "admin/payslips/upload.html", {"form": form})

