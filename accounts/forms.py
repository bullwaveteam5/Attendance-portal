from django import forms
from django.contrib.auth.forms import AuthenticationForm
import re

from .models import EmployeePersonalProfile, User, UserRole
from .upload_validators import IMAGE_EXTENSIONS, validate_upload_file

INPUT = "form-control"
SELECT = "form-select"


class EmployeeIdAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="Employee ID",
        widget=forms.TextInput(attrs={"autofocus": True, "class": "form-control", "placeholder": "Employee ID"}),
    )
    password = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Password"}),
    )


class InitialAdminSetupForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput(attrs={"class": "form-control"}))
    password_confirm = forms.CharField(widget=forms.PasswordInput(attrs={"class": "form-control"}))

    class Meta:
        model = User
        fields = ["employee_id", "username", "email", "department"]
        widgets = {
            "employee_id": forms.TextInput(attrs={"class": "form-control", "placeholder": "HR001"}),
            "username": forms.TextInput(attrs={"class": "form-control", "placeholder": "HR Name"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "hr@company.com"}),
            "department": forms.TextInput(attrs={"class": "form-control", "placeholder": "HR"}),
        }

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password")
        p2 = cleaned.get("password_confirm")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Passwords do not match.")
        return cleaned

    def save(self, commit=True):
        user: User = super().save(commit=False)
        user.role = UserRole.ADMIN
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


class PersonalProfileForm(forms.ModelForm):
    class Meta:
        model = EmployeePersonalProfile
        fields = [
            "profile_photo",
            "full_name",
            "father_name",
            "mother_name",
            "phone_number",
            "emergency_contact_name",
            "emergency_phone_number",
            "current_address",
            "pan_number",
            "aadhaar_number",
            "bank_account_holder",
            "bank_name",
            "bank_account_number",
            "bank_ifsc",
        ]
        widgets = {
            "profile_photo": forms.FileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "full_name": forms.TextInput(attrs={"class": INPUT, "placeholder": "Full legal name"}),
            "father_name": forms.TextInput(attrs={"class": INPUT, "placeholder": "Father's name"}),
            "mother_name": forms.TextInput(attrs={"class": INPUT, "placeholder": "Mother's name"}),
            "phone_number": forms.TextInput(attrs={"class": INPUT, "placeholder": "10-digit mobile"}),
            "emergency_contact_name": forms.TextInput(attrs={"class": INPUT, "placeholder": "Emergency contact person"}),
            "emergency_phone_number": forms.TextInput(attrs={"class": INPUT, "placeholder": "Emergency mobile"}),
            "current_address": forms.Textarea(attrs={"class": INPUT, "rows": 3, "placeholder": "Current residential address"}),
            "pan_number": forms.TextInput(attrs={"class": INPUT, "placeholder": "ABCDE1234F", "style": "text-transform:uppercase"}),
            "aadhaar_number": forms.TextInput(attrs={"class": INPUT, "placeholder": "12-digit Aadhaar"}),
            "bank_account_holder": forms.TextInput(attrs={"class": INPUT, "placeholder": "Name as per bank records"}),
            "bank_name": forms.TextInput(attrs={"class": INPUT, "placeholder": "Bank name & branch"}),
            "bank_account_number": forms.TextInput(attrs={"class": INPUT, "placeholder": "Account number"}),
            "bank_ifsc": forms.TextInput(attrs={"class": INPUT, "placeholder": "IFSC code", "style": "text-transform:uppercase"}),
        }

    def clean_phone_number(self):
        value = re.sub(r"\s+", "", self.cleaned_data.get("phone_number", ""))
        if value and not re.fullmatch(r"\+?\d{10,13}", value):
            raise forms.ValidationError("Enter a valid phone number (10–13 digits).")
        return value

    def clean_emergency_phone_number(self):
        value = re.sub(r"\s+", "", self.cleaned_data.get("emergency_phone_number", ""))
        if value and not re.fullmatch(r"\+?\d{10,13}", value):
            raise forms.ValidationError("Enter a valid emergency phone number.")
        return value

    def clean_pan_number(self):
        value = self.cleaned_data.get("pan_number", "").strip().upper()
        if value and not re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", value):
            raise forms.ValidationError("PAN must be in format ABCDE1234F.")
        return value

    def clean_aadhaar_number(self):
        value = re.sub(r"\s+", "", self.cleaned_data.get("aadhaar_number", ""))
        if value and not re.fullmatch(r"\d{12}", value):
            raise forms.ValidationError("Aadhaar must be exactly 12 digits.")
        return value

    def clean_bank_ifsc(self):
        value = self.cleaned_data.get("bank_ifsc", "").strip().upper()
        if value and not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", value):
            raise forms.ValidationError("Enter a valid IFSC code (e.g. SBIN0001234).")
        return value

    def clean_profile_photo(self):
        photo = self.cleaned_data.get("profile_photo")
        validate_upload_file(photo, allowed_extensions=IMAGE_EXTENSIONS, max_bytes=2 * 1024 * 1024, label="Profile photo")
        return photo

