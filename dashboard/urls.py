from django.urls import path



from . import views



urlpatterns = [

    path("setup/", views.initial_setup, name="initial_setup"),

    path("employee/login/", views.EmployeeLoginView.as_view(), name="employee_login"),

    path("hr/login/", views.HrLoginView.as_view(), name="hr_login"),

    path("ceo/login/", views.CeoLoginView.as_view(), name="ceo_login"),

    path("director/login/", views.DirectorLoginView.as_view(), name="director_login"),

    path("logout/", views.logout_view, name="logout"),

    path("account/password/", views.password_change, name="password_change"),

    path("account/personal/", views.personal_info, name="personal_info"),

    path("", views.landing_page, name="home"),



    # Employee

    path("employee/dashboard/", views.employee_dashboard, name="employee_dashboard"),

    path("employee/check-in/", views.employee_check_in, name="employee_check_in"),

    path("employee/check-out/", views.employee_check_out, name="employee_check_out"),

    path("employee/praise-letters/", views.employee_praise_letters, name="employee_praise_letters"),

    path("employee/praise-letters/<int:pk>/download/", views.praise_letter_download, name="praise_letter_download"),

    path("employee/attendance/", views.employee_attendance_records, name="employee_attendance_records"),

    path("employee/leave/", views.employee_leave_requests, name="employee_leave_requests"),

    path("employee/leave/request/", views.leave_request_create, name="leave_request_create"),

    path("employee/payslips/", views.employee_payslips, name="employee_payslips"),

    path("employee/payslips/<int:pk>/download/", views.employee_payslip_download, name="employee_payslip_download"),

    path("employee/regularization/request/", views.request_regularization, name="request_regularization"),

    path("org/hierarchy/", views.org_hierarchy_view, name="org_hierarchy"),



    # Admin (HR) — CEO has full access via admin_or_ceo_required

    path("hr/dashboard/", views.admin_dashboard, name="admin_dashboard"),

    path("hr/employees/", views.employee_list, name="employee_list"),

    path("hr/employees/add/", views.employee_create, name="employee_create"),

    path("hr/employees/<int:pk>/edit/", views.employee_update, name="employee_update"),

    path("hr/employees/<int:pk>/record/", views.hr_employee_record, name="hr_employee_record"),

    path("hr/employees/<int:pk>/delete/", views.employee_delete, name="employee_delete"),

    path("hr/employees/<int:pk>/portal/", views.hr_employee_portal, name="hr_employee_portal"),

    path("hr/employees/<int:pk>/personal/", views.hr_employee_personal_info, name="hr_employee_personal_info"),

    path("hr/holidays/", views.holiday_list, name="holiday_list"),

    path("hr/holidays/add/", views.holiday_create, name="holiday_create"),

    path("hr/holidays/<int:pk>/edit/", views.holiday_update, name="holiday_update"),

    path("hr/holidays/<int:pk>/approve/", views.holiday_approve, name="holiday_approve"),

    path("hr/holidays/<int:pk>/delete/", views.holiday_delete, name="holiday_delete"),

    path("hr/attendance/", views.admin_attendance_list, name="admin_attendance_list"),

    path("hr/attendance/regularize/", views.attendance_regularize, name="attendance_regularize"),

    path("hr/regularization/", views.regularization_request_list, name="regularization_request_list"),

    path("hr/regularization/<int:pk>/review/", views.regularization_review, name="regularization_review"),

    path("hr/leave/", views.hr_leave_request_list, name="hr_leave_request_list"),

    path("hr/leave/export/csv/", views.hr_leave_export_csv, name="hr_leave_export_csv"),

    path("hr/leave/balances/", views.hr_leave_balances, name="hr_leave_balances"),

    path("hr/leave/employee/<int:pk>/", views.hr_employee_leave_history, name="hr_employee_leave_history"),

    path("hr/leave/<int:pk>/review/", views.hr_leave_request_review, name="hr_leave_request_review"),

    path("hr/payslips/", views.hr_payslip_list, name="hr_payslip_list"),

    path("hr/payslips/<int:pk>/download/", views.hr_payslip_download, name="hr_payslip_download"),

    path("hr/payslips/upload/", views.hr_payslip_upload, name="hr_payslip_upload"),

    path("hr/attendance/export/csv/", views.export_attendance_csv, name="export_attendance_csv"),

    path("hr/attendance/export/pdf/", views.export_attendance_pdf, name="export_attendance_pdf"),



    # CEO command center

    path("ceo/dashboard/", views.ceo_dashboard, name="ceo_dashboard"),

    path("ceo/hr/", views.ceo_hr_overview, name="ceo_hr_overview"),

    path("ceo/praise/", views.praise_letter_list, name="praise_letter_list"),

    path("ceo/praise/new/", views.praise_letter_create, name="praise_letter_create"),

    path("ceo/praise/<int:pk>/", views.praise_letter_detail, name="praise_letter_detail"),

    path("ceo/holidays/announce/", views.ceo_holiday_announce, name="ceo_holiday_announce"),

    path("ceo/regularization/<int:pk>/override/", views.ceo_regularization_override, name="ceo_regularization_override"),

    path("ceo/attendance/export/csv/", views.export_attendance_csv, name="ceo_export_attendance_csv"),

    path("ceo/attendance/export/pdf/", views.export_attendance_pdf, name="ceo_export_attendance_pdf"),



    # Director oversight

    path("director/dashboard/", views.director_dashboard, name="director_dashboard"),

    path("director/hierarchy/edit/", views.director_hierarchy_manage, name="director_hierarchy_manage"),

]


