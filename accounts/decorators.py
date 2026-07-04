from __future__ import annotations

from django.contrib.auth.decorators import user_passes_test

from .models import UserRole


def is_admin(user) -> bool:
    return bool(user.is_authenticated and getattr(user, "role", None) == UserRole.ADMIN)


def is_ceo(user) -> bool:
    return bool(user.is_authenticated and getattr(user, "role", None) == UserRole.CEO)


def is_director(user) -> bool:
    return bool(user.is_authenticated and getattr(user, "role", None) == UserRole.DIRECTOR)


def is_employee(user) -> bool:
    return bool(user.is_authenticated and getattr(user, "role", None) == UserRole.EMPLOYEE)


def is_admin_or_ceo(user) -> bool:
    return bool(
        user.is_authenticated and getattr(user, "role", None) in (UserRole.ADMIN, UserRole.CEO)
    )


def is_leadership(user) -> bool:
    return bool(
        user.is_authenticated
        and getattr(user, "role", None) in (UserRole.DIRECTOR, UserRole.CEO, UserRole.ADMIN)
    )


def can_mark_own_attendance(user) -> bool:
    return bool(
        user.is_authenticated
        and getattr(user, "role", None) in (UserRole.EMPLOYEE, UserRole.ADMIN, UserRole.CEO)
    )


admin_required = user_passes_test(is_admin)
ceo_required = user_passes_test(is_ceo)
director_required = user_passes_test(is_director)
employee_required = user_passes_test(is_employee)
admin_or_ceo_required = user_passes_test(is_admin_or_ceo)
leadership_required = user_passes_test(is_leadership)
self_attendance_required = user_passes_test(can_mark_own_attendance)
