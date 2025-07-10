{
    'name': 'Student Service Management',
    'version': '1.0',
    'summary': 'Quản lý dịch vụ cho sinh viên',
    'author': 'Your Name',
    'category': 'Student',
    'depends': ['base'],
    'data': [
        'views/service_views.xml',
        'views/menus.xml',
        'security/ir.model.access.csv',
        'data/service_step_data.xml',
    ],
    'installable': True,
    'application': True,
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
