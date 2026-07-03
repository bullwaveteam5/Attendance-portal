from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist


def user_personal_profile(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {"user_personal_profile": None}
    try:
        return {"user_personal_profile": request.user.personal_profile}
    except ObjectDoesNotExist:
        return {"user_personal_profile": None}
