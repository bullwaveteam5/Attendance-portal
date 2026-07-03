from django.contrib import admin

from .models import (
    Attendance,
    AttendanceRegularizationRequest,
    LeaveDeduction,
    LeaveRequest,
    MonthlyLeaveBalance,
    OfficeSettings,
    PaySlip,
    PortalAccessLog,
)


@admin.register(OfficeSettings)
class OfficeSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "latitude",
        "longitude",
        "allowed_radius_meters",
        "gps_verification_enabled",
        "ip_verification_enabled",
        "updated_at",
    )
    fieldsets = (
        ("Office location", {"fields": ("name", "latitude", "longitude", "allowed_radius_meters")}),
        (
            "Verification",
            {
                "fields": ("gps_verification_enabled", "ip_verification_enabled", "allowed_public_ips"),
                "description": "Enable GPS geofence and/or office public IP checks for portal login and attendance.",
            },
        ),
    )

    def has_add_permission(self, request):
        return not OfficeSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PortalAccessLog)
class PortalAccessLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "event_type", "user", "username_attempt", "success", "client_ip", "distance_m")
    list_filter = ("event_type", "success", "created_at")
    search_fields = ("user__employee_id", "user__username", "username_attempt", "client_ip")
    readonly_fields = (
        "user",
        "username_attempt",
        "event_type",
        "success",
        "latitude",
        "longitude",
        "distance_m",
        "client_ip",
        "user_agent",
        "failure_reason",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "date",
        "check_in",
        "check_out",
        "status",
        "check_in_distance_m",
        "check_in_ip",
        "is_late",
    )
    list_filter = ("date", "status", "is_late", "employee__department")
    search_fields = ("employee__employee_id", "employee__username", "employee__department", "check_in_ip")
    autocomplete_fields = ("employee",)
    readonly_fields = (
        "check_in_latitude",
        "check_in_longitude",
        "check_in_distance_m",
        "check_in_ip",
        "check_in_user_agent",
        "check_out_latitude",
        "check_out_longitude",
        "check_out_distance_m",
        "check_out_ip",
        "check_out_user_agent",
    )
    fieldsets = (
        (None, {"fields": ("employee", "date", "check_in", "check_out", "status", "working_hours", "overtime_hours", "is_late")}),
        (
            "Check-in log",
            {
                "fields": (
                    "check_in_latitude",
                    "check_in_longitude",
                    "check_in_distance_m",
                    "check_in_ip",
                    "check_in_user_agent",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Check-out log",
            {
                "fields": (
                    "check_out_latitude",
                    "check_out_longitude",
                    "check_out_distance_m",
                    "check_out_ip",
                    "check_out_user_agent",
                ),
                "classes": ("collapse",),
            },
        ),
    )


@admin.register(MonthlyLeaveBalance)
class MonthlyLeaveBalanceAdmin(admin.ModelAdmin):
    list_display = ("employee", "year", "month", "monthly_allocation", "carried_forward", "used_leaves", "remaining")
    list_filter = ("year", "month")
    search_fields = ("employee__employee_id", "employee__username")


@admin.register(LeaveDeduction)
class LeaveDeductionAdmin(admin.ModelAdmin):
    list_display = ("employee", "date", "balance", "created_at")
    list_filter = ("date",)
    search_fields = ("employee__employee_id", "employee__username")


@admin.register(AttendanceRegularizationRequest)
class AttendanceRegularizationRequestAdmin(admin.ModelAdmin):
    list_display = ("employee", "date", "status", "created_at", "reviewed_at")
    list_filter = ("status", "date")
    search_fields = ("employee__employee_id", "employee__username", "description")


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ("employee", "leave_type", "start_date", "end_date", "status", "created_at")
    list_filter = ("status", "leave_type")
    search_fields = ("employee__employee_id", "employee__username")


@admin.register(PaySlip)
class PaySlipAdmin(admin.ModelAdmin):
    list_display = ("employee", "year", "month", "title", "uploaded_by", "uploaded_at")
    list_filter = ("year", "month")
    search_fields = ("employee__employee_id", "employee__username")
