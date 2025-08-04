{
    'name': 'Student Service Management',
    'version': '1.0',
    'summary': 'Quản lý dịch vụ cho sinh viên',
    'author': 'Your Name',
    'category': 'Student',
    'license': 'LGPL-3',
    'depends': ['base'],
    'data': [
        # Security files
        'security/ir.model.access.csv',
        
        # Data files (nên load trước views)
        'data/service_step_data.xml',
        
        # View files
        'views/service_group_views.xml',
        'views/service_views.xml',
        'views/service_step_views.xml',
        'views/service_file_views.xml',
        'views/service_request_views.xml',
        'views/admin_profile_views.xml',
        'views/notification_views.xml',
        'views/dormitory_views.xml',
        'views/request_review_views.xml',
        
        # Menu (phải để cuối)
        'views/menus.xml',
    ],
    'installable': True,
    'application': True,
    'assets': {
        'web.assets_backend': [
            'student_request/static/src/css/kanban.css',
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
