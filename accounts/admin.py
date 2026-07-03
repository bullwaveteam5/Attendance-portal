from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.forms import ModelForm

from .models import CompanyHierarchy, EmployeePersonalProfile, PraiseLetter, User


class UserChangeForm(ModelForm):
    class Meta:
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    form = UserChangeForm
    model = User

    ordering = ("employee_id",)
    list_display = ("employee_id", "username", "role", "department", "is_active", "is_staff")
    list_filter = ("role", "department", "is_active", "is_staff")
    search_fields = ("employee_id", "username", "email", "department")

    fieldsets = (
        (None, {"fields": ("employee_id", "password")}),
        ("Profile", {"fields": ("username", "email", "department", "role")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("employee_id", "username", "password1", "password2", "role", "department", "email"),
            },
        ),
    )


@admin.register(EmployeePersonalProfile)
class EmployeePersonalProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "full_name", "phone_number", "updated_at")
    search_fields = ("user__employee_id", "user__username", "full_name", "pan_number")
    raw_id_fields = ("user",)


@admin.register(PraiseLetter)
class PraiseLetterAdmin(admin.ModelAdmin):
    list_display = ("employee", "title", "issued_by", "issued_at", "is_read")
    list_filter = ("is_read",)
    search_fields = ("employee__employee_id", "employee__username", "title", "message")


@admin.register(CompanyHierarchy)
class CompanyHierarchyAdmin(admin.ModelAdmin):
    list_display = ("director_user", "ceo_user", "primary_hr_user", "updated_at")

    def has_add_permission(self, request):
        return not CompanyHierarchy.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

