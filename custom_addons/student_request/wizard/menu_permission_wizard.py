# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError

class MenuPermissionWizard(models.TransientModel):
    _name = 'menu.permission.wizard'
    _description = 'Menu Permission Wizard'

    user_ids = fields.Many2many('res.users', string='Người dùng', required=True)
    menu_group = fields.Selection([
        ('group_menu_create_request', 'Tạo yêu cầu'),
        ('group_menu_view_requests', 'Xem yêu cầu'),
        ('group_menu_notifications', 'Gửi thông báo'),
        ('group_menu_configuration', 'Cấu hình'),
        ('group_menu_reports', 'Báo cáo'),
        ('group_menu_statistics', 'Bảng thống kê'),
        ('group_menu_bulk_assign', 'Phân công hàng loạt'),
        ('group_menu_extension_management', 'Quản lý gia hạn'),
        ('group_menu_service_groups', 'Nhóm dịch vụ'),
        ('group_menu_services', 'Cài dịch vụ'),
        ('group_menu_service_steps', 'Cài bước duyệt'),
        ('group_menu_user_management', 'Tài khoản quản lý'),
        ('group_menu_maintenance', 'Bảo trì hệ thống'),
    ], string='Menu Group', required=True)
    grant_access = fields.Boolean(string='Cấp quyền truy cập', default=True, 
                                  help="Bỏ chọn để thu hồi quyền truy cập")

    def apply_permissions(self):
        """Áp dụng phân quyền cho các user được chọn"""
        if not self.user_ids:
            raise UserError("Vui lòng chọn ít nhất một người dùng")
        
        try:
            group = self.env.ref(f'student_request.{self.menu_group}')
        except ValueError:
            raise UserError(f"Không tìm thấy group: {self.menu_group}")
        
        for user in self.user_ids:
            if self.grant_access:
                if user not in group.users:
                    group.users = [(4, user.id)]
            else:
                if user in group.users:
                    group.users = [(3, user.id)]
        
        action_text = "cấp" if self.grant_access else "thu hồi"
        menu_name = dict(self._fields['menu_group'].selection)[self.menu_group]
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Thành công!',
                'message': f'Đã {action_text} quyền truy cập menu "{menu_name}" cho {len(self.user_ids)} người dùng.',
                'type': 'success',
                'sticky': False,
            }
        }