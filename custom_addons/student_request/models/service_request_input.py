from odoo import models, fields, api

class ServiceRequestInput(models.Model):
    _name = 'student.service.request.input'
    _description = 'Service Request Input'
    _order = 'sequence'

    request_id = fields.Many2one('student.service.request', string='Yêu cầu', ondelete='cascade')
    service_form_field_id = fields.Many2one('student.service.form.field', string='Cấu hình trường')
    
    # Normal fields (NOT related) - populated directly from onchange
    sequence = fields.Integer(string='Thứ tự')
    name = fields.Char(string='Mã trường (JSON)')
    label = fields.Char(string='Tên trường')
    field_type = fields.Selection([
    ('text', 'Text'),
    ('textarea', 'Textarea'),
    ('number', 'Number'),
    ('date', 'Date'),
    ('date_multi', 'Chọn nhiều ngày'),
    ('select', 'Dropdown'),
    ('checkbox', 'Checkbox'),
    ], string='Loại dữ liệu')
    required = fields.Boolean(string='Bắt buộc')
    placeholder = fields.Char(string='Gợi ý')
    selection_options = fields.Text(string='Các lựa chọn')
    # Computed field to convert selection_options to Selection format
    # Many2many field for options
    selected_option_ids = fields.Many2many(
        'student.service.option',
        string='Selected Options',
        help='Dropdown với options từ service form field'
    )
    
    # Multi Date field
    date_ids = fields.One2many('student.service.request.input.date', 'input_id', string='Các ngày đã chọn')
    
    @api.depends('selected_option_ids', 'selected_option_ids.name')
    def _compute_value_selection(self):
        for rec in self:
            if rec.selected_option_ids:
                rec.value_selection = ', '.join(rec.selected_option_ids.mapped('name'))
            else:
                rec.value_selection = False

    # Value fields
    value_char = fields.Char(string='Giá trị')
    value_text = fields.Text(string='Giá trị')
    value_integer = fields.Integer(string='Giá trị')
    value_float = fields.Float(string='Giá trị')
    value_date = fields.Date(string='Giá trị')
    value_datetime = fields.Datetime(string='Giá trị')
    value_boolean = fields.Boolean(string='Giá trị')
    value_selection = fields.Char(string='Giá trị', compute='_compute_value_selection', store=True)

    # Computed display value
    value_display = fields.Char(string='Giá trị hiển thị', compute='_compute_value_display')
    

    @api.depends('field_type', 'value_char', 'value_text', 'value_integer', 'value_float', 
                 'value_date', 'value_datetime', 'value_boolean', 'value_selection',
                 'date_ids', 'date_ids.date')
    def _compute_value_display(self):
        for rec in self:
            val = ''
            # Map field_type from ServiceFormField
            if rec.field_type == 'text':
                val = rec.value_char or ''
            elif rec.field_type == 'textarea':
                val = rec.value_text or ''
            elif rec.field_type == 'number':
                val = str(rec.value_float) if rec.value_float else ''
            elif rec.field_type == 'date':
                val = str(rec.value_date) if rec.value_date else ''
            elif rec.field_type == 'checkbox':
                val = 'Có' if rec.value_boolean else 'Không'
            elif rec.field_type == 'select':
                val = rec.value_selection or ''
            elif rec.field_type == 'date_multi':
                dates = rec.date_ids.mapped('date')
                val = ', '.join([d.strftime('%d/%m/%Y') for d in dates if d])
            
            rec.value_display = val

class ServiceRequestInputDate(models.Model):
    _name = 'student.service.request.input.date'
    _description = 'Selected Dates'
    _order = 'date'
    
    input_id = fields.Many2one('student.service.request.input', ondelete='cascade')
    date = fields.Date(string='Ngày', required=True)
