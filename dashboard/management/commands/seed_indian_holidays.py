from __future__ import annotations

from datetime import date, timedelta

from django.core.management.base import BaseCommand

from dashboard.models import Holiday


class Command(BaseCommand):
    help = "Seed Indian national holidays + bank Saturdays + Hindu festivals (starter set)."

    @staticmethod
    def _nth_weekday_of_month(*, year: int, month: int, weekday: int, n: int) -> date:
        """
        weekday: Monday=0 .. Sunday=6 (Python date.weekday()).
        n: 1..5
        """
        d = date(year, month, 1)
        while d.weekday() != weekday:
            d += timedelta(days=1)
        return d + timedelta(days=7 * (n - 1))

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, required=True)

    def handle(self, *args, **options):
        year: int = options["year"]

        # Fixed-date national/public holidays (common India-wide list)
        national = [
            (date(year, 1, 26), "Republic Day"),
            (date(year, 8, 15), "Independence Day"),
            (date(year, 10, 2), "Gandhi Jayanti"),
        ]

        # Other widely observed public days (may vary by state/company)
        public_days = [
            (date(year, 1, 1), "New Year's Day"),
            (date(year, 5, 1), "Labour Day"),
            (date(year, 4, 14), "Dr. Ambedkar Jayanti"),
            (date(year, 12, 25), "Christmas"),
        ]

        # Hindu festivals: exact dates vary (lunar calendar); treat as starter defaults you can edit in UI.
        hindu_festivals = [
            (date(year, 1, 14), "Makar Sankranti / Pongal"),
            (date(year, 2, 18), "Maha Shivratri (approx)"),
            (date(year, 3, 25), "Ram Navami (approx)"),
            (date(year, 3, 8), "Holi (approx)"),
            (date(year, 4, 10), "Hanuman Jayanti (approx)"),
            (date(year, 8, 9), "Raksha Bandhan (approx)"),
            (date(year, 8, 19), "Janmashtami (approx)"),
            (date(year, 9, 7), "Ganesh Chaturthi (approx)"),
            (date(year, 9, 22), "Navratri Begins (approx)"),
            (date(year, 10, 2), "Dussehra (approx)"),
            (date(year, 10, 20), "Karwa Chauth (approx)"),
            (date(year, 11, 1), "Diwali (approx)"),
            (date(year, 11, 2), "Govardhan Puja (approx)"),
            (date(year, 11, 3), "Bhai Dooj (approx)"),
            (date(year, 12, 5), "Gita Jayanti (approx)"),
        ]

        # Bank-style holidays: 2nd and 4th Saturday of every month
        bank_saturdays: list[tuple[date, str]] = []
        for month in range(1, 13):
            second_sat = self._nth_weekday_of_month(year=year, month=month, weekday=5, n=2)  # Saturday=5
            fourth_sat = self._nth_weekday_of_month(year=year, month=month, weekday=5, n=4)
            bank_saturdays.append((second_sat, "Second Saturday (Bank Holiday)"))
            bank_saturdays.append((fourth_sat, "Fourth Saturday (Bank Holiday)"))

        presets = [*national, *public_days, *hindu_festivals, *bank_saturdays]

        created = 0
        updated = 0
        for d, name in presets:
            obj, was_created = Holiday.objects.update_or_create(date=d, defaults={"name": name, "is_optional": False})
            created += 1 if was_created else 0
            updated += 0 if was_created else 1

        self.stdout.write(self.style.SUCCESS(f"Seeded holidays for {year}. created={created}, updated={updated}"))

