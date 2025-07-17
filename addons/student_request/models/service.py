from odoo import models, fields, api

# Model quản lý nhóm dịch vụ (có thể lồng nhiều cấp)
class ServiceGroup(models.Model):
    _name = 'student.service.group'
    _description = 'Nhóm dịch vụ'

    name = fields.Char('Tên nhóm', required=True)
    description = fields.Text('Mô tả nhóm')
    service_ids = fields.One2many('student.service', 'group_id', string='Dịch vụ thuộc nhóm')
    parent_id = fields.Many2one('student.service.group', string='Nhóm cha')
    child_ids = fields.One2many('student.service.group', 'parent_id', string='Nhóm con')

    def action_unlink_with_children(self):
        for group in self:
            group._unlink_with_children_recursive()

    def _unlink_with_children_recursive(self):
        # Xóa tất cả nhóm con trước
        for child in self.child_ids:
            child._unlink_with_children_recursive()
        # Xóa chính nó
        self.unlink()

# Model quản lý dịch vụ
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
    group_id = fields.Many2one('student.service.group', string='Nhóm dịch vụ')

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

# Model quản lý các bước duyệt dịch vụ
class ServiceStep(models.Model):
    _name = 'student.service.step'
    _description = 'Bước duyệt dịch vụ'
    _order = 'sequence'

    name = fields.Char('Tên bước', required=True, help='Tên bước duyệt dịch vụ')
    sequence = fields.Integer('Thứ tự', default=1)
    description = fields.Text('Mô tả bước')
    user_ids = fields.Many2many('res.users', string='Người thực hiện', help='Người thực hiện bước này')
    nextstep = fields.Integer('Thứ tự', default=99)
    state = fields.Integer('Trạng thái', default=1)  # Trạng thái bước, mặc định là 1 (có thể chỉnh sửa)

    def unlink(self):
        for step in self:
            if step.state == 0:
                raise models.ValidationError("Không thể xóa bước mặc định!")
        return super().unlink()

# Model quản lý file cần gửi kèm dịch vụ
class ServiceFile(models.Model):
    _name = 'student.service.file'
    _description = 'File cần gửi kèm dịch vụ'

    name = fields.Char('Tên file', required=True)

# Model lưu lịch sử duyệt từng bước của một yêu cầu dịch vụ
class ServiceRequestStepHistory(models.Model):
    _name = 'student.service.request.step.history'
    _description = 'Lịch sử duyệt từng bước của Request'

    request_id = fields.Many2one('student.service.request', string='Request', required=True, ondelete='cascade')
    step_id = fields.Many2one('student.service.step', string='Bước duyệt', required=True)
    user_id = fields.Many2one('res.users', string='Người duyệt')
    state = fields.Selection([
        ('pending', 'Chờ duyệt'),
        ('approved', 'Đã duyệt'),
        ('rejected', 'Từ chối')
    ], string='Trạng thái', default='pending')
    approve_content = fields.Text('Nội dung duyệt')
    approve_date = fields.Datetime('Ngày duyệt')

# Model quản lý yêu cầu dịch vụ của sinh viên
class ServiceRequest(models.Model):
    _name = 'student.service.request'
    _description = 'Yêu cầu dịch vụ của sinh viên'

    service_id = fields.Many2one('student.service', string='Dịch vụ', required=True)
    request_user_id = fields.Many2one('res.users', string='Người gửi yêu cầu', required=True, default=lambda self: self.env.user)
    request_date = fields.Datetime('Ngày gửi', default=fields.Datetime.now)
    note = fields.Text('Ghi chú')
    file_ids = fields.Many2many('student.service.file', string='Files đính kèm')
    step_history_ids = fields.One2many('student.service.request.step.history', 'request_id', string='Lịch sử các bước duyệt')
    final_state = fields.Selection([
        ('pending', 'Chờ duyệt'),
        ('approved', 'Đã duyệt'),
        ('rejected', 'Từ chối')
    ], string='Trạng thái duyệt cuối', default='pending')
    approve_content = fields.Text('Nội dung duyệt cuối')
    approve_date = fields.Datetime('Ngày duyệt cuối')

    def action_approve_request(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Duyệt yêu cầu dịch vụ',
            'res_model': 'student.service.request',
            'view_mode': 'form',
            'view_id': self.env.ref('student_request.view_service_request_approve_form').id,
            'res_id': self.id,
            'target': 'new',
            'context': dict(self.env.context),
        }

    def action_confirm_approve(self):
        self.final_state = 'approved'
        self.approve_date = fields.Datetime.now()
        # ...bạn có thể thêm logic lưu lịch sử duyệt ở đây...
        return {'type': 'ir.actions.act_window_close'}
        # ...bạn có thể thêm logic lưu lịch sử duyệt ở đây...
        return {'type': 'ir.actions.act_window_close'}

# Các chức năng đã có trong module Student_Request:
# - Quản lý danh mục file cần gửi kèm dịch vụ (`student.service.file`)
# - Quản lý các bước duyệt dịch vụ, phân công người thực hiện từng bước (`student.service.step`)
# - Quản lý dịch vụ: tên, mô tả, trạng thái hoạt động, người duyệt, các file cần gửi kèm, các bước duyệt (`student.service`)
# - Quản lý nhóm dịch vụ (`student.service.group`)
# - Quản lý yêu cầu dịch vụ của sinh viên (`student.service.request`)
# - Lịch sử duyệt từng bước của Request (`student.service.request.step.history`)
# - Quản lý yêu cầu dịch vụ của sinh viên (`student.service.request`)
# - Lịch sử duyệt từng bước của Request (`student.service.request.step.history`)
