from datetime import date

from django.test import TestCase

from accounts.models import User, UserRole
from dashboard.forms import EmployeeUpsertForm


class EmployeeUpsertFormTests(TestCase):
    def test_update_without_password_keeps_existing_password(self):
        user = User.objects.create_user(
            employee_id="E100",
            password="Secret123!",
            username="Test User",
            department="IT",
            role=UserRole.EMPLOYEE,
            date_of_birth=date(1995, 5, 15),
        )
        old_hash = user.password

        form = EmployeeUpsertForm(
            data={
                "employee_id": "E100",
                "username": "Updated Name",
                "email": "updated@example.com",
                "department": "HR",
                "role": UserRole.EMPLOYEE,
                "date_of_birth": "1995-05-15",
                "anniversary_date": "",
                "is_active": "on",
                "password": "",
            },
            instance=user,
        )
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()

        saved.refresh_from_db()
        self.assertEqual(saved.username, "Updated Name")
        self.assertEqual(saved.department, "HR")
        self.assertEqual(saved.password, old_hash)
        self.assertTrue(saved.check_password("Secret123!"))

    def test_create_requires_password(self):
        form = EmployeeUpsertForm(
            data={
                "employee_id": "E200",
                "username": "New User",
                "email": "",
                "department": "IT",
                "role": UserRole.EMPLOYEE,
                "date_of_birth": "",
                "anniversary_date": "",
                "is_active": "on",
                "password": "",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("password", form.errors)

    def test_create_hashes_password(self):
        form = EmployeeUpsertForm(
            data={
                "employee_id": "E201",
                "username": "New User",
                "email": "",
                "department": "IT",
                "role": UserRole.EMPLOYEE,
                "date_of_birth": "",
                "anniversary_date": "",
                "is_active": "on",
                "password": "NewPass123!",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertTrue(user.check_password("NewPass123!"))
        self.assertNotEqual(user.password, "NewPass123!")
