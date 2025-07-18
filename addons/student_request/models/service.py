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
    attachment = fields.Char('File Attachment', required=False)
    description = fields.Text('Mô tả file')

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

    def action_confirm_approve(self):
        self.final_state = 'approved'
        self.approve_date = fields.Datetime.now()
        # Tạo bản ghi lịch sử duyệt bước
        if self.step_id:
            self.env['student.service.request.step.history'].create({
                'request_id': self.id,
                'step_id': self.step_id.id,
                'user_id': self.env.user.id,
                'state': 'approved',
                'approve_content': self.approve_content,
                'approve_date': fields.Datetime.now(),
            })
        return {'type': 'ir.actions.act_window_close'}

# Model yêu cầu dịch vụ của sinh viên
class ServiceRequest(models.Model):
    _name = 'student.service.request'
    _description = 'Yêu cầu dịch vụ của sinh viên'

    service_id = fields.Many2one('student.service', string='Dịch vụ', required=True)
    request_user_id = fields.Many2one('res.users', string='Người gửi yêu cầu', required=True, default=lambda self: self.env.user)
    request_user_name = fields.Char('Tên người gửi', required=False, related='request_user_id.name')
    request_user_avatar = fields.Binary('Ảnh đại diện', required=False, related='request_user_id.image_1920')

    request_date = fields.Datetime('Ngày gửi', default=fields.Datetime.now)
    note = fields.Text('Ghi chú')
    file_ids = fields.Many2many('student.service.file', string='Files đính kèm')
    image_attachment_ids = fields.Many2many(
        'ir.attachment',
        string='Ảnh đính kèm',
        domain=[('mimetype', 'ilike', 'image')],
        help='Ảnh đính kèm cho yêu cầu dịch vụ'
    )

    step_history_ids = fields.One2many('student.service.request.step.history', 'request_id', string='Lịch sử các bước duyệt')
    final_state = fields.Selection([
        ('pending', 'Chờ duyệt'),
        ('approved', 'Đã duyệt'),
        ('rejected', 'Từ chối')
      ], string='Trạng thái duyệt cuối', default='pending')
    approve_content = fields.Text('Nội dung duyệt cuối')
    approve_date = fields.Datetime('Ngày duyệt cuối')

    step_id = fields.Many2one('student.service.step', string='Bước duyệt hiện tại', required=False)


    def action_open_approve(self):
        print("Self open approve data:", self)
        self.ensure_one()
        # Lấy service_id và request_id từ context (do button truyền vào)
        service_id = self.env.context.get('default_service_id')
        request_id = self.env.context.get('default_request_id')

        service = self.env['student.service'].browse(service_id)
        # Xác định step_id: nếu self.step_id có thì dùng, nếu không thì lấy bước đầu tiên theo sequence nhỏ nhất
        step_id = self.step_id.id if self.step_id else False
        if not step_id and service and service.step_ids:
            first_step = service.step_ids.sorted(key=lambda s: s.sequence)[0]
            step_id = first_step.id


        # Tạo bản ghi lịch sử duyệt bước với giá trị mặc định
        history = self.env['student.service.request.step.history'].create({
            'request_id': request_id or self.id,
            'step_id': step_id,
            'user_id': self.env.user.id,
            'state': 'pending',
            'approve_content': 'Đã duyệt',
            'approve_date': fields.Datetime.now(),
        })

        return {
            'type': 'ir.actions.act_window',
            'name': 'Duyệt yêu cầu',
            'res_model': 'student.service.request.step.history',
            'view_mode': 'form',
            'res_id': history.id,
            'view_id': self.env.ref('student_request.popup_service_request_approve_form').id,
            'target': 'new',
            'context': dict(self.env.context, default_service_id=service_id, default_request_id=request_id),
        }

    

# Các chức năng đã có trong module Student_Request:
# - Quản lý danh mục file cần gửi kèm dịch vụ (`student.service.file`)
# - Quản lý các bước duyệt dịch vụ, phân công người thực hiện từng bước (`student.service.step`)
# - Quản lý dịch vụ: tên, mô tả, trạng thái hoạt động, người duyệt, các file cần gửi kèm, các bước duyệt (`student.service`)
# - Quản lý nhóm dịch vụ (`student.service.group`)
# - Quản lý yêu cầu dịch vụ của sinh viên (`student.service.request`)
# - Lịch sử duyệt từng bước của Request (`student.service.request.step.history`)
# - Quản lý yêu cầu dịch vụ của sinh viên (`student.service.request`)
# - Lịch sử duyệt từng bước của Request (`student.service.request.step.history`)
