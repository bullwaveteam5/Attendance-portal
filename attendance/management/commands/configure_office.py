from decimal import Decimal

from django.core.management.base import BaseCommand

from attendance.models import OfficeSettings

# 28°41'36.9"N 77°08'59.0"E
OFFICE_LATITUDE = Decimal("28.693583")
OFFICE_LONGITUDE = Decimal("77.149722")

# Office WiFi LAN — devices on the office router (192.168.1.x).
# Office public IPv6 /64 — Airtel office WiFi prefix only (not the wider /48 ISP block).
OFFICE_ALLOWED_IPS = """192.168.1.0/24
2401:4900:1cd7:88b1::/64"""


class Command(BaseCommand):
    help = "Configure office GPS geofence for portal login and attendance."

    def handle(self, *args, **options):
        office = OfficeSettings.get_solo()
        office.name = "Capital Bull Wave Office"
        office.latitude = OFFICE_LATITUDE
        office.longitude = OFFICE_LONGITUDE
        office.allowed_radius_meters = 150
        office.allowed_public_ips = OFFICE_ALLOWED_IPS.strip()
        office.gps_verification_enabled = True
        office.ip_verification_enabled = False
        office.save()

        self.stdout.write(self.style.SUCCESS("Office settings configured:"))
        self.stdout.write(f"  Location: {office.latitude}, {office.longitude}")
        self.stdout.write(f"  Radius: {office.allowed_radius_meters} m")
        self.stdout.write("  GPS verification: ON")
        self.stdout.write("  IP verification: OFF (employees may use mobile data)")
