from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand

from dashboard.models import Holiday, HolidayApprovalStatus, HolidayEventType


class Command(BaseCommand):
    help = "Seed Indian national / festival holidays (no bank Saturdays). Entries are pre-approved."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, required=True)

    def handle(self, *args, **options):
        year: int = options["year"]

        national = [
            (date(year, 1, 26), "Republic Day"),
            (date(year, 8, 15), "Independence Day"),
            (date(year, 10, 2), "Gandhi Jayanti"),
        ]

        public_days = [
            (date(year, 1, 1), "New Year's Day"),
            (date(year, 5, 1), "Labour Day"),
            (date(year, 4, 14), "Dr. Ambedkar Jayanti"),
            (date(year, 12, 25), "Christmas"),
        ]

        # Approximate lunar dates — edit in HR/CEO calendar after review.
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

        # Do NOT seed 2nd/4th Saturdays — company holidays must be approved by HR + CEO.
        presets = [*national, *public_days, *hindu_festivals]

        # Clean any leftover bank-Saturday rows for this year
        removed, _ = Holiday.objects.filter(
            date__year=year, name__icontains="Saturday (Bank Holiday)"
        ).delete()

        created = 0
        updated = 0
        for d, name in presets:
            obj, was_created = Holiday.objects.update_or_create(
                date=d,
                defaults={
                    "name": name,
                    "is_optional": False,
                    "event_type": HolidayEventType.HOLIDAY,
                    "approval_status": HolidayApprovalStatus.APPROVED,
                },
            )
            created += 1 if was_created else 0
            updated += 0 if was_created else 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded holidays for {year}. created={created}, updated={updated}, removed_bank_saturdays={removed}"
            )
        )
