from odoo import models, fields, api
from odoo.exceptions import ValidationError
import re


class ServiceFieldTemplate(models.Model):
    """Template cho các trường form dịch vụ"""
    _name = 'student.service.field.template'
    _description = 'Template trường form dịch vụ'
    _order = 'sequence, name'
    
    name = fields.Char(
        string='Tên kỹ thuật',
        required=True,
        help='Tên kỹ thuật của field (VD: student_id, full_name). Chỉ dùng a-z, 0-9, _'
    )
    label = fields.Char(
        string='Nhãn hiển thị',
        required=True,
        help='Nhãn hiển thị mặc định cho user (VD: "Mã sinh viên", "Họ và tên")'
    )
    description = fields.Text(
        string='Mô tả',
        help='Mô tả chi tiết về field này'
    )
    field_type_suggestion = fields.Selection([
        ('text', 'Text'),
        ('textarea', 'Textarea'),
        ('number', 'Number'),
        ('date', 'Date'),
        ('date_multi', 'Chọn nhiều ngày'),
        ('select', 'Dropdown'),
        ('checkbox', 'Checkbox'),
    ], string='Loại field đề xuất', help='Loại field được đề xuất khi sử dụng template này')
    
    placeholder = fields.Char(
        string='Placeholder',
        help='Gợi ý hiển thị trong ô nhập liệu (VD: "Nhập mã sinh viên")'
    )
    
    required = fields.Boolean(
        string='Bắt buộc',
        default=False,
        help='Đánh dấu field này là bắt buộc nhập'
    )
    
    options = fields.Text(
        string='Options',
        help='Các lựa chọn cho dropdown (mỗi dòng một option)'
    )
    
    sequence = fields.Integer(string='Thứ tự', default=10, help='Thứ tự hiển thị trong danh sách')
    active = fields.Boolean(string='Hoạt động', default=True)
    
    # SQL constraint
    _sql_constraints = [
        ('unique_name', 
         'unique(name)', 
         'Tên kỹ thuật phải unique!')
    ]
    
    @api.constrains('name')
    def _check_name_format(self):
        """Validate field name chỉ dùng a-z, 0-9, _"""
        for rec in self:
            if not re.match(r'^[a-z][a-z0-9_]*$', rec.name):
                raise ValidationError(
                    f'Tên kỹ thuật "{rec.name}" không hợp lệ!\n'
                    'Chỉ được dùng: a-z (chữ thường), 0-9, _\n'
                    'Phải bắt đầu bằng chữ cái.'
                )
    
    def name_get(self):
        """Hiển thị: 'name - label'"""
        result = []
        for record in self:
            name = f"{record.name} - {record.label}" if record.label else record.name
            result.append((record.id, name))
        return result
