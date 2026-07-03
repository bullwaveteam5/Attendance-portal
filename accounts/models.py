from __future__ import annotations

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone


class UserRole(models.TextChoices):
    DIRECTOR = "director", "Director"
    ADMIN = "admin", "Admin (HR)"
    CEO = "ceo", "CEO"
    EMPLOYEE = "employee", "Employee"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, employee_id: str, password: str | None, **extra_fields):
        if not employee_id:
            raise ValueError("The employee_id must be set")

        employee_id = str(employee_id).strip()
        user = self.model(employee_id=employee_id, **extra_fields)
        user.set_password(password)
        user.full_clean()
        user.save(using=self._db)
        return user

    def create_user(self, employee_id: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("role", UserRole.EMPLOYEE)
        return self._create_user(employee_id, password, **extra_fields)

    def create_superuser(self, employee_id: str, password: str, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("role", UserRole.ADMIN)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        if extra_fields.get("role") != UserRole.ADMIN:
            raise ValueError("Superuser must have role=admin.")

        return self._create_user(employee_id, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    employee_id = models.CharField(max_length=32, unique=True)
    username = models.CharField(max_length=150)
    email = models.EmailField(blank=True)
    department = models.CharField(max_length=100, blank=True)
    role = models.CharField(max_length=20, choices=UserRole.choices, default=UserRole.EMPLOYEE)

    date_of_birth = models.DateField(null=True, blank=True)
    anniversary_date = models.DateField(null=True, blank=True)
    salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "employee_id"
    REQUIRED_FIELDS: list[str] = ["username"]

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        indexes = [
            models.Index(fields=["employee_id"]),
            models.Index(fields=["department"]),
            models.Index(fields=["role"]),
        ]

    def __str__(self) -> str:
        return f"{self.employee_id} - {self.username}"


def profile_photo_upload_to(instance, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    return f"profiles/{instance.user.employee_id}.{ext}"


class EmployeePersonalProfile(models.Model):
    user = models.OneToOneField("User", on_delete=models.CASCADE, related_name="personal_profile")
    profile_photo = models.ImageField(upload_to=profile_photo_upload_to, blank=True, null=True)
    full_name = models.CharField(max_length=150, blank=True)
    father_name = models.CharField(max_length=150, blank=True)
    mother_name = models.CharField(max_length=150, blank=True)
    phone_number = models.CharField(max_length=15, blank=True)
    emergency_contact_name = models.CharField(max_length=150, blank=True)
    emergency_phone_number = models.CharField(max_length=15, blank=True)
    current_address = models.TextField(blank=True)
    pan_number = models.CharField(max_length=10, blank=True)
    aadhaar_number = models.CharField(max_length=12, blank=True)
    bank_account_holder = models.CharField(max_length=150, blank=True)
    bank_name = models.CharField(max_length=120, blank=True)
    bank_account_number = models.CharField(max_length=30, blank=True)
    bank_ifsc = models.CharField(max_length=11, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Employee personal profile"
        verbose_name_plural = "Employee personal profiles"

    def __str__(self) -> str:
        return f"Profile — {self.user.employee_id}"

    @property
    def display_name(self) -> str:
        return self.full_name or self.user.username


class CompanyHierarchy(models.Model):
    """Singleton: assign named leaders for the org chart (editable by Director)."""

    director_user = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hierarchy_as_director",
        limit_choices_to={"role": UserRole.DIRECTOR},
    )
    ceo_user = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hierarchy_as_ceo",
        limit_choices_to={"role": UserRole.CEO},
    )
    primary_hr_user = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hierarchy_as_hr",
        limit_choices_to={"role": UserRole.ADMIN},
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Company hierarchy"
        verbose_name_plural = "Company hierarchy"

    def __str__(self) -> str:
        return "Organization hierarchy"


class PraiseLetter(models.Model):
    employee = models.ForeignKey("User", on_delete=models.CASCADE, related_name="praise_letters")
    title = models.CharField(max_length=200, default="Letter of Praise")
    message = models.TextField(blank=True)
    document = models.FileField(upload_to="praise_letters/%Y/%m/", blank=True, null=True)
    issued_by = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, related_name="praise_letters_issued"
    )
    issued_at = models.DateTimeField(default=timezone.now)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ["-issued_at"]
        indexes = [
            models.Index(fields=["employee", "is_read"]),
            models.Index(fields=["issued_at"]),
        ]

    def __str__(self) -> str:
        return f"Praise for {self.employee.employee_id} — {self.title}"

    @property
    def has_download(self) -> bool:
        return bool(self.document)


class SalaryIncrementStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class SalaryIncrementRequest(models.Model):
    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name="salary_increment_requests")
    percent = models.DecimalField(max_digits=5, decimal_places=2, default=20)
    status = models.CharField(max_length=20, choices=SalaryIncrementStatus.choices, default=SalaryIncrementStatus.PENDING)
    note = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="salary_increment_decisions"
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["employee", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.employee.employee_id} {self.percent}% ({self.status})"
