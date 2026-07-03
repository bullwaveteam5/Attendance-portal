from __future__ import annotations

from attendance.models import OfficeSettings


def office_verification(request):
    settings = OfficeSettings.get_solo()
    requires = settings.requires_verification()
    return {
        "office_settings": settings,
        "office_gps_required": settings.gps_verification_enabled,
        "office_ip_required": settings.ip_verification_enabled,
        "office_verification_required": requires,
    }
