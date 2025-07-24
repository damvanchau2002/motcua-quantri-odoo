import os
from odoo import models, fields, api
from odoo.addons.student_request.controllers.service_api import send_fcm_user, send_fcm_admin
import json
import requests

def action_sync_area_cluster(self):
        url = "https://sv_test.ktxhcm.edu.vn/MotCuaApi/GetDormitoryCatalog"
        headers = {"X-Api-Key": "motcua_ktx_maia_apikey"}
        try:
            response = requests.get(url, headers=headers, verify=False, timeout=30)
            response.raise_for_status()
            data = response.json()
            clusters = data.get("Data", {}).get("Clusters", [])
            area_obj = self.env['student.dormitory.area']
            cluster_obj = self.env['student.dormitory.cluster']
            # Sync areas
            areas = data.get("Data", {}).get("Areas", [])
            for area in areas:
                vals = {
                    'area_id': area.get("Id"),
                    'name': area.get("Name"),
                    'description': area.get("Description", ''),
                }
                area_rec = area_obj.search([('area_id', '=', area.get("Id"))], limit=1)
                if area_rec:
                    area_rec.write(vals)
                else:
                    area_obj.create(vals)

            # Sync clusters
            for cluster in clusters:
                area_id = cluster.get("DormitoryAreaId")
                area_rec = area_obj.search([('area_id', '=', area_id)], limit=1)
                vals = {
                    'qlsv_cluster_id': cluster.get("Id"),
                    'qlsv_area_id': area_id,
                    'area_id': area_rec.id if area_rec else False,
                    'name': cluster.get("Name"),
                    'description': '',
                }
                cluster_rec = cluster_obj.search([('qlsv_cluster_id', '=', cluster.get("Id"))], limit=1)
                if cluster_rec:
                    cluster_rec.write(vals)
                else:
                    cluster_obj.create(vals)
                    
        except Exception as e:
            raise models.ValidationError("Lỗi đồng bộ cụm KTX: %s" % str(e))
        return {'type': 'ir.actions.client', 'tag': 'reload'}

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
    role_ids = fields.Many2many('student.activity.role', string='Vai trò duyệt', help='Các vai trò có quyền duyệt dịch vụ này')


# Định nghĩa bước duyệt dịch vụ
class ServiceStep(models.Model):
    _name = 'student.service.step'
    _description = 'Bước duyệt dịch vụ'
    _order = 'sequence'

    name = fields.Char('Tên bước', required=True, help='Tên bước duyệt dịch vụ')
    sequence = fields.Integer('Thứ tự', default=1)
    description = fields.Text('Mô tả bước')
    nextstep = fields.Integer('Thứ tự', default=99)
    state = fields.Integer('Trạng thái', default=1)  # Trạng thái bước, mặc định là 1 (có thể chỉnh sửa)

    user_ids = fields.Many2many('res.users', string='Người thực hiện', help='Những người cố định nhận được thông báo để thực hiện bước này')
    role_ids = fields.Many2many('student.activity.role', string='Vai trò', help='Các vai trò nhận được thông báo để thực hiện bước này')

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
    # Người đã duyệt bước này
    user_id = fields.Many2one('res.users', string='Người duyệt')

    state = fields.Selection([
        ('pending', 'Chờ duyệt'),
        ('assigned', 'Đã phân công'),
        ('ignored', 'Đã bỏ qua'),
        ('approved', 'Đã duyệt'),
        ('rejected', 'Từ chối')
    ], string='Trạng thái', default='pending')
    approve_content = fields.Text('Nội dung duyệt')
    assign_user_id = fields.Many2one('res.users', string='Người được phân công', help='Người đã được phân công tiêp theo để xử lý bước này')
    approve_date = fields.Datetime('Ngày duyệt', default=fields.Datetime.now)
    assign_history = fields.Text('Lịch sử phân công', help='Lịch sử phân công cho bước này')

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
        ('assigned', 'Đã phân công'),
        ('approved', 'Đã duyệt'),
        ('rejected', 'Từ chối')
      ], string='Trạng thái duyệt cuối', default='pending')
    approve_content = fields.Text('Nội dung duyệt cuối')
    approve_date = fields.Datetime('Ngày duyệt cuối')

    # Bước duyệt hiện tại (bước đầu tiên sẽ là bước đầu tiên trong danh sách step_ids của service)
    step_id = fields.Many2one('student.service.step', string='Bước duyệt hiện tại', required=False)
    # Người duyệt dịch vụ này
    users = fields.Many2many('res.users', string='Người duyệt', help='Người có quyền duyệt dịch vụ này')
    # Vai trò được duyệt dựa trên khu vực người gửi yêu cầu
    role_ids = fields.Many2many('student.activity.role', string='Vai trò được duyệt', help='Các vai trò có quyền duyệt dịch vụ này')

    def write(self, vals):
        # Xử lý dữ liệu trước khi ghi
        # Ví dụ: cập nhật trạng thái cuối nếu có thay đổi
        if 'final_state' in vals:
            vals['approve_date'] = fields.Datetime.now()
        return super().write(vals)

    @api.model
    def create(self, vals):
        # Xử lý dữ liệu trước khi tạo mới
        service = self.env['student.service'].browse(vals.get('service_id')).exists()
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


# Model quản lý thông tin sinh viên KTX
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

# Model quản lý thông tin quản trị viên
class StudentAdminProfile(models.Model):
    _name = 'student.admin.profile'
    _description = 'Thông tin quản trị viên sinh viên KTX'

    user_id = fields.Many2one('res.users', string='User', required=True, ondelete='cascade')
    oauth_ids = fields.One2many('student.admin.oauth', 'profile_id', string='Các provider đăng nhập')

    # Thông tin cá nhân:
    birthday = fields.Date('Ngày sinh')
    gender = fields.Boolean(string='Giới tính')
    phone = fields.Char('Số điện thoại')
    email = fields.Char('Email')
    fcm_token = fields.Char('FCM Token', help='Firebase Cloud Messaging Token cho thông báo đẩy')
    device_id = fields.Char('Device ID', help='Mã thiết bị của sinh viên')

    # Thông tin chờ duyệt:
    title_name = fields.Char('Chức danh', help='Chức danh, khu vực quản lý của quản trị viên sinh viên')
    activated = fields.Boolean('Đã kích hoạt', default=False, help='Trạng thái kích hoạt tài khoản quản trị viên sinh viên')
    dormitory_area_id = fields.Many2one('student.dormitory.area', string='Khu ký túc xá')
    dormitory_cluster_id = fields.Many2one('student.dormitory.cluster', string='Cụm ký túc xá')
    # Thông tin vai trò:
    role_ids = fields.Many2many('student.activity.role', string='Vai trò')

# Model quản lý thông tin OAuth của quản trị viên
class StudentAdminOauth(models.Model):
    _name = 'student.admin.oauth'
    _description = 'Thông tin provider OAuth của quản trị viên sinh viên KTX'

    user_id = fields.Many2one('res.users', string='User', required=True, ondelete='cascade')
    profile_id = fields.Many2one('student.admin.profile', string='Admin Profile', required=True, ondelete='cascade')

    provider = fields.Char('Provider', help='Tên nhà cung cấp dịch vụ OAuth')
    avatar_url = fields.Char('Avatar URL')
    token = fields.Char('OAuth Token', help='OAuth Token cho quản trị viên sinh viên')

# Model quản lý thông báo cho sinh viên và quản trị viên
class StudentNotify(models.Model):
    _name = 'student.notify'
    _description = 'Thông báo cho sinh viên và quản trị viên'

    title = fields.Char('Tiêu đề', required=True)
    body = fields.Text('Nội dung thông báo', required=True)
    read_user_ids = fields.Many2many('res.users', 'student_notify_read_user_rel', 'notify_id', 'user_id', string='Người đã đọc', help='Danh sách người dùng đã đọc thông báo')
    created_date = fields.Datetime('Ngày tạo', default=fields.Datetime.now)
    data = fields.Text('Dữ liệu bổ sung', help='Dữ liệu JSON hoặc thông tin bổ sung cho thông báo')
    
    user_ids = fields.Many2many('res.users', 'student_notify_user_rel', 'notify_id', 'user_id',  string='Danh sách người nhận', help='Danh sách người dùng nhận thông báo')
    dormitory_cluster_ids = fields.Many2many('student.dormitory.cluster', string='Cụm ký túc xá', help='Cụm ký túc xá liên quan đến thông báo')

    user_id = fields.Many2one('res.users', string='Người gửi', help='Người gửi thông báo')
    notify_type = fields.Selection([
        ('user', 'Sinh viên'),
        ('admin', 'Quản trị viên')
    ], string='Loại thông báo', default='user')

    fcm_success_count = fields.Integer('Số lượng gửi thành công', default=0)
    fcm_failure_count = fields.Integer('Số lượng gửi thất bại', default=0)
    fcm_responses = fields.Text('Kết quả gửi FCM', help='Lưu JSON kết quả gửi FCM')

    @api.model
    def create(self, vals):
        # Tạo thông báo mới
        notify = super().create(vals)
        try:
            result = None
            # Gửi FCM nếu có token
            if notify.notify_type == 'user':
                result = send_fcm_user(self.env, notify.user_ids.ids, notify.title, notify.body, {})
            elif notify.notify_type == 'admin':
                result = send_fcm_admin(self.env, notify.user_ids.ids, notify.title, notify.body, {})
            
            # Cập nhật kết quả gửi FCM
            if result:
                notify.sudo().write({
                    'fcm_success_count': result.get('success_count', 0),
                    'fcm_failure_count': result.get('failure_count', 0),
                    'fcm_responses': json.dumps(result.get('responses', []), ensure_ascii=False)
                })
        except Exception as e:
            # Log lỗi hoặc xử lý theo ý muốn
            notify.sudo().write({
                'fcm_success_count': 0,
                'fcm_failure_count': 0,
                'fcm_responses': error.args[0] if isinstance(error, Exception) else str(error)
            })
            pass
        return notify

# Model quản lý khu ký túc xá
class StudentDormitoryArea(models.Model):
    _name = 'student.dormitory.area'
    _description = 'Khu ký túc xá'

    area_id = fields.Integer('ID khu ký túc xá', required=True)
    name = fields.Char('Tên khu', required=True)
    description = fields.Text('Mô tả khu')
    cluster_ids = fields.One2many('student.dormitory.cluster', 'area_id', string='Các cụm thuộc khu')
    
    @api.model
    def action_sync_cluster(self, vals):
        return action_sync_area_cluster(self)

# Model quản lý cụm ký túc xá
class StudentDormitoryCluster(models.Model):
    _name = 'student.dormitory.cluster'
    _description = 'Cụm ký túc xá'

    qlsv_cluster_id = fields.Integer('ID cụm ký túc xá', required=True)
    qlsv_area_id = fields.Integer('ID khu ký túc xá', required=True)
    area_id = fields.Many2one('student.dormitory.area', string='Khu ký túc xá', required=True)
    name = fields.Char('Tên cụm', required=True)
    description = fields.Text('Mô tả cụm')

    @api.model
    def action_sync_cluster(self, vals):
        return action_sync_area_cluster(self)

# Model quản lý vai trò hoạt động trong KTX
class ActivityRole(models.Model):
    _name = 'student.activity.role'
    _description = 'Vai trò hoạt động KTX'

    name = fields.Char('Tên vai trò', required=True)
    description = fields.Text('Mô tả vai trò')