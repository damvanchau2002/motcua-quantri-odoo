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
    titlenote = fields.Char('Tiêu đề gửi nội dung yêu cầu', help='Ghi chú cho SV thông tin cần nhập như thế nào')

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

class ServiceFileCheckbox(models.Model):
    _name = 'student.service.file.checkbox'
    _description = 'File checkbox cho từng bước duyệt'

    step_id = fields.Many2one('student.service.request.step', string='Bước duyệt')
    file_id = fields.Many2one('student.service.file', string='File cần nộp')
    checked = fields.Boolean('Đã chọn', default=False)

# Model quản lý lịch sử duyệt từng bước của yêu cầu dịch vụ
class ServiceRequestStep(models.Model):
    _name = 'student.service.request.step'
    _description = 'Dòng duyệt từng bước'

    request_id = fields.Many2one('student.service.request', string='Yêu cầu dịch vụ')
    base_step_id = fields.Many2one('student.service.step', string='Bước duyệt')
    # người duyệt bước này
    user_id = fields.Many2one('res.users', string='Người duyệt')
    state = fields.Selection([
        ('pending', 'Chờ duyệt'),
        ('approved', 'Đã duyệt'),
        ('rejected', 'Từ chối')
    ], string='Trạng thái', default='pending')
    approve_content = fields.Text('Nội dung duyệt')
    # Các giấy tờ cần nộp trong bước này
    file_ids = fields.Many2many(
        'student.service.file',
        'student_service_step_file_rel',  # bảng quan hệ riêng cho file_ids
        'step_id', 'file_id',
        string='Giấy tờ cần nộp',
        help='Các giấy tờ cần nộp trong bước này'
    )
    # Nếu là bước đầu tiên, các giấy tờ đã nộp
    file_checkbox_ids = fields.Many2many(
        'student.service.file',
        'student_service_step_file_checkbox_rel',  # bảng quan hệ riêng cho file_checkbox_ids
        'step_id', 'file_id',
        string='Hồ sơ đã nộp',
        help='Các giấy tờ đã nộp trong bước này'
    )

# Model yêu cầu dịch vụ của sinh viên
class ServiceRequest(models.Model):
    _name = 'student.service.request'
    _description = 'Yêu cầu dịch vụ của sinh viên'

    name = fields.Char('Tên yêu cầu', required=True, help='Tên mô tả ngắn gọn cho yêu cầu dịch vụ')

    service_id = fields.Many2one('student.service', string='Dịch vụ', required=True)
    request_user_id = fields.Many2one('res.users', string='Người gửi yêu cầu', required=True, default=lambda self: self.env.user)
    request_user_name = fields.Char('Tên người gửi', required=False, related='request_user_id.name')
    request_user_avatar = fields.Binary('Ảnh đại diện', required=False, related='request_user_id.image_1920')

    request_date = fields.Datetime('Ngày gửi', default=fields.Datetime.now)
    note = fields.Text('Ghi chú')
    
    # Ảnh đính kèm Gửi theo yêu cầu dịch vụ (là các ảnh giấy tờ liên quan) 
    image_attachment_ids = fields.Many2many(
        'ir.attachment',
        string='Ảnh đính kèm',
        domain=[('mimetype', 'ilike', 'image')],
        help='Ảnh đính kèm cho yêu cầu dịch vụ'
    )

    step_history_ids = fields.One2many('student.service.request.step', 'request_id', string='Lịch sử các bước duyệt')
    final_state = fields.Selection([
        ('pending', 'Chờ duyệt'),
        ('approved', 'Đã duyệt'),
        ('rejected', 'Từ chối')
      ], string='Trạng thái duyệt cuối', default='pending')
    approve_content = fields.Text('Nội dung duyệt cuối')
    approve_date = fields.Datetime('Ngày duyệt cuối')

    # Bước duyệt hiện tại (bước đầu tiên sẽ là bước đầu tiên trong danh sách step_ids của service)
    step_id = fields.Many2one('student.service.step', string='Bước duyệt hiện tại', required=False)
    # Người duyệt dịch vụ này
    users = fields.Many2many('res.users', string='Người duyệt', help='Người có quyền duyệt dịch vụ này')

    def write(self, vals):
        # Xử lý dữ liệu trước khi ghi
        # Ví dụ: cập nhật trạng thái cuối nếu có thay đổi
        if 'final_state' in vals:
            vals['approve_date'] = fields.Datetime.now()
        return super().write(vals)

    @api.model
    def create(self, vals):
        # Xử lý dữ liệu trước khi tạo mới
        service = self.env['student.service'].browse(vals.get('service_id'))
        # Get user name from vals or fetch from user record
        user_id = vals.get('request_user_id')
        user_name = 'Yêu cầu dịch vụ: '
        if user_id:
            user = self.env['res.users'].browse(user_id)
            user_name = user.name or ''
        vals['name'] = user_name + ': ' + service.name
        # Tạo các bản ghi student.service.request.step ứng với mỗi bước duyệt của dịch vụ
        step_ids = service.step_ids.sorted('sequence')
        step_history_ids = []
        for step in step_ids:
            step_request = self.env['student.service.request.step'].create({
                'request_id': self.id if self.id else False,
                'base_step_id': step.id,
                'state': 'pending',
            })
            # Tạo file_checkbox_ids cho từng file của step
            # Nếu là bước đầu tiên, tạo các bản ghi file_checkbox ứng với mỗi file trong service.files
            if step == step_ids[0]:
                vals['step_id'] = step.id
                # Thêm các files cần của Dịch vụ vào file_ids
                if service.files:
                    step_request.file_ids = [(6, 0, service.files.ids)]
            step_history_ids.append(step_request.id)
        if step_history_ids:
            vals['step_history_ids'] = [(6, 0, step_history_ids)]

        # Thêm các Users trong Service.users vào Request
        if service.users:
            vals['users'] = [(6, 0, service.users.ids)]
        # Lưu
        return super().create(vals)



# Các chức năng đã có trong module Student_Request:
# - Quản lý danh mục file cần gửi kèm dịch vụ (`student.service.file`)
# - Quản lý các bước duyệt dịch vụ, phân công người thực hiện từng bước (`student.service.step`)
# - Quản lý dịch vụ: tên, mô tả, trạng thái hoạt động, người duyệt, các file cần gửi kèm, các bước duyệt (`student.service`)
# - Quản lý nhóm dịch vụ (`student.service.group`)
# - Quản lý yêu cầu dịch vụ của sinh viên (`student.service.request`)
# - Lịch sử duyệt từng bước của Request (`student.service.request.step`)
# - Quản lý yêu cầu dịch vụ của sinh viên (`student.service.request`)
# - Lịch sử duyệt từng bước của Request (`student.service.request.step`)


class StudentUserProfile(models.Model):
    _name = 'student.user.profile'
    _description = 'Thông tin sinh viên KTX'

    user_id = fields.Many2one('res.users', string='User', required=True, ondelete='cascade')
    
    avatar_url = fields.Char('Avatar URL')
    birthday = fields.Date('Ngày sinh')
    gender = fields.Boolean(string='Giới tính')
    dormitory_full_name = fields.Char('Tên ký túc xá')
    dormitory_room_id = fields.Char('Phòng ký túc xá')
    rent_id = fields.Char('Mã hợp đồng thuê')
    university_name = fields.Char('Tên trường đại học')
    student_code = fields.Char('Mã sinh viên')
    id_card_number = fields.Char('Số CMND/CCCD')
    id_card_date = fields.Char('Ngày cấp CMND/CCCD')
    id_card_issued_name = fields.Char('Nơi cấp CMND/CCCD')
    address = fields.Char('Địa chỉ')
    district_name = fields.Char('Tên quận/huyện')
    province_name = fields.Char('Tên tỉnh/thành phố')
    phone = fields.Char('Số điện thoại')
    email = fields.Char('Email')
    dormitory_area_id = fields.Integer('ID khu ký túc xá')
    dormitory_house_name = fields.Char('Tên nhà ký túc xá')
    dormitory_cluster_id = fields.Integer('ID cụm ký túc xá')
    dormitory_room_type_name = fields.Char('Loại phòng ký túc xá')
    fcm_token = fields.Char('FCM Token', help='Firebase Cloud Messaging Token cho thông báo đẩy')
    device_id = fields.Char('Device ID', help='Mã thiết bị của sinh viên')