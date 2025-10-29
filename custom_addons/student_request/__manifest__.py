{
    'name': 'Student Service Management',
    'version': '1.0',
    'summary': 'Quản lý dịch vụ cho sinh viên',
    'author': 'Your Name',
    'category': 'Student',
    'license': 'LGPL-3',
    'depends': ['base', 'mail'],
    'data': [
        # Security files (groups must be loaded before access rules)
        'security/extension_security.xml',
        'security/ir.model.access.csv',
        
        # Data files (nên load trước views)
        # 'data/model_data.xml',  # Temporarily commented out
        'data/service_step_data.xml',
        'data/cron_data.xml',
        'data/stats_cron.xml',
        'data/email_templates.xml',
        'data/automated_actions.xml',  # Fixed XML validation error
        # 'data/permission_rules_data.xml',  # Commented out to remove permission restrictions
        
        # View files
        'views/service_group_views.xml',
        'views/service_views.xml',
        'views/service_step_views.xml',
        'views/service_file_views.xml',
        'views/service_request_views.xml',
        'views/request_extension_views.xml',
        'views/request_stats_views.xml',
        'views/bulk_assign_wizard_views.xml',
        'views/admin_profile_views.xml',
        'views/notification_views.xml',
        'views/dormitory_views.xml',
        'views/request_review_views.xml',
        'views/roles_views.xml',
        'views/department_views.xml',
        'views/service_report_views.xml',
        'views/request_stats_wizard_views.xml',
        'views/email_template.xml',
        # Đảm bảo các server actions được định nghĩa trước khi view đơn giản tham chiếu
        'views/maintenance_user_friendly_views.xml',
        'views/maintenance_simple_views.xml',
        'views/student_manage_views.xml',
        'views/user_permission_views.xml',
        'views/permission_manager_views.xml',
        'views/ir_attachment_views.xml',
        'views/menu_permission_views.xml',
        
        # Menu (phải để cuối)
        'views/menus.xml',
    ],
    'installable': True,
    'application': True,
    # 'post_init_hook': 'post_init_hook',  # Commented out to remove permission setup
    'assets': {
        'web.assets_backend': [
            'student_request/static/src/css/hide_checkbox.css',
            'student_request/static/src/css/kanban.css',
            'student_request/static/src/css/no_download.css',
            'student_request/static/src/css/image_gallery.css',
            'student_request/static/src/js/image_viewer.js',
            'student_request/static/src/js/image_gallery.js',
        ],
    },
}

# Các loại view phổ biến trong Odoo:
# - form: Giao diện nhập/sửa/xem chi tiết bản ghi.
# - tree (Odoo < 17) / list (Odoo 17+): Giao diện danh sách bản ghi.
# - kanban: Giao diện dạng thẻ (card), thường dùng cho quy trình.
# - calendar: Lịch (dạng ngày/tuần/tháng).
# - graph: Biểu đồ (bar, line, pie...).
# - pivot: Bảng tổng hợp động.
# - search: Giao diện tìm kiếm nâng cao.
# - activity: Quản lý hoạt động (chấm công việc).
# - map: Bản đồ (Odoo Enterprise).
# - cohort, gantt, dashboard, timeline, grid, diagram, etc. (tùy phiên bản Odoo)

# Không cần sửa nếu đã có views/service_views.xml và views/menus.xml
