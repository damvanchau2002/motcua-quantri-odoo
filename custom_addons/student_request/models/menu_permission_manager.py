# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError

class MenuPermissionManager(models.Model):
    _name = 'menu.permission.manager'
    _description = 'Menu Permission Manager'
    _rec_name = 'user_id'

    user_id = fields.Many2one('res.users', string='Người dùng', required=True)
    menu_permissions = fields.One2many('menu.permission.line', 'permission_id', string='Quyền truy cập menu')
    
    @api.model
    def get_available_menus(self):
        """Lấy danh sách tất cả menu có thể phân quyền"""
        menus = [
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
        ]
        return menus

    def assign_menu_permissions(self):
        """Gán quyền menu cho user"""
        for permission_line in self.menu_permissions:
            if permission_line.can_access:
                group = self.env.ref(f'student_request.{permission_line.menu_group}')
                if group and self.user_id not in group.users:
                    group.users = [(4, self.user_id.id)]
            else:
                group = self.env.ref(f'student_request.{permission_line.menu_group}')
                if group and self.user_id in group.users:
                    group.users = [(3, self.user_id.id)]

class MenuPermissionLine(models.Model):
    _name = 'menu.permission.line'
    _description = 'Menu Permission Line'

    permission_id = fields.Many2one('menu.permission.manager', string='Permission Manager', required=True, ondelete='cascade')
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
    can_access = fields.Boolean(string='Có quyền truy cập', default=False)
    menu_name = fields.Char(string='Tên menu', compute='_compute_menu_name', store=True)

    @api.depends('menu_group')
    def _compute_menu_name(self):
        for record in self:
            if record.menu_group:
                menu_dict = dict(self._fields['menu_group'].selection)
                record.menu_name = menu_dict.get(record.menu_group, '')
            else:
                record.menu_name = ''