import re
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ServiceFormField(models.Model):
    """Trường thông tin trong form dịch vụ"""
    _name = 'student.service.form.field'
    _description = 'Trường form dịch vụ'
    _order = 'sequence, id'
    
    service_id = fields.Many2one(
        'student.service', 
        string='Dịch vụ', 
        required=True, 
        ondelete='cascade',
        index=True
    )
    name = fields.Char(
        string='Tên field', 
        required=True,
        help='Tên kỹ thuật (VD: student_id). Chỉ dùng a-z, 0-9, _'
    )
    field_type = fields.Selection([
        ('text', 'Text'),
        ('textarea', 'Textarea (nhiều dòng)'),
        ('number', 'Number'),
        ('date', 'Date'),
        ('date_multi', 'Chọn nhiều ngày'),
        ('select', 'Dropdown'),
        ('checkbox', 'Checkbox'),
        ('file', 'File Upload')
    ], string='Loại', required=True, default='text')
    
    label = fields.Char(
        string='Nhãn hiển thị', 
        required=True,
        help='Nhãn hiển thị cho user (VD: "Mã sinh viên")'
    )
    placeholder = fields.Char(
        string='Placeholder',
        help='Gợi ý nhập (VD: "Nhập mã sinh viên 8 số")'
    )
    required = fields.Boolean(
        string='Bắt buộc', 
        default=False,
        help='User phải nhập khi tạo yêu cầu'
    )
    sequence = fields.Integer(
        string='Thứ tự', 
        default=10,
        help='Thứ tự hiển thị trong form'
    )
    
    # Cho select dropdown
    options = fields.Text(
        string='Options',
        help='Mỗi dòng 1 option. VD:\nCMND/CCCD\nBằng lái xe\nGiấy khám SK'
    )
    option_ids = fields.One2many(
        'student.service.option',
        'form_field_id',
        string='Options (Many2many)',
        help='Danh sách options cho dropdown'
    )
    
    @api.onchange('options')
    def _onchange_options_to_many2many(self):
        """Auto create option_ids from options text"""
        if self.field_type == 'select' and self.options:
            # Parse options text
            option_lines = [opt.strip() for opt in self.options.split('\n') if opt.strip()]
            
            # Clear old options
            commands = [(5, 0, 0)]
            
            # Create new options
            for seq, opt in enumerate(option_lines, 1):
                commands.append((0, 0, {
                    'name': opt,
                    'sequence': seq * 10,
                }))
            
            self.option_ids = commands
    @api.model_create_multi
    def create(self, vals_list):
        """Auto create options when creating form field"""
        records = super().create(vals_list)
        for rec in records:
            if rec.field_type == 'select' and rec.options:
                rec._sync_options_to_many2many()
        return records
    
    def write(self, vals):
        """Auto create options when updating form field"""
        result = super().write(vals)
        if 'options' in vals or 'field_type' in vals:
            for rec in self:
                if rec.field_type == 'select' and rec.options:
                    rec._sync_options_to_many2many()
        return result
    
    def _sync_options_to_many2many(self):
        """Sync options text to option_ids"""
        self.ensure_one()
        if not self.options:
            self.option_ids = [(5, 0, 0)]
            return
        
        # Parse options
        option_lines = [opt.strip() for opt in self.options.split('\n') if opt.strip()]
        
        # Clear and create
        commands = [(5, 0, 0)]
        for seq, opt in enumerate(option_lines, 1):
            commands.append((0, 0, {
                'name': opt,
                'sequence': seq * 10,
            }))
        
        self.option_ids = commands
    # SQL constraint
    _sql_constraints = [
        ('unique_name_per_service', 
         'unique(service_id, name)', 
         'Tên field phải unique trong 1 dịch vụ!')
    ]
    
    @api.constrains('name')
    def _check_name_format(self):
        """Validate field name chỉ dùng a-z, 0-9, _"""
        for rec in self:
            if not re.match(r'^[a-z][a-z0-9_]*$', rec.name):
                raise ValidationError(
                    f'Field name "{rec.name}" không hợp lệ!\n'
                    'Chỉ được dùng: a-z (chữ thường), 0-9, _\n'
                    'Phải bắt đầu bằng chữ cái.'
                )
    
    @api.constrains('field_type', 'options')
    def _check_select_has_options(self):
        """Select phải có options"""
        for rec in self:
            if rec.field_type == 'select' and not rec.options:
                raise ValidationError(
                    f'Field "{rec.label}" loại Dropdown phải có Options!'
                )
    
    def get_options_list(self):
        """Trả về list options"""
        self.ensure_one()
        if not self.options:
            return []
        return [opt.strip() for opt in self.options.split('\n') if opt.strip()]
