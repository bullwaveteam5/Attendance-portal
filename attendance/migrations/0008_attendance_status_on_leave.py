from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0007_officesettings_attendance_check_in_distance_m_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="attendance",
            name="status",
            field=models.CharField(
                choices=[
                    ("Present", "Present"),
                    ("Half Day", "Half Day"),
                    ("Absent", "Absent"),
                    ("Full Day", "Full Day"),
                    ("On Leave", "On Leave"),
                ],
                default="Absent",
                max_length=20,
            ),
        ),
    ]
