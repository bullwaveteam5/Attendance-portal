from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create the MySQL database configured in settings (uses DB_* environment variables)."

    def handle(self, *args, **options):
        db = settings.DATABASES["default"]
        engine = db.get("ENGINE", "")

        if "mysql" not in engine:
            raise CommandError(f"DB_ENGINE is not MySQL ({engine}). Nothing to create.")

        try:
            import MySQLdb
        except ImportError as exc:
            raise CommandError("Install mysqlclient: pip install mysqlclient") from exc

        db_name = db["NAME"]
        try:
            conn = MySQLdb.connect(
                host=db.get("HOST") or "127.0.0.1",
                user=db.get("USER") or "root",
                passwd=db.get("PASSWORD") or "",
                port=int(db.get("PORT") or 3306),
            )
            cursor = conn.cursor()
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            conn.commit()
            conn.close()
        except MySQLdb.Error as exc:
            raise CommandError(
                f"Could not create database '{db_name}'. "
                f"Ensure MySQL is running and DB_USER/DB_PASSWORD are correct. ({exc})"
            ) from exc

        self.stdout.write(self.style.SUCCESS(f"MySQL database '{db_name}' is ready."))
        self.stdout.write("Run: python manage.py migrate")
