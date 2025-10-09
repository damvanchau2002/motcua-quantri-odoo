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
    
    @api.model
    def auto_assign_permissions(self, user):
        """Tự động gán quyền cho user dựa trên các quy tắc"""
        if not user or not user.active:
            return
            
        rules = self.search([('active', '=', True), ('auto_assign', '=', True)])
        manager_group = self.env.ref('student_request.group_student_request_manager')
        user_group = self.env.ref('student_request.group_student_request_user')
        
        assigned_groups = []
        
        for rule in rules:
            should_assign = False
            
            if rule.condition_type == 'email_domain' and user.email:
                if rule.condition_value and user.email.endswith(rule.condition_value):
                    should_assign = True
                    
            elif rule.condition_type == 'login_pattern' and user.login:
                if rule.condition_value:
                    pattern = rule.condition_value.replace('*', '')
                    if rule.condition_value.endswith('*'):
                        should_assign = user.login.startswith(pattern)
                    elif rule.condition_value.startswith('*'):
                        should_assign = user.login.endswith(pattern)
                    else:
                        should_assign = pattern in user.login
            
            if should_assign:
                if rule.target_group in ['user', 'both']:
                    if user_group not in user.groups_id:
                        assigned_groups.append(user_group.id)
                        
                if rule.target_group in ['manager', 'both']:
                    if manager_group not in user.groups_id:
                        assigned_groups.append(manager_group.id)
                        
                _logger.info(f"Quy tắc '{rule.name}' áp dụng cho user {user.login}")
        
        if assigned_groups:
            user.write({'groups_id': [(4, group_id) for group_id in assigned_groups]})
            _logger.info(f"Đã gán quyền tự động cho user {user.login}: {assigned_groups}")
            
        return assigned_groups

    def action_apply_to_existing_users(self):
        """Áp dụng quy tắc cho tất cả user hiện có"""
        users = self.env['res.users'].search([('active', '=', True)])
        applied_count = 0
        
        for user in users:
            assigned = self.auto_assign_permissions(user)
            if assigned:
                applied_count += 1
                
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Áp dụng quy tắc hoàn thành',
                'message': f'Đã áp dụng quy tắc cho {applied_count} users',
                'type': 'success',
            }
        }

class ResUsers(models.Model):
    _inherit = 'res.users'
    
    @api.model_create_multi
    def create(self, vals_list):
        """Override create để tự động gán quyền cho user mới"""
        users = super().create(vals_list)
        
        permission_manager = self.env['student.permission.manager']
        for user in users:
            try:
                permission_manager.auto_assign_permissions(user)
            except Exception as e:
                _logger.warning(f"Không thể tự động gán quyền cho user {user.login}: {e}")
                
        return users
    
    def write(self, vals):
        """Override write để cập nhật quyền khi thông tin user thay đổi"""
        result = super().write(vals)
        
        # Chỉ tự động gán lại quyền khi email hoặc login thay đổi
        # Tránh xung đột với onchange bằng cách không gán quyền khi đang trong quá trình onchange
        if ('email' in vals or 'login' in vals) and not self.env.context.get('skip_auto_permissions'):
            permission_manager = self.env['student.permission.manager']
            for user in self:
                try:
                    # Sử dụng context để tránh vòng lặp vô hạn
                    permission_manager.with_context(skip_auto_permissions=True).auto_assign_permissions(user)
                except Exception as e:
                    _logger.warning(f"Không thể tự động cập nhật quyền cho user {user.login}: {e}")
                    
        return result

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