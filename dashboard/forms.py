from __future__ import annotations

from datetime import date, time

from django import forms
from django.utils import timezone

from accounts.models import PraiseLetter, User, UserRole
from accounts.models import CompanyHierarchy
from accounts.upload_validators import DOCUMENT_EXTENSIONS, PRAISE_EXTENSIONS, validate_upload_file
from .models import Holiday, HolidayAnnouncementRead, HolidayEventType
from attendance.models import Attendance, AttendanceRegularizationRequest, RegularizationStatus


class EmployeeUpsertForm(forms.ModelForm):
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
        help_text="Leave blank to keep the current password.",
    )

    class Meta:
        model = User
        # password is handled separately so a blank update never overwrites the hash
        fields = [
            "employee_id",
            "username",
            "email",
            "department",
            "role",
            "date_of_birth",
            "anniversary_date",
            "is_active",
        ]
        widgets = {
            "employee_id": forms.TextInput(attrs={"class": "form-control"}),
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "department": forms.TextInput(attrs={"class": "form-control"}),
            "role": forms.Select(attrs={"class": "form-select"}),
            "date_of_birth": forms.DateInput(attrs={"class": "form-control", "type": "date"}, format="%Y-%m-%d"),
            "anniversary_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}, format="%Y-%m-%d"
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date_of_birth"].input_formats = ["%Y-%m-%d"]
        self.fields["anniversary_date"].input_formats = ["%Y-%m-%d"]
        # New employees need a password; updates may leave it blank.
        if not self.instance.pk:
            self.fields["password"].required = True
            self.fields["password"].help_text = "Initial login password for this employee."
            self.fields["role"].initial = UserRole.EMPLOYEE
        else:
            # Employee records stay as employees — hide role to avoid accidental changes.
            self.fields["role"].widget = forms.HiddenInput()
            self.fields["role"].initial = UserRole.EMPLOYEE

    def clean_password(self):
        password = self.cleaned_data.get("password") or ""
        if not self.instance.pk and not password:
            raise forms.ValidationError("Password is required when creating an employee.")
        return password

    def save(self, commit=True):
        user: User = super().save(commit=False)
        pwd = self.cleaned_data.get("password")
        if pwd:
            user.set_password(pwd)
        # Keep Django admin access aligned with privileged roles
        if user.role in {UserRole.ADMIN, UserRole.CEO, UserRole.DIRECTOR}:
            user.is_staff = True
        elif user.role == UserRole.EMPLOYEE:
            user.is_staff = False
        if commit:
            user.save()
        return user


class HolidayForm(forms.ModelForm):
    class Meta:
        model = Holiday
        fields = ["date", "name", "event_type", "is_optional", "ceo_message"]
        widgets = {
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}, format="%Y-%m-%d"),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "event_type": forms.Select(attrs={"class": "form-select"}),
            "is_optional": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "ceo_message": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Message to all employees & HR (optional — CEO announcement)",
                }
            ),
        }

    def __init__(self, *args, ceo_mode: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].input_formats = ["%Y-%m-%d"]
        if not ceo_mode:
            self.fields.pop("ceo_message", None)
        else:
            self.fields["ceo_message"].help_text = (
                "Staff see the notice only after both CEO and HR approve this holiday."
            )

    def save(self, commit=True, *, announced_by=None):
        holiday: Holiday = super().save(commit=False)
        if announced_by:
            holiday.announced_by = announced_by
            holiday.announced_at = timezone.now()
        # Visibility / popup only after dual approval (handled in views).
        if holiday.approval_status != "approved":
            holiday.announcement_active = False
        if commit:
            holiday.save()
        return holiday


class CeoHolidayAnnounceForm(forms.ModelForm):
    """Quick CEO form to propose a holiday or extra working day (needs HR approval too)."""

    class Meta:
        model = Holiday
        fields = ["date", "name", "event_type", "ceo_message"]
        widgets = {
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}, format="%Y-%m-%d"),
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Diwali / company holiday"}),
            "event_type": forms.Select(attrs={"class": "form-select"}),
            "ceo_message": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 5,
                    "placeholder": "Write the official notice for employees and HR...",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].input_formats = ["%Y-%m-%d"]

    def save(self, commit=True, *, announced_by=None):
        holiday: Holiday = super().save(commit=False)
        holiday.is_optional = False
        holiday.announcement_active = False
        if announced_by:
            holiday.announced_by = announced_by
            holiday.announced_at = timezone.now()
        if commit:
            holiday.save()
        return holiday


class CompanyHierarchyForm(forms.ModelForm):
    class Meta:
        model = CompanyHierarchy
        fields = ["director_user", "ceo_user", "primary_hr_user"]
        widgets = {
            "director_user": forms.Select(attrs={"class": "form-select"}),
            "ceo_user": forms.Select(attrs={"class": "form-select"}),
            "primary_hr_user": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["director_user"].queryset = User.objects.filter(
            role=UserRole.DIRECTOR, is_active=True
        ).order_by("employee_id")
        self.fields["ceo_user"].queryset = User.objects.filter(role=UserRole.CEO, is_active=True).order_by(
            "employee_id"
        )
        self.fields["primary_hr_user"].queryset = User.objects.filter(
            role=UserRole.ADMIN, is_active=True
        ).order_by("employee_id")
        self.fields["director_user"].label = "Director"
        self.fields["ceo_user"].label = "CEO"
        self.fields["primary_hr_user"].label = "Primary HR"


class PraiseLetterForm(forms.ModelForm):
    class Meta:
        model = PraiseLetter
        fields = ["employee", "title", "message", "document"]
        widgets = {
            "employee": forms.Select(attrs={"class": "form-select"}),
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "Letter of Praise"}),
            "message": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 6,
                    "placeholder": "Optional message (or upload a document below)...",
                }
            ),
            "document": forms.FileInput(
                attrs={"class": "form-control", "accept": ".pdf,.doc,.docx,.jpg,.jpeg,.png"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employee"].queryset = User.objects.filter(role=UserRole.EMPLOYEE).order_by("employee_id")
        self.fields["message"].required = False
        self.fields["document"].required = False

    def clean(self):
        cleaned = super().clean()
        message = (cleaned.get("message") or "").strip()
        document = cleaned.get("document")
        if not message and not document and not (self.instance and self.instance.document):
            raise forms.ValidationError("Provide a message or upload a praise letter file from your computer.")
        if document:
            validate_upload_file(document, allowed_extensions=PRAISE_EXTENSIONS, label="Praise letter file")
        return cleaned


class LeaveRequestForm(forms.ModelForm):
    class Meta:
        from attendance.models import LeaveRequest

        model = LeaveRequest
        fields = ["leave_type", "start_date", "end_date", "reason"]
        widgets = {
            "leave_type": forms.Select(attrs={"class": "form-select"}),
            "start_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}, format="%Y-%m-%d"),
            "end_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}, format="%Y-%m-%d"),
            "reason": forms.Textarea(attrs={"class": "form-control", "rows": 4, "placeholder": "Reason for leave..."}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["start_date"].input_formats = ["%Y-%m-%d"]
        self.fields["end_date"].input_formats = ["%Y-%m-%d"]

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_date")
        end = cleaned.get("end_date")
        if start and end and end < start:
            raise forms.ValidationError("End date cannot be before start date.")
        return cleaned


class HrLeaveReviewForm(forms.Form):
    hr_note = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Note to employee (optional)"}),
    )


class PaySlipUploadForm(forms.ModelForm):
    class Meta:
        from attendance.models import PaySlip

        model = PaySlip
        fields = ["employee", "year", "month", "title", "document"]
        widgets = {
            "employee": forms.Select(attrs={"class": "form-select"}),
            "year": forms.NumberInput(attrs={"class": "form-control", "min": 2020, "max": 2100}),
            "month": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 12}),
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. July 2026 Salary Slip"}),
            "document": forms.FileInput(attrs={"class": "form-control", "accept": ".pdf,.jpg,.jpeg,.png"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employee"].queryset = User.objects.filter(role=UserRole.EMPLOYEE).order_by("employee_id")

    def clean_document(self):
        document = self.cleaned_data.get("document")
        validate_upload_file(document, allowed_extensions=DOCUMENT_EXTENSIONS, label="Pay slip")
        return document


class CeoRegularizationOverrideForm(forms.Form):
    check_in = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
    )
    ceo_note = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "CEO note (reason for override)"}),
    )


class AttendanceRegularizeForm(forms.Form):
    employee = forms.ModelChoiceField(
        queryset=User.objects.filter(role=UserRole.EMPLOYEE).order_by("employee_id"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    date = forms.DateField(widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}))
    check_in = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
    )

    def save(self) -> Attendance:
        from attendance.services import regularize_attendance

        employee: User = self.cleaned_data["employee"]
        att_date = self.cleaned_data["date"]
        check_in = self.cleaned_data["check_in"]

        return regularize_attendance(
            employee=employee,
            att_date=att_date,
            check_in=check_in,
            check_out=None,
        )


class EmployeeRegularizationRequestForm(forms.ModelForm):
    class Meta:
        model = AttendanceRegularizationRequest
        fields = ["date", "description"]
        widgets = {
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}, format="%Y-%m-%d"),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Explain why you forgot to mark attendance...",
                }
            ),
        }

    def __init__(self, *args, employee=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.employee = employee
        self.fields["date"].input_formats = ["%Y-%m-%d"]

    def clean_date(self):
        att_date = self.cleaned_data["date"]
        if att_date > timezone.localdate():
            raise forms.ValidationError("Cannot request regularization for a future date.")
        return att_date

    def clean(self):
        cleaned = super().clean()
        att_date = cleaned.get("date")
        if self.employee and att_date:
            if AttendanceRegularizationRequest.objects.filter(
                employee=self.employee,
                date=att_date,
                status=RegularizationStatus.PENDING,
            ).exists():
                raise forms.ValidationError("A pending request already exists for this date.")
            att = Attendance.objects.filter(employee=self.employee, date=att_date).first()
            if att and att.check_in and att.check_out:
                raise forms.ValidationError("Attendance is already complete for this date.")
        return cleaned


class HrRegularizationApproveForm(forms.Form):
    check_in = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
    )
    hr_note = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "HR note (optional)"}),
    )

