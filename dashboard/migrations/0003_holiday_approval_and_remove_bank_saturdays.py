from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def forwards(apps, schema_editor):
    Holiday = apps.get_model("dashboard", "Holiday")
    # Remove incorrectly seeded bank-style 2nd/4th Saturday holidays
    Holiday.objects.filter(name__icontains="Saturday (Bank Holiday)").delete()
    # Existing remaining holidays are treated as already approved for employees
    Holiday.objects.all().update(approval_status="approved")


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("dashboard", "0002_holidayannouncementread_holiday_announced_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="holiday",
            name="approval_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending Approval"),
                    ("approved", "Approved"),
                    ("rejected", "Rejected"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="holiday",
            name="approval_note",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="holiday",
            name="hr_approved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="holiday",
            name="ceo_approved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="holiday",
            name="hr_approved_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="holidays_hr_approved",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="holiday",
            name="ceo_approved_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="holidays_ceo_approved",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddIndex(
            model_name="holiday",
            index=models.Index(fields=["approval_status"], name="dashboard_h_approva_6f2a1c_idx"),
        ),
        migrations.RunPython(forwards, backwards),
    ]
