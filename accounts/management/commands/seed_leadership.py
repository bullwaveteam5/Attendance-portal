from __future__ import annotations

from django.core.management.base import BaseCommand

from accounts.hierarchy import get_company_hierarchy
from accounts.models import User, UserRole


LEADERS = (
    {
        "employee_id": "DIR001",
        "username": "Rohit",
        "role": UserRole.DIRECTOR,
        "department": "Board",
        "email": "rohit@capitalbullwave.com",
    },
    {
        "employee_id": "CEO001",
        "username": "Kanika",
        "role": UserRole.CEO,
        "department": "Executive",
        "email": "kanika@capitalbullwave.com",
    },
    {
        "employee_id": "HR001",
        "username": "Vandana",
        "role": UserRole.ADMIN,
        "department": "Human Resources",
        "email": "vandana@capitalbullwave.com",
        "is_staff": True,
    },
)


class Command(BaseCommand):
    help = "Create or update Director (Rohit), CEO (Kanika), and HR (Vandana) and link the org hierarchy."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            default="ChangeMe123!",
            help="Default password for newly created leadership accounts.",
        )
        parser.add_argument(
            "--update-existing",
            action="store_true",
            help="Update username/department/email on existing leadership accounts.",
        )

    def handle(self, *args, **options):
        password = options["password"]
        update_existing = options["update_existing"]
        created_users: dict[str, User] = {}
        any_created = False

        for spec in LEADERS:
            employee_id = spec["employee_id"]
            defaults = {
                "username": spec["username"],
                "role": spec["role"],
                "department": spec["department"],
                "email": spec["email"],
                "is_active": True,
            }
            if spec.get("is_staff"):
                defaults["is_staff"] = True

            user, created = User.objects.get_or_create(employee_id=employee_id, defaults=defaults)
            if created:
                user.set_password(password)
                user.save()
                any_created = True
                self.stdout.write(self.style.SUCCESS(f"Created {spec['role']}: {spec['username']} ({employee_id})"))
            else:
                if update_existing:
                    for key, value in defaults.items():
                        setattr(user, key, value)
                    user.save()
                    self.stdout.write(f"Updated {spec['username']} ({employee_id})")
                else:
                    self.stdout.write(f"Exists: {spec['username']} ({employee_id})")

            created_users[spec["role"]] = user

        config = get_company_hierarchy()
        config.director_user = created_users[UserRole.DIRECTOR]
        config.ceo_user = created_users[UserRole.CEO]
        config.primary_hr_user = created_users[UserRole.ADMIN]
        config.save()

        self.stdout.write(self.style.SUCCESS("Organization hierarchy linked: Rohit -> Kanika -> Vandana -> Employees"))
        if any_created:
            self.stdout.write(
                self.style.WARNING(f"New accounts use password: {password} — change after first login.")
            )
