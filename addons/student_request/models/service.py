from odoo import models, fields

class ServiceFile(models.Model):
    _name = 'student.service.file'
    _description = 'File cần gửi kèm dịch vụ'

    name = fields.Char('Tên file', required=True)
    

class ServiceStep(models.Model):
    _name = 'student.service.step'
    _description = 'Bước duyệt dịch vụ'

    name = fields.Char('Tên bước', required=True)
    sequence = fields.Integer('Thứ tự', default=1)
    description = fields.Text('Mô tả bước')
    user_ids = fields.Many2many('res.users', string='Người thực hiện', help='Người thực hiện bước này')
    nextstep = fields.Integer('Thứ tự', default=99)

class Service(models.Model):
    _name = 'student.service'
    _description = 'Dịch vụ'

    name = fields.Char('Tên dịch vụ', required=True)
    description = fields.Text('Mô tả chi tiết')
    files = fields.Many2many('student.service.file', string='Files cần gửi kèm')
    state = fields.Selection([
        ('enabled', 'Enabled'),
        ('disabled', 'Disabled')
    ], string='Hoạt động', default='enabled')
    users = fields.Many2many('res.users', string='Người duyệt', help='Người có quyền duyệt dịch vụ này')
    step_ids = fields.Many2many('student.service.step',  string='Các bước duyệt')
