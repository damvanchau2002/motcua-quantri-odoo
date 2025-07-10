from odoo import models, fields, api

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

    def action_configure_steps(self):
        """
        Tự động cấu hình các bước cho service:
        - Thêm bước 1 (Khởi tạo) vào đầu nếu chưa có
        - Thêm bước 99 (Kết thúc) vào cuối nếu chưa có
        """
        Step = self.env['student.service.step']
        for service in self:
            steps = service.step_ids.sorted('sequence')
            step_names = steps.mapped('name')
            # Thêm bước 1 nếu chưa có
            if not any(s.sequence == 1 for s in steps):
                step1 = Step.create({
                    'name': 'Khởi tạo',
                    'sequence': 1,
                    'description': 'Bước khởi tạo',
                    'nextstep': steps[0].sequence if steps else 99,
                })
                service.step_ids = [(4, step1.id)]
            # Thêm bước 99 nếu chưa có
            if not any(s.sequence == 99 for s in steps):
                step99 = Step.create({
                    'name': 'Kết thúc',
                    'sequence': 99,
                    'description': 'Bước kết thúc',
                    'nextstep': 0,
                })
                service.step_ids = [(4, step99.id)]

# Các chức năng đã có trong module Student_Request:
# - Quản lý danh mục file cần gửi kèm dịch vụ (`student.service.file`)
# - Quản lý các bước duyệt dịch vụ, phân công người thực hiện từng bước (`student.service.step`)
# - Quản lý dịch vụ: tên, mô tả, trạng thái hoạt động, người duyệt, các file cần gửi kèm, các bước duyệt (`student.service`)
