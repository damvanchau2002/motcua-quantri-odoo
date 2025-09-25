import os
import json
from dateutil.relativedelta import relativedelta
import requests
from odoo import models, fields, api
from datetime import timedelta

from odoo.exceptions import UserError 
from ..controllers.service_api.utils import send_fcm_notify, send_fcm_users, send_fcm_request
from ..controllers.service_api.request_api import create_request, update_request_step

# Đồng bộ khu vực và cụm KTX
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

# Model quản lý file cần gửi kèm dịch vụ
class ServiceFile(models.Model):
    _name = 'student.service.file'
    _description = 'File cần gửi kèm dịch vụ'

    name = fields.Char('Tên file', required=True)
    attachment = fields.Char('File Attachment', required=False)
    description = fields.Text('Mô tả file')

# Định nghĩa dịch vụ
class Service(models.Model):
    _name = 'student.service'
    _description = 'Dịch vụ'

    name = fields.Char('Tên dịch vụ', required=True)
    description = fields.Text('Mô tả chi tiết', help='Mô tả chi tiết về dịch vụ này, bao gồm các thông tin cần thiết cho sinh viên')
    titlenote = fields.Char('Tiêu đề gửi nội dung yêu cầu', help='Ghi chú cho SV thông tin cần nhập như thế nào')

    duration = fields.Integer('Thời gian xử lý (giờ)', default=168, help='Thời gian dự kiến để xử lý yêu cầu dịch vụ này, tính bằng giờ')
    per_week = fields.Integer('Số lượng yêu cầu tối đa mỗi tuần', default=1, help='Số lượng yêu cầu tối đa User được phép gửi mỗi tuần')

    state = fields.Selection([
        ('enabled', 'Enabled'),
        ('disabled', 'Disabled')
    ], string='Hoạt động', default='enabled', help='Trạng thái hoạt động của dịch vụ: Đang hoạt động hay Tạm ngừng gửi yêu cầu')
    group_id = fields.Many2one('student.service.group', string='Nhóm dịch vụ')

    files = fields.Many2many('student.service.file', string='Files cần gửi kèm')

    step_ids = fields.Many2many('student.service.step',  string='Các bước duyệt')

    users = fields.Many2many('res.users', string='Người duyệt', help='Cụ thể người được phân công duyệt dịch vụ này')
    role_ids = fields.Many2many('student.activity.role', string='Chức danh được duyệt', help='Các phòng ban, chức danh, vai trò có sẽ nhận được yêu cầu từ dịch vụ này')


# Định nghĩa bước duyệt của 1 dịch vụ
class ServiceStep(models.Model):
    _name = 'student.service.step'
    _description = 'Bước duyệt dịch vụ'
    _order = 'sequence'

    name = fields.Char('Tên bước', required=True, help='Tên bước duyệt dịch vụ')
    sequence = fields.Integer('Thứ tự', default=1)
    description = fields.Text('Mô tả bước')
    nextstep = fields.Integer('Bước tiếp theo', default=99)
    state = fields.Integer('Trạng thái', default=1)  # Trạng thái bước, mặc định là 1 (có thể chỉnh sửa)

    # tạm thời chưa dùng:
    user_ids = fields.Many2many('res.users', string='Người thực hiện', help='Những người cố định được phân công thực hiện duyệt bước này')
    role_ids = fields.Many2many('student.activity.role', string='Phòng ban', help='Các phòng ban, chức danh, vai trò nhận được phân công để thực hiện duyệt bước này')
    department_id = fields.Many2one('student.activity.department', string='Phòng ban được phân công', help='Phòng ban có quyền phân công bước này')
    # / tạm thời chưa dùng

    def unlink(self):
        for step in self:
            if step.state == 0:
                raise models.ValidationError("Không thể xóa bước mặc định!")
        return super().unlink()


# Bước duyệt đầu đánh dấu các giấy tờ cần nộp
class ServiceFileCheckbox(models.Model):
    _name = 'student.service.file.checkbox'
    _description = 'File checkbox cho từng bước duyệt'

    step_id = fields.Many2one('student.service.request.step', string='Bước duyệt')
    file_id = fields.Many2one('student.service.file', string='File cần nộp')
    checked = fields.Boolean('Đã chọn', default=False)

# Lịch sử duyệt
class ServiceRequestStepHistory(models.Model):
    _name = 'student.service.request.step.history'
    _description = 'Lịch sử thao tác duyệt'
    _order = 'date desc'
    
    request_id = fields.Many2one('student.service.request', string='Yêu cầu dịch vụ')
    step_id = fields.Many2one('student.service.request.step', string='Bước duyệt')
    user_id = fields.Many2one('res.users', string='Người duyệt')
    state = fields.Selection([
        ('repairing', 'Chờ sửa chữa'),
        ('pending', 'Chờ duyệt'),
        ('assigned', 'Đã phân công'),
        ('extended', 'Đã gia hạn'),
        ('cancelled', 'Đã hủy'),
        ('ignored', 'Đã bỏ qua'),
        ('approved', 'Đã duyệt'),

        ('rejected', 'Từ chối'),
        ('closed', 'Đã đóng')
    ], string='Trạng thái', default='pending', help='Trạng thái hiện tại của bước duyệt này')
    date = fields.Datetime('Ngày thực hiện', default=fields.Datetime.now)
    note = fields.Text('Ghi chú', help='Ghi chú cho lịch sử thao tác duyệt này')

# Bước duyệt đang được thực hiện
class ServiceRequestStep(models.Model):
    _name = 'student.service.request.step'
    _description = 'Dòng duyệt từng bước'
    _order = 'base_secquence'

    # BASE
    request_id = fields.Many2one('student.service.request', string='Dịch vụ')
    base_step_id = fields.Many2one('student.service.step', string='Thông tin bước duyệt')
    base_secquence = fields.Integer('Thứ tự', related='base_step_id.sequence', help='Thứ tự của bước duyệt trong quy trình')
    activated = fields.Boolean('Đã kích hoạt', default=False)

    # TÌNH TRẠNG XỬ LÝ
    state = fields.Selection([
        ('repairing', 'Chờ sửa chữa'),
        ('pending', 'Chờ duyệt'),
        ('assigned', 'Đã phân công'),
        ('extended', 'Đã gia hạn'),
        ('ignored', 'Đã bỏ qua'),
        ('approved', 'Đã duyệt'), # Trạng thái đã duyệt: Hoàn thành xử lý yêu cầu
        ('cancelled', 'Đã hủy'),
        ('rejected', 'Từ chối'),
        ('closed', 'Đã đóng')
    ], string='Trạng thái', default='pending', help='Trạng thái hiện tại của bước duyệt này')
    approve_content = fields.Text('Nội dung duyệt', help='Nội dung duyệt cho bước này')
    approve_date = fields.Datetime('Ngày duyệt', default=fields.Datetime.now)
    upload_files = fields.Many2many('ir.attachment', string='Tài liệu đính kèm', help='Các tài liệu đính kèm cho bước này')
    final_data = fields.Text('Kết luận cuối cùng', help='Dữ liệu duyệt cuối sẽ hiển thị lên App')

    # Phân công
    assign_user_id = fields.Many2one(
        'res.users',
        string='Người được phân công',
        domain=lambda self: [('groups_id', 'in', [self.env['res.groups'].search([('name','=','Settings')], limit=1).id])],
    )
    department_id = fields.Many2one('student.activity.department', string='Phòng ban được phân công', help='Phòng ban có quyền phân công bước này')
    # Lịch sử xử lý yêu cầu
    history_ids = fields.One2many('student.service.request.step.history', 'step_id', string='Lịch sử xử lý yêu cầu', help='Lịch sử xử lý, phân công cho người xử lý hoặc thao tác xử lý')

    # Các giấy tờ cần nộp trong bước này (chỉ bước 1 mới có)
    file_ids = fields.Many2many(
        'student.service.file',
        'student_service_step_file_rel',  # bảng quan hệ riêng cho file_ids
        'step_id', 'file_id',
        string='Giấy tờ cần nộp',
        help='Các giấy tờ cần nộp trong bước này'
    )
    # Đánh dấu các giấy tờ đã nộp  (chỉ bước 1 mới có)
    file_checkbox_ids = fields.Many2many(
        'student.service.file',
        'student_service_step_file_checkbox_rel',  # bảng quan hệ riêng cho file_checkbox_ids
        'step_id', 'file_id',
        string='Hồ sơ đã nộp',
        help='Các giấy tờ đã nộp trong bước này'
    )

    def action_confirm_approve(self):
        # Nếu tạo mới:
        #if vals.get('approve_content') == self.approve_content and vals.get('assign_user_id') == self.assign_user_id.id and vals.get('state') == self.state:
        #    return super().write(vals)

        vals = update_request_step(
            self.env, 
            self.request_id.id if self.request_id.id else 0, 
            self.id, 
            self.env.user.id, 
            self.approve_content if self.approve_content else '', 
            self.state, 
            self.assign_user_id.id if self.assign_user_id else None, 
            self.file_checkbox_ids.ids, 
            self.final_data,
            self.department_id.id if self.department_id else 0
        )
        super().write(vals)
        return { 'type': 'ir.actions.client', 'tag': 'reload' }

# Model yêu cầu dịch vụ của sinh viên
class ServiceRequest(models.Model):
    _name = 'student.service.request'
    _description = 'Yêu cầu dịch vụ của sinh viên'

    # NỘI DUNG YÊU CẦU
    # Đầu vào của yêu cầu dịch vụ:
    service_id = fields.Many2one('student.service', string='Dịch vụ', required=True, help='Dịch vụ mà sinh viên yêu cầu')
    name = fields.Char('Tên yêu cầu', required=False, help='Tên yêu cầu tạo bởi: Tên sv + Tên dịch vụ')
    note = fields.Text('Ghi chú', help='Ghi chú bổ sung cho yêu cầu dịch vụ do SV nhập')
    image_attachment_ids = fields.Many2many(
        'ir.attachment',
        string='Ảnh đính kèm',
        domain=[('mimetype', 'ilike', 'image')],
        help='Ảnh đính kèm khi gửi yêu cầu dịch vụ'
        # Ảnh đính kèm Gửi theo yêu cầu dịch vụ (là các ảnh giấy tờ liên quan) 
    )

    # SINH VIÊN GỬI YÊU CẦU
    request_user_id = fields.Many2one('res.users', string='Người gửi yêu cầu', required=True, default=lambda self: self.env.user, help='Sinh viên người gửi yêu cầu dịch vụ')
    dormitory_cluster_id = fields.Many2one('student.dormitory.cluster', string='Cụm KTX', help='Cụm ký túc xá của sinh viên gửi yêu cầu dịch vụ này')
    request_user_name = fields.Char('Tên người gửi', required=False, related='request_user_id.name', help='Họ và tên của người gửi yêu cầu dịch vụ')
    request_user_avatar = fields.Binary('Ảnh đại diện', required=False, related='request_user_id.image_1920', help='Ảnh đại diện của người gửi yêu cầu dịch vụ')
    request_date = fields.Datetime('Ngày gửi', default=fields.Datetime.now, help='Ngày và giờ gửi yêu cầu dịch vụ')
    expired_date = fields.Datetime('Ngày hết hạn', default=fields.Datetime.now() + timedelta(days=7), help='Ngày và giờ hết hạn gửi yêu cầu dịch vụ')
    send_expired_warning = fields.Boolean('Đã gửi cảnh báo hết hạn', default=False, help='Đánh dấu đã gửi cảnh báo yêu cầu sắp hết hạn cho sinh viên')
    is_new = fields.Boolean('Yêu cầu mới', default=True, help='Đánh dấu yêu cầu này là mới')

    # Thông tin hủy yêu cầu
    cancel_reason = fields.Text('Lý do hủy')
    cancel_date = fields.Datetime('Ngày hủy')
    cancel_user_id = fields.Many2one('res.users', string='Người hủy')

    # THÔNG TIN CÁC BƯỚC
    # Tạo tự động theo setup Service:
    step_ids = fields.One2many('student.service.request.step', 'request_id', string='Các bước quy trình của dịch vụ này', order='sequence asc')
    
    # DUYỆT
    # Lấy user trong role_ids dồn vào đây, field users sẽ chứa tất cả người dùng có quyền duyệt, đã duyệt và sẽ duyệt dịch vụ này
    users = fields.Many2many('res.users', string='Danh sách người đã và đang duyệt', help='Người có quyền duyệt dịch vụ này')
    role_ids = fields.Many2many('student.activity.role', string='Vai trò được duyệt', help='Các vai trò có quyền duyệt dịch vụ này')
    department_ids = fields.Many2many('student.activity.department', string='Phòng ban được xử lý yêu cầu', help='Các phòng ban có quyền xử lý yêu cầu dịch vụ này')
    # Người đang xử lý yêu cầu dịch vụ này
    user_processing_id = fields.Many2one('res.users', string='Người đang xử lý', help='Người đang xử lý yêu cầu dịch vụ này')

    # TRẠNG THÁI KẾT LUẬN CUỐI
    # Trạng thái cuối cùng của yêu cầu dịch vụ
    final_state = fields.Selection([
        ('repairing', 'Chờ sửa chữa'),  # Trạng thái chờ sửa chữa (SV yêu cầu làm lại, nghiệm thu không đạt)
        ('pending', 'Chờ duyệt'),
        ('assigned', 'Đã phân công'),
        ('extended', 'Đã gia hạn'),
        ('ignored', 'Đã bỏ qua'),
        ('cancelled', 'Đã hủy'),
        ('approved', 'Đã duyệt'), 
        ('rejected', 'Từ chối'),    # Hủy bỏ yêu cầu
        ('closed', 'Đã đóng')       # Là hoàn thành và đóng
    ], string='Trạng thái duyệt', default='pending', help='Trạng thái duyệt hiện tại của yêu cầu dịch vụ này')
    final_data = fields.Text('Kết luận cuối cùng', help='Dữ liệu duyệt cuối sẽ hiển thị lên App')
    # Đánh giá cuối cùng 
    final_star = fields.Integer('Sao đánh giá cuối', help='Số sao cuối cùng sẽ hiển thị lên App') 

    # TRẠNG THÁI HIỆN TẠI
    # Thông tin duyệt mỗi bước cập nhật lên
    approve_content = fields.Text('Nội dung duyệt', help='Nội dung duyệt hiện tại cho yêu cầu dịch vụ này')
    approve_date = fields.Datetime('Ngày duyệt', default=fields.Datetime.now, help='Ngày và giờ thao tác cập nhật duyệt yêu cầu dịch vụ này')
    approve_user_id = fields.Many2one('res.users', string='Người đang nhận duyệt', help='Người đang thụ lý yêu cầu dịch vụ này')

    # PHẢN HỒI, ĐÁNH GIÁ
    acceptance = fields.Text('Phản hồi chấp nhận', help='Phản hồi của người yêu cầu về việc xử lý')
    complaint_ids = fields.One2many('student.service.request.complaint', 'request_id', string='Các khiếu nại', help='Các khiếu nại liên quan đến yêu cầu dịch vụ này')
    review_ids = fields.One2many('student.service.request.review', 'request_id', string='Các đánh giá', help='Các đánh giá liên quan đến yêu cầu dịch vụ này')

    # GHI NHẬN KẾT QUẢ
    result_ids = fields.One2many('student.service.request.result', 'request_id', string='Kết quả', help='Các kết quả liên quan đến yêu cầu dịch vụ này')

    @api.onchange('expired_date')
    def _onchange_increase_expired(self):
        """Tăng thời gian hết hạn của yêu cầu dịch vụ"""
        if self.expired_date and self.expired_date < fields.Datetime.now():
            return {
                'warning': {
                    'title': "Cảnh báo",
                    'message': "Ngày hết hạn phải lớn hơn ngày hiện tại!"
                }
            }
        self.sudo().write({
            'expired_date': self.expired_date,
            'final_state': 'extended'
        })
        send_fcm_request(self.env, self, send_type=7)  # Gửi thông báo gia hạn yêu cầu


    def action_create_new(self):
        # Tạo mới yêu cầu dịch vụ
        vals = create_request(self.env, self.service_id.id, self.id if self.id else 0, self.request_user_id.id, self.note, self.image_attachment_ids.ids)
        return { 'type': 'ir.actions.client', 'tag': 'reload' }

    @api.model
    def cron_check_timeout_requests(self):
        """Kiểm tra và cập nhật trạng thái timeout cho các request"""
        try:
            # Tìm các request đã quá thời gian xử lý
            timeout_date = fields.Datetime.now() - timedelta(days=6)
            timeout_requests = self.search([('final_state', '=', 'pending'), ('send_expired_warning', '=', False), ('request_date', '<', timeout_date)])

            for request in timeout_requests:
                # Cập nhật trạng thái timeout
                print(f"Updating request {request.id} to timeout status")
                send_fcm_request(self.env, self, 13)
                request.sudo().send_expired_warning = True


            print(f"Updated {len(timeout_requests)} requests to timeout status")
            
        except Exception as e:
            print(f"Error in cron_check_timeout_requests: {str(e)}")
    
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
    title_name = fields.Char('Mô tả tài khoản', help='Chức danh, khu vực quản lý của quản trị viên sinh viên')
    activated = fields.Boolean('Đã kích hoạt', default=False, help='Trạng thái kích hoạt tài khoản quản trị viên sinh viên')
    dormitory_area_id = fields.Many2one('student.dormitory.area', string='Khu ký túc xá')
    #dormitory_cluster_id = fields.Many2one('student.dormitory.cluster', string='Cụm ký túc xá')
    dormitory_clusters = fields.Many2many('student.dormitory.cluster', string='Cụm KTX quản lý', help='Các cụm ký túc xá mà quản trị viên này quản lý')

    # Thông tin vai trò:
    specialization = fields.Text('Chuyên môn', default='Chưa khai báo', required=False, help='Ghi chú thêm về chuyên môn hoặc khu vực quản lý của quản trị của người này')
    role_ids = fields.Many2many('student.activity.role', string='Nhóm chức danh', help='Các vai trò hoạt động của quản trị viên')
    # Thông tin phòng ban:
    department_id = fields.Many2one('student.activity.department', string='Phòng ban', help='Phòng ban của quản trị viên sinh viên')

# Model quản lý vai trò hoạt động trong KTX
class ActivityRole(models.Model):
    _name = 'student.activity.role'
    _description = 'Vai trò hoạt động KTX'

    name = fields.Char('Tên vai trò', required=True)
    description = fields.Text('Mô tả vai trò')
    level = fields.Selection([
        ('1', 'Tiếp nhận'),
        ('9', 'Trưởng nhóm'),
        ('3', 'Chuyên viên')
    ], string='Cấp bậc', required=False, default='3')


class ActivityDepartment(models.Model):
    _name = 'student.activity.department'
    _description = 'Phòng ban hoạt động KTX'

    name = fields.Char('Tên phòng ban', required=True)
    description = fields.Text('Mô tả phòng ban')
    admin_profiles = fields.One2many('student.admin.profile', 'department_id', string='Thành viên của Phòng ban')
    cluster_ids = fields.Many2many('student.dormitory.cluster', string='Cụm KTX', help='Các cụm KTX thuộc phòng ban này')


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
    body = fields.Text('Nội dung tóm tắt', required=True)
    image = fields.Char('URL hình ảnh', required=False, help='URL hình ảnh đại diện cho thông báo, có thể là link đến ảnh trên internet')
    article = fields.Text('Nội dung chi tiết', required=False, help='Nội dung chi tiết của thông báo, có thể chứa HTML hoặc Markdown')
    created_date = fields.Datetime('Ngày tạo', default=fields.Datetime.now)
    data = fields.Text('Dữ liệu bổ sung', help='Dữ liệu JSON hoặc thông tin bổ sung cho thông báo')
    notify_type = fields.Selection([
        ('users', 'Thông báo xử lý nghiệp vụ đến người dùng'),
        ('articles', 'Thông báo dạng bài viết'),
    ], string='Loại thông báo', default='articles', help='Loại thông báo')
    # Đánh dấu đã xem:
    read_user_ids = fields.Many2many('res.users', 'student_notify_read_user_rel', 'notify_id', 'user_id', string='Người đã đọc', help='Danh sách người dùng đã đọc thông báo')
    
    #Nhận notify theo user, cluster, activity
    user_ids = fields.Many2many('res.users', 'student_notify_user_rel', 'notify_id', 'user_id',  string='Danh sách người nhận notify', help='Danh sách người sẽ nhận thông báo')
    dormitory_cluster_ids = fields.Many2many('student.dormitory.cluster', string='Cụm nhận notify', help='Gửi thông báo đến các SV trong các cụm KTX này')
    activity_role_ids = fields.Many2many('student.activity.role', string='Vai trò nhận notify', help='Gửi thông báo đến các SV có vai trò hoạt động này')

    # Thống kê kết quả gửi FCM
    user_id = fields.Many2one('res.users', string='Người gửi', help='Người gửi thông báo')
    fcm_success_count = fields.Integer('Số lượng gửi thành công', default=0)
    fcm_failure_count = fields.Integer('Số lượng gửi thất bại', default=0)
    fcm_responses = fields.Text('Kết quả gửi FCM', help='Lưu JSON kết quả gửi FCM')

    def send_fcm(self):
        try:
            dt = { 'type': 'article', 'id': f'{self.id}' }
            result = send_fcm_notify(self.env, self, dt)
            # Cập nhật kết quả gửi FCM
            if result:
                self.sudo().write({
                    'data': json.dumps(dt, ensure_ascii=False),
                    'fcm_success_count': result.fcm_success_count,
                    'fcm_failure_count': result.fcm_failure_count,
                    'fcm_responses': result.fcm_responses
                })
        except Exception as e:
            # Log lỗi hoặc xử lý theo ý muốn
            self.sudo().write({
                'fcm_success_count': 0,
                'fcm_failure_count': 0,
                'fcm_responses': e.args[0] if isinstance(e, Exception) else str(e)
            })
            raise models.ValidationError("Gửi thông báo FCM thất bại: %s" % str(e))
        return self

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


# Model lịch sử nghiệm thu yêu cầu
class StudentServiceRequestResult(models.Model):
    _name = 'student.service.request.result'
    _description = 'Lịch sử nghiệm thu yêu cầu dịch vụ'

    # Thông tin yêu cầu
    request_id = fields.Many2one('student.service.request', string='Yêu cầu dịch vụ', required=True)
    user_id = fields.Many2one('res.users', string='Người gửi yêu cầu', required=True)

    # Thông tin người đóng góp
    acceptance_ids = fields.Many2many('res.users', string='Người đóng góp')

    action = fields.Selection([
        ('issue', 'Cần sửa lại'),   # Cần sửa lại
        ('accept', 'Chấp nhận'),    # Hoàn thành
        ('reject', 'Từ chối'),      # Không hoàn thành
    ], string='Hành động', required=True)
    timestamp = fields.Datetime('Thời gian', default=fields.Datetime.now)
    note = fields.Text('Ghi chú', help='Ghi chú về hành động thực hiện trên yêu cầu dịch vụ này')
    star = fields.Integer('Sao đánh giá', help='Số sao đánh giá cho yêu cầu dịch vụ này')
    image_ids = fields.Many2many(
        'ir.attachment',
        'student_service_request_result_image_rel',
        'complaint_id',
        'attachment_id',
        string='Complaint Images',
        help='Upload and attach multiple images to this complaint'
    )
    # Thông tin người thực hiện hành động
    action_user = fields.Many2one('res.users', string='Người thực hiện hành động', required=True)

class StudentServiceReportWizard(models.TransientModel):
    _name = "student.service.report.wizard"
    _description = "Báo cáo"

    mode = fields.Selection([
        ('day', 'Ngày'),
        ('month', 'Tháng'),
        ('year', 'Năm')
    ], string="Chế độ", default='month', required=True)

    from_date = fields.Date(string="Từ ngày")
    to_date = fields.Date(string="Đến ngày")

    from_month = fields.Char(string="Từ tháng")
    to_month = fields.Char(string="Đến tháng")

    from_year = fields.Integer(string="Từ năm")
    to_year = fields.Integer(string="Đến năm")

    @api.onchange('mode')
    def _onchange_mode(self):
        self.from_date = self.to_date = False
        self.from_month = self.to_month = False
        self.from_year = self.to_year = False

    def _get_report_title(self):
        if self.mode == 'day':
            return f"Báo cáo thống kê số lượng yêu cầu theo Ngày (Từ {self.from_date} đến {self.to_date})"
        elif self.mode == 'month':
            return f"Báo cáo thống kê số lượng yêu cầu theo Tháng (Từ {self.from_month} đến {self.to_month})"
        elif self.mode == 'year':
            return f"Báo cáo thống kê số lượng yêu cầu theo Năm (Từ {self.from_year} đến {self.to_year})"
        return "Báo cáo"

    def action_generate_report(self):
        self.ensure_one()
        params = {"mode": self.mode}
        where_clause = ""

        # --- DAY ---
        if self.mode == 'day':
            if not (self.from_date and self.to_date):
                raise UserError("Vui lòng nhập khoảng từ ngày đến ngày.")

            # cộng thêm 1 ngày để lọc đến 23:59:59
            to_date_plus = self.to_date + relativedelta(days=1)

            where_clause = """
                WHERE r.request_date >= %(from_date)s
                  AND r.request_date < %(to_date_plus)s
            """
            params.update({
                "from_date": self.from_date,
                "to_date_plus": to_date_plus
            })

        # --- MONTH ---
        elif self.mode == 'month':
            if not (self.from_month and self.to_month):
                raise UserError("Vui lòng nhập khoảng từ tháng đến tháng.")

            # where_clause dùng TO_DATE để convert 'MM/YYYY' -> date
            where_clause = """
                WHERE r.request_date >= DATE_TRUNC('month', TO_DATE(%(from_month)s, 'MM/YYYY'))
                AND r.request_date < DATE_TRUNC('month', TO_DATE(%(to_month)s, 'MM/YYYY') + INTERVAL '1 month')
            """

            params.update({
                "from_month": self.from_month,   # dạng '09/2025'
                "to_month": self.to_month,       # dạng '12/2025'
            })

        # --- YEAR ---
        elif self.mode == 'year':
            if not (self.from_year and self.to_year):
                raise UserError("Vui lòng nhập khoảng từ năm đến năm.")

            to_year_plus = self.to_year + 1

            where_clause = """
                WHERE r.request_date >= MAKE_DATE(%(from_year)s, 1, 1)
                  AND r.request_date < MAKE_DATE(%(to_year_plus)s, 1, 1)
            """
            params.update({
                "from_year": self.from_year,
                "to_year_plus": to_year_plus
            })

        query = f"""
            SELECT 
                a.name AS area_name,
                cl.name AS cluster_name,
                s.name AS service_name,
                g.name AS group_name,
                CASE 
                    WHEN %(mode)s = 'day'   THEN TO_CHAR(r.request_date, 'DD/MM/YYYY')
                    WHEN %(mode)s = 'month' THEN TO_CHAR(r.request_date, 'MM/YYYY')
                    WHEN %(mode)s = 'year'  THEN TO_CHAR(r.request_date, 'YYYY')
                END AS period,
                MIN(r.request_date)::date AS min_request_date,
                COUNT(r.id) AS total_requests,
                COUNT(CASE WHEN r.final_state NOT IN ('pending','assigned') THEN 1 END) AS processed_requests,
                COUNT(CASE WHEN r.final_state IN ('pending','assigned') THEN 1 END) AS pending_requests,
                COUNT(DISTINCT CASE 
                        WHEN r.expired_date < NOW() 
                            AND r.final_state IN ('pending','assigned') 
                        THEN r.id 
                    END) AS overdue_requests
            FROM student_service_request r
            JOIN student_dormitory_cluster cl ON r.dormitory_cluster_id = cl.id
            JOIN student_dormitory_area a     ON cl.area_id = a.id
            JOIN student_service s            ON r.service_id = s.id
            JOIN student_service_group g      ON s.group_id = g.id
            {where_clause}
            GROUP BY a.id, a.name, cl.id, cl.name, g.id, g.name, s.id, 
                CASE 
                    WHEN %(mode)s = 'day'   THEN TO_CHAR(r.request_date, 'DD/MM/YYYY')
                    WHEN %(mode)s = 'month' THEN TO_CHAR(r.request_date, 'MM/YYYY')
                    WHEN %(mode)s = 'year'  THEN TO_CHAR(r.request_date, 'YYYY')
                END
            ORDER BY period DESC, group_name,service_name
        """
        self.env.cr.execute(query, params)
        rows = self.env.cr.dictfetchall()

        # Xóa dữ liệu cũ
        self.env['student.service.report'].search([]).unlink()

        # Biến tổng
        total_requests = 0
        total_processed = 0
        total_pending = 0
        total_overdue = 0

        for row in rows:
            row.pop("min_request_date", None)
            total_requests += row.get("total_requests", 0)
            total_processed += row.get("processed_requests", 0)
            total_pending += row.get("pending_requests", 0)
            total_overdue += row.get("overdue_requests", 0)
            self.env['student.service.report'].create(row)

        # Thêm dòng tổng cộng
        if rows:
            percent = (total_processed * 100.0 / total_requests) if total_requests else 0.0
            self.env['student.service.report'].create({
                "period": "Tổng cộng",
                "area_name": "",
                "cluster_name": "",
                "group_name": "",
                "service_name": "",
                "total_requests": total_requests,
                "processed_requests": total_processed,
                "pending_requests": total_pending,
                "overdue_requests": total_overdue,
                "processed_percent": percent,
            })

        return {
            'type': 'ir.actions.act_window',
            'name': 'Báo cáo',
            'res_model': 'student.service.report',
            'view_mode': 'list',
            'target': 'current',
            'context': {
                'report_title': self._get_report_title(),
            }
        }

class StudentServiceReport(models.Model): 
    _name = "student.service.report" 
    _description = "Báo cáo" 
    _rec_name = "period" 
    _auto = False
    # Model báo cáo không có bảng thật 
    report_title = fields.Char( string="Tiêu đề báo cáo", compute="_compute_report_title", store=False ) 
    period = fields.Char(string='Ngày/Tháng/Năm') 
    area_name = fields.Char(string='Khu ký túc xá') 
    cluster_name = fields.Char(string='Cụm') 
    group_name = fields.Char(string='Nhóm') 
    service_name = fields.Char(string='Dịch vụ') 
    total_requests = fields.Integer(string='Tổng yêu cầu') 
    processed_requests = fields.Integer(string='Đã xử lý') 
    pending_requests = fields.Integer(string='Chưa xử lý') 
    overdue_requests = fields.Integer(string='Quá hạn') 
    processed_percent = fields.Float( string='% Xử lý', compute="_compute_processed_percent", store=False ) 
    @api.depends('processed_requests', 'total_requests') 
    def _compute_processed_percent(self): 
        for rec in self: 
            if rec.total_requests: 
                rec.processed_percent = rec.processed_requests * 100.0 / rec.total_requests 
            else: 
                rec.processed_percent = 0.0