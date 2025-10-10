from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class PermissionManager(models.Model):
    _name = 'student.permission.manager'
    _description = 'Quản lý quyền tự động'
    _rec_name = 'name'

    name = fields.Char('Tên quy tắc', required=True)
    active = fields.Boolean('Kích hoạt', default=True)
    condition_type = fields.Selection([
        ('login_pattern', 'Theo pattern login'),
        ('email_domain', 'Theo domain email'),
        ('manual', 'Gán thủ công'),
    ], string='Loại điều kiện', required=True, default='email_domain')
    
    condition_value = fields.Char('Giá trị điều kiện', 
                                  help="VD: @ktxhcm.edu.vn cho email domain, admin* cho login pattern")
    
    target_group = fields.Selection([
        ('user', 'Student Request User'),
        ('manager', 'Student Request Manager'),
        ('both', 'Cả hai quyền'),
    ], string='Quyền được gán', required=True, default='user')
    
    auto_assign = fields.Boolean('Tự động gán cho user mới', default=True)
    description = fields.Text('Mô tả')
    


    def action_apply_to_existing_users(self):
        """Áp dụng quy tắc cho tất cả user hiện có"""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Áp dụng quy tắc hoàn thành',
                'message': 'Tự động gán quyền đã bị vô hiệu hóa',
                'type': 'info',
            }
        }

class ResUsers(models.Model):
    _inherit = 'res.users'
    

    


    @api.onchange('groups_id')
    def _onchange_groups_id(self):
        """Override onchange để tránh lỗi KeyError khi thay đổi groups"""
        # Không làm gì cả, chỉ để tránh lỗi KeyError
        pass

    def onchange(self, values, field_names, fields_spec):
        """Override onchange để xử lý an toàn groups_id field"""
        try:
            return super().onchange(values, field_names, fields_spec)
        except KeyError as e:
            if 'groups_id' in str(e):
                # Nếu gặp lỗi KeyError với groups_id, trả về kết quả rỗng
                _logger.warning(f"KeyError với groups_id được xử lý an toàn cho user: {self}")
                return {'value': {}, 'warning': {}, 'domain': {}}
            else:
                # Nếu là lỗi khác, raise lại
                raise
    
    def action_assign_student_permissions(self):
        """Action để gán quyền student request cho user"""
        user_group = self.env.ref('student_request.group_student_request_user')
        
        for user in self:
            if user_group not in user.groups_id:
                user.write({'groups_id': [(4, user_group.id)]})
                
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Gán quyền thành công',
                'message': f'Đã gán quyền Student Request User cho {len(self)} users',
                'type': 'success',
            }
        }
    
    def action_assign_manager_permissions(self):
        """Action để gán quyền manager cho user"""
        manager_group = self.env.ref('student_request.group_student_request_manager')
        user_group = self.env.ref('student_request.group_student_request_user')
        
        for user in self:
            groups_to_add = []
            if user_group not in user.groups_id:
                groups_to_add.append(user_group.id)
            if manager_group not in user.groups_id:
                groups_to_add.append(manager_group.id)
                
            if groups_to_add:
                user.write({'groups_id': [(4, group_id) for group_id in groups_to_add]})
                
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Gán quyền thành công',
                'message': f'Đã gán quyền Student Request Manager cho {len(self)} users',
                'type': 'success',
            }
        }
    
    def action_remove_student_permissions(self):
        """Action để gỡ quyền student request"""
        manager_group = self.env.ref('student_request.group_student_request_manager')
        user_group = self.env.ref('student_request.group_student_request_user')
        
        for user in self:
            groups_to_remove = []
            if manager_group in user.groups_id:
                groups_to_remove.append(manager_group.id)
            if user_group in user.groups_id:
                groups_to_remove.append(user_group.id)
                
            if groups_to_remove:
                user.write({'groups_id': [(3, group_id) for group_id in groups_to_remove]})
                
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Gỡ quyền thành công',
                'message': f'Đã gỡ quyền Student Request cho {len(self)} users',
                'type': 'success',
            }
        }