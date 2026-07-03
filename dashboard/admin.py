from django.contrib import admin

from .models import Holiday


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ("date", "name", "event_type", "is_optional", "announcement_active")
    list_filter = ("event_type", "is_optional", "announcement_active")
    search_fields = ("name", "ceo_message")
