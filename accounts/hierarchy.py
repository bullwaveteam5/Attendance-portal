from __future__ import annotations

from dataclasses import dataclass

from django.db.models import QuerySet

from .models import CompanyHierarchy, User, UserRole


@dataclass
class OrgNode:
    key: str
    title: str
    user: User | None
    employee_count: int = 0
    children_keys: list[str] | None = None


def _pick_user(role: str, preferred: User | None, queryset: QuerySet[User]) -> User | None:
    if preferred and preferred.role == role and preferred.is_active:
        return preferred
    return queryset.filter(role=role, is_active=True).order_by("employee_id").first()


def get_company_hierarchy() -> CompanyHierarchy:
    obj, _ = CompanyHierarchy.objects.get_or_create(pk=1)
    return obj


def build_org_hierarchy(*, viewer: User | None = None) -> dict:
    config = get_company_hierarchy()
    employee_count = User.objects.filter(role=UserRole.EMPLOYEE, is_active=True).count()
    hr_team = list(User.objects.filter(role=UserRole.ADMIN, is_active=True).order_by("employee_id"))

    director = _pick_user(UserRole.DIRECTOR, config.director_user, User.objects.all())
    ceo = _pick_user(UserRole.CEO, config.ceo_user, User.objects.all())
    primary_hr = _pick_user(UserRole.ADMIN, config.primary_hr_user, User.objects.all())

    nodes = {
        "director": OrgNode(
            key="director",
            title="Director",
            user=director,
            children_keys=["ceo"],
        ),
        "ceo": OrgNode(
            key="ceo",
            title="CEO",
            user=ceo,
            children_keys=["hr"],
        ),
        "hr": OrgNode(
            key="hr",
            title="HR",
            user=primary_hr,
            children_keys=["employees"],
        ),
        "employees": OrgNode(
            key="employees",
            title="Employees",
            user=None,
            employee_count=employee_count,
            children_keys=[],
        ),
    }

    chain = ["director", "ceo", "hr", "employees"]
    levels = [nodes[k] for k in chain]

    viewer_key = None
    if viewer and viewer.is_authenticated:
        role = getattr(viewer, "role", None)
        if role == UserRole.DIRECTOR:
            viewer_key = "director"
        elif role == UserRole.CEO:
            viewer_key = "ceo"
        elif role == UserRole.ADMIN:
            viewer_key = "hr"
        elif role == UserRole.EMPLOYEE:
            viewer_key = "employees"

    return {
        "levels": levels,
        "chain": chain,
        "viewer_key": viewer_key,
        "hr_team": hr_team,
        "employee_count": employee_count,
        "config": config,
    }
