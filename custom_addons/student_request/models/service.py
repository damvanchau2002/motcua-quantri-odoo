import base64
import logging
from datetime import datetime
import os
import json
from dateutil.relativedelta import relativedelta
import requests
from odoo import models, fields, api
from datetime import timedelta
import requests as py_requests

from odoo.exceptions import UserError, ValidationError, AccessError
from odoo.http import request 
from ..controllers.service_api.utils import add_user_to_firebase_topic, convert_date, remove_user_from_all_firebase_topics, send_fcm_notify, send_fcm_users, send_fcm_request
from ..controllers.service_api.request_api import create_request, update_request_step

# Logger cho module
_logger = logging.getLogger(__name__)

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

    def action_back(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Nhóm dịch vụ',
            'res_model': 'student.service.group',
            'view_mode': 'list',
            'target': 'current',
        }

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
    group_id = fields.Many2one('student.service.group', string='Nhóm dịch vụ', ondelete='cascade')

    files = fields.Many2many('student.service.file', string='Files cần gửi kèm')

    step_ids = fields.Many2many('student.service.step',  string='Các bước duyệt')
    step_selection_ids = fields.One2many('student.service.step.selection', 'service_id', string='Thông tin duyệt dịch vụ', help='Các bước duyệt với thứ tự tùy chỉnh')

    users = fields.Many2many('res.users', string='Người duyệt', help='Cụ thể người được phân công duyệt dịch vụ này')
    role_ids = fields.Many2many('student.activity.role', string='Chức danh được duyệt', help='Các phòng ban, chức danh, vai trò có sẽ nhận được yêu cầu từ dịch vụ này')
    
    form_field_ids = fields.One2many(
        'student.service.form.field',
        'service_id',
        string='Form Fields',
        help='Các trường thông tin sẽ hiển thị trong form tạo yêu cầu'
    )
    form_field_count = fields.Integer(
        string='Số fields',
        compute='_compute_form_field_count', 
        store=False
    )
    @api.depends('form_field_ids')
    def _compute_form_field_count(self):
        for rec in self:
            rec.form_field_count = len(rec.form_field_ids)
    @api.model
    def get_group_system_id(self):
        return self.env.ref('base.group_system').id

    @api.constrains('step_selection_ids')
    def _check_step_selection_ids_required(self):
        for rec in self:
            # Chỉ kiểm tra constraint khi record đã được tạo và có ID
            if rec.id and not rec.step_selection_ids:
                raise ValidationError('Vui lòng thêm ít nhất một bước duyệt cho dịch vụ.')

    def write(self, vals):
        _logger.info(f"Service write called with vals: {vals}")
        
        if 'step_selection_ids' in vals:
            _logger.info(f"step_selection_ids being updated: {vals['step_selection_ids']}")
        
        try:
            result = super().write(vals)
            _logger.info(f"Service write completed successfully")
            return result
        except Exception as e:
            _logger.error(f"Error in Service write: {str(e)}")
            raise

    def read(self, fields=None, load='_classic_read'):
        _logger.info(f"Service read called for IDs: {self.ids}, fields: {fields}")
        result = super().read(fields, load)
        
        # Log step_selection_ids data if it's being read
        if not fields or 'step_selection_ids' in fields:
            for record in result:
                if 'step_selection_ids' in record:
                    _logger.info(f"Service ID {record.get('id')}: step_selection_ids = {record['step_selection_ids']}")
        
        return result

    # Giữ lại constraint cũ để tương thích ngược
    @api.constrains('step_ids')
    def _check_step_ids_required(self):
        for rec in self:
            if not rec.step_ids and not rec.step_selection_ids:
                raise ValidationError('Vui lòng thêm ít nhất một bước duyệt cho dịch vụ.')


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

    def name_get(self):
        """Hiển thị nhãn có STT: 'Bước <sequence>: <name>'"""
        result = []
        for record in self:
            seq = record.sequence or 0
            base = record.name or ''
            result.append((record.id, f"Bước {seq}: {base}" if base else f"Bước {seq}"))
        return result

    def action_back(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Bước duyệt dịch vụ',
            'res_model': 'student.service.step',
            'view_mode': 'list',
            'target': 'current',
        }

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
    step_id = fields.Many2one('student.service.request.step', string='Bước duyệt', ondelete='cascade')
    user_id = fields.Many2one('res.users', string='Người duyệt', ondelete='cascade')
    state = fields.Selection([
        ('repairing', 'Chờ sửa chữa'),
        ('pending', 'Chờ duyệt'),
        ('assigned', 'Đã phân công'),
        ('extended', 'Đã gia hạn'),
        ('cancelled', 'Đã hủy'),
        ('ignored', 'Đã bỏ qua'),
        ('approved', 'Đã duyệt'),
        ('rejected', 'Từ chối'),
        ('adjust_profile', 'Điều chỉnh hồ sơ'),
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
    request_id = fields.Many2one('student.service.request', string='Dịch vụ', ondelete='cascade')
    # Liên kết bản ghi lựa chọn bước duyệt theo dịch vụ
    selection_id = fields.Many2one(
        'student.service.step.selection',
        string='Bước duyệt (theo dịch vụ)',
        compute='_compute_selection_id',
        store=False,
        readonly=True
    )
    # Giữ tương thích: lấy bước gốc từ selection_id.step_id
    base_step_id = fields.Many2one(
        'student.service.step',
        string='Thông tin bước duyệt',
        ondelete='set null'
    )
    # Thứ tự lấy theo cấu hình selection
    base_secquence = fields.Integer(
        'Thứ tự',
        related='selection_id.sequence',
        help='Thứ tự của bước duyệt trong quy trình',
        readonly=True,
        store=True
    )
    activated = fields.Boolean('Đã kích hoạt', default=False)

    # Hiển thị các bước duyệt cấu hình theo dịch vụ của yêu cầu hiện tại
    # Liên kết trực tiếp từ request_id.service_step_selection_ids để dùng trong form bước duyệt
    step_selection_ids = fields.Many2many(
        related='request_id.service_step_selection_ids',
        string='Các bước duyệt (theo dịch vụ)',
        readonly=True
    )

    # Tên bước hiển thị theo cấu hình dịch vụ
    display_step_name = fields.Char(
        string='Tên bước hiển thị',
        compute='_compute_display_step_name',
        store=False,
        readonly=True
    )

    @api.depends('selection_id', 'base_step_id', 'request_id.service_step_selection_ids')
    def _compute_display_step_name(self):
        for rec in self:
            # Ưu tiên tên theo selection của chính dòng bước này
            name = ''
            if rec.selection_id:
                name = rec.selection_id.name or rec.selection_id.step_name or ''
            # Fallback theo bước gốc nếu selection chưa xác định
            if not name:
                name = rec.base_step_id.name if rec.base_step_id else ''
            rec.display_step_name = name

    @api.depends('request_id.service_step_selection_ids', 'request_id.step_ids', 'base_step_id')
    def _compute_selection_id(self):
        for rec in self:
            selection = False
            if rec.request_id:
                # Lấy danh sách selection theo thứ tự cấu hình
                selections = rec.request_id.service_step_selection_ids.sorted(lambda s: s.sequence)
                # Lấy danh sách các bước của request theo thứ tự tạo (id tăng dần)
                steps = rec.request_id.step_ids.sorted(lambda s: s.id)

                # Ánh xạ theo vị trí tạo: index của rec trong steps -> selection cùng index
                try:
                    idx = steps.ids.index(rec.id)
                    if idx < len(selections):
                        selection = selections[idx]
                except ValueError:
                    selection = False

                # Fallback: nếu không xác định theo vị trí, map theo step_id với sequence nhỏ nhất
                if not selection and rec.base_step_id:
                    matched = selections.filtered(lambda s: s.step_id.id == rec.base_step_id.id)
                    if matched:
                        selection = matched.sorted(lambda s: s.sequence)[0]

            rec.selection_id = selection

    # TÌNH TRẠNG XỬ LÝ
    state = fields.Selection([
        ('repairing', 'Chờ sửa chữa'),
        ('pending', 'Chờ duyệt'),
        ('assigned', 'Đã phân công'),
        ('extended', 'Đã gia hạn'),
        ('ignored', 'Đã bỏ qua'),
        ('approved', 'Đã duyệt'), # Trạng thái đã duyệt: Hoàn thành xử lý yêu cầu
        ('rejected', 'Từ chối'),
        ('adjust_profile', 'Điều chỉnh hồ sơ'), # Trạng thái yêu cầu sinh viên điều chỉnh hồ sơ
        ('cancelled', 'Đã hủy'),
        ('closed', 'Đã đóng')
    ], string='Trạng thái', default='pending', help='Trạng thái hiện tại của bước duyệt này')
    approve_content = fields.Text('Nội dung duyệt', help='Nội dung duyệt cho bước này')
    approve_date = fields.Datetime('Ngày duyệt', default=fields.Datetime.now)
    upload_files = fields.Many2many('ir.attachment', string='Tài liệu đính kèm', help='Các tài liệu đính kèm cho bước này')
    final_data = fields.Text('Kết luận cuối cùng', help='Dữ liệu duyệt cuối sẽ hiển thị lên App')

    # Phân công
    assign_user_id = fields.Many2one('res.users', string='Người được phân công', help='Người đã được phân công tiêp theo để xử lý bước này')
    allowed_user_ids = fields.Many2many('res.users', compute='_compute_allowed_users')
    def _compute_allowed_users(self):
        users = self.env['student.admin.profile'].search([]).mapped('user_id')
        for record in self:
            record.allowed_user_ids = [(6, 0, users.ids)]

    department_id = fields.Many2one('student.activity.department', string='Phòng ban được phân công', help='Phòng ban có quyền phân công bước này')
    
    @api.onchange('assign_user_id')
    def _onchange_assign_user_id(self):
        """Tự động chọn phòng ban khi chọn người được phân công"""
        if self.assign_user_id:
            # Tìm admin profile của user được chọn
            admin_profile = self.env['student.admin.profile'].sudo().search([
                ('user_id', '=', self.assign_user_id.id),
                ('activated', '=', True)
            ], limit=1)
            
            if admin_profile and admin_profile.department_id:
                self.department_id = admin_profile.department_id
            else:
                # Nếu không tìm thấy phòng ban, xóa department_id
                self.department_id = False
        else:
            # Nếu không chọn user, xóa department_id
            self.department_id = False
    
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

    disabled = fields.Boolean(
        string="Disabled",
        compute="_compute_disabled",
        store=False,
        help="Các bước sau bước 'pending' đầu tiên sẽ bị khóa"
    )

    @api.depends("state", "request_id.step_ids.state")
    def _compute_disabled(self):
        for rec in self:
            rec.disabled = True  # mặc định khóa

            if not rec.request_id:
                continue

            # Lấy tất cả step trong request, sort theo thứ tự đã cấu hình (selection.sequence)
            steps = rec.request_id.step_ids.sorted(lambda s: s.base_secquence or 0)

            # Tìm step ngay trước step hiện tại theo thứ tự cấu hình
            prev_steps = steps.filtered(
                lambda s: (s.base_secquence or 0) < (rec.base_secquence or 0)
            )

            if not prev_steps:
                # Nếu không có step trước → step đầu tiên luôn mở
                rec.disabled = False
                continue

            # Lấy step liền kề trước nó
            prev_step = prev_steps[-1]

            # Nếu step trước là approved thì mở step hiện tại
            if prev_step.state == "approved":
                rec.disabled = False


    def action_back(self):
        return {
            'type': 'ir.actions.act_window_close',
        }

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
        
        # Gửi thông báo khi trạng thái là "Điều chỉnh hồ sơ"
        if self.state == 'adjust_profile' and self.request_id and self.request_id.request_user_id:
            # Tạo thông báo cho sinh viên
            self.env['student.notify'].sudo().create({
                'title': 'Yêu cầu điều chỉnh hồ sơ',
                'body': f'Yêu cầu dịch vụ "{self.request_id.name}" cần được điều chỉnh hồ sơ. Vui lòng kiểm tra và cập nhật.',
                'notify_type': 'users',
                'user_ids': [(4, self.request_id.request_user_id.id)],
                'data': f'{{"request_id": {self.request_id.id}, "step_id": {self.id}}}'
            })
            
        super().write(vals)
        return { 'type': 'ir.actions.client', 'tag': 'reload' }

# Model yêu cầu dịch vụ của sinh viên
class ServiceRequest(models.Model):
    _name = 'student.service.request'
    _description = 'Yêu cầu dịch vụ của sinh viên'
    _inherit = ['mail.thread']

    def _format_dt_for_user(self, dt, user_id=None, fmt='%d/%m/%Y %H:%M'):
        """Định dạng datetime theo múi giờ người nhận email.

        Ưu tiên dùng util `format_datetime_local` nếu có, fallback về
        `context_timestamp` rồi tới `strftime` mặc định.
        """
        if not dt:
            return ''
        try:
            from odoo.addons.student_request.controllers.service_api.utils import format_datetime_local
            text = format_datetime_local(dt, user_id=user_id)
            if text:
                return text
        except Exception:
            pass
        try:
            local_dt = fields.Datetime.context_timestamp(self, dt)
            if local_dt:
                return local_dt.strftime(fmt)
        except Exception:
            pass
        try:
            return dt.strftime(fmt)
        except Exception:
            return str(dt)
    
    def check_access_rule(self, operation):
        """Cho phép tất cả users truy cập service requests.
        Tránh lỗi 'Access Denied by record rules' khi xem yêu cầu."""
        return None

    # NỘI DUNG YÊU CẦU
    # Đầu vào của yêu cầu dịch vụ:
    service_id = fields.Many2one('student.service', string='Dịch vụ', required=True, help='Dịch vụ mà sinh viên yêu cầu')
    # Các bước duyệt hiển thị theo dịch vụ của yêu cầu hiện tại
    # Liên kết trực tiếp từ service_id.step_selection_ids để dùng ở form bước duyệt
    service_step_selection_ids = fields.Many2many(
        'student.service.step.selection',
        string='Các bước duyệt (theo dịch vụ)',
        compute='_compute_service_step_selection_ids',
        store=False,
        readonly=True
    )
    name = fields.Char('Tên yêu cầu', required=False, help='Tên yêu cầu tạo bởi: Tên sv + Tên dịch vụ')
    note = fields.Text('Ghi chú', help='Ghi chú bổ sung cho yêu cầu dịch vụ do SV nhập')
    image_attachment_ids = fields.Many2many(
        'ir.attachment',
        string='Ảnh đính kèm',
        domain=[('mimetype', 'ilike', 'image')],
        help='Ảnh đính kèm khi gửi yêu cầu dịch vụ',
        # Ảnh đính kèm Gửi theo yêu cầu dịch vụ (là các ảnh giấy tờ liên quan) 
        ondelete='cascade'
    )
    input_ids = fields.One2many(
        'student.service.request.input',
        'request_id',
        string='Thông tin chi tiết',
        help='Bảng nhập liệu động'
    )
    
    custom_data = fields.Text(
        string='Dữ liệu form',
        compute='_compute_custom_data',
        inverse='_inverse_custom_data',
        store=True,
        help='JSON chứa dữ liệu các trường custom (auto-sync với input_ids)'
    )
    
    @api.onchange('service_id')
    def _onchange_service_id_for_inputs(self):
        """Initialize inputs when service is selected"""
        if not self.service_id:
            self.input_ids = [(5, 0, 0)]
            return
        
        new_inputs = [(5, 0, 0)]
        for field in self.service_id.form_field_ids:
            new_inputs.append((0, 0, {
                'service_form_field_id': field.id,
                # Copy all values directly (onchange won't fire for command created records)
                'sequence': field.sequence,
                'name': field.name,
                'label': field.label,
                'field_type': field.field_type,
                'required': field.required,
                'placeholder': field.placeholder,
                'selection_options': field.options,
            }))
        self.input_ids = new_inputs
    
    @api.depends('input_ids.value_char', 'input_ids.value_text', 
                 'input_ids.value_integer', 'input_ids.value_float', 
                 'input_ids.value_date', 'input_ids.value_datetime', 
                 'input_ids.value_boolean', 'input_ids.value_selection')
    def _compute_custom_data(self):
        """Compute JSON from input_ids"""
        import json
        for rec in self:
            data = {}
            for input_rec in rec.input_ids:
                key = input_rec.name
                if not key:
                    continue
                    
                val = None
                # Map field_type from ServiceFormField
                if input_rec.field_type == 'text':
                    val = input_rec.value_char
                elif input_rec.field_type == 'textarea':
                    val = input_rec.value_text
                elif input_rec.field_type == 'number':
                    val = input_rec.value_float
                elif input_rec.field_type == 'date':
                    val = str(input_rec.value_date) if input_rec.value_date else None
                elif input_rec.field_type == 'checkbox':
                    val = input_rec.value_boolean
                elif input_rec.field_type == 'select':
                    val = input_rec.value_selection
                    
                if val is not None and val != False and val != '':
                    data[key] = val
            
            rec.custom_data = json.dumps(data, ensure_ascii=False) if data else '{}'
    
    def _inverse_custom_data(self):
        """Populate input_ids from JSON (backward compatibility)"""
        import json
        for rec in self:
            if not rec.custom_data:
                continue
                
            try:
                data = json.loads(rec.custom_data)
                for input_rec in rec.input_ids:
                    key = input_rec.name
                    if key in data:
                        val = data[key]
                        if input_rec.field_type == 'text':
                            input_rec.value_char = val
                        elif input_rec.field_type == 'textarea':
                            input_rec.value_text = val
                        elif input_rec.field_type == 'number':
                            input_rec.value_float = float(val) if val else 0.0
                        elif input_rec.field_type == 'date':
                            input_rec.value_date = val if isinstance(val, str) else False
                        elif input_rec.field_type == 'checkbox':
                            input_rec.value_boolean = bool(val)
                        elif input_rec.field_type == 'select':
                            input_rec.value_selection = val
            except Exception as e:
                _logger.warning(f"Error parsing custom_data: {e}")
    
    @api.constrains('input_ids')
    def _validate_inputs(self):
        """Validate required fields in input table"""
        from odoo.exceptions import ValidationError
        for rec in self:
            for input_rec in rec.input_ids:
                if input_rec.required:
                    has_value = False
                    if input_rec.field_type == 'text':
                        has_value = bool(input_rec.value_char)
                    elif input_rec.field_type == 'textarea':
                        has_value = bool(input_rec.value_text)
                    elif input_rec.field_type in ['number', 'checkbox']:
                        has_value = True  # 0, False are valid
                    elif input_rec.field_type == 'date':
                        has_value = bool(input_rec.value_date)
                    elif input_rec.field_type == 'select':
                        # Check both selected_option_ids (web form) and value_selection (API)
                        has_value = bool(input_rec.selected_option_ids) or bool(input_rec.value_selection)  
                    
                    if not has_value:
                        raise ValidationError(f'Trường "{input_rec.label}" là bắt buộc!')
    @api.constrains('custom_data', 'service_id')
    def _validate_custom_data(self):
        """Validate required fields (legacy - now using _validate_inputs)"""
        # Keep for backward compatibility but validation moved to _validate_inputs
        pass
    @api.depends('service_id', 'service_id.step_selection_ids')
    def _compute_service_step_selection_ids(self):
        for rec in self:
            rec.service_step_selection_ids = rec.service_id.step_selection_ids

    # SINH VIÊN GỬI YÊU CẦU
    request_user_id = fields.Many2one('res.users', string='Người gửi yêu cầu', required=True, default=lambda self: self.env.user, help='Sinh viên người gửi yêu cầu dịch vụ', ondelete='cascade')
    # Danh sách người dùng thuộc nhóm Sinh viên để dùng domain chọn người gửi
    student_user_ids = fields.Many2many('res.users', compute='_compute_student_user_ids', string='Sinh viên hệ thống', store=False)

    def _compute_student_user_ids(self):
        Profiles = self.env['student.user.profile'].sudo()
        Users = self.env['res.users'].sudo()
        profiles = Profiles.search([])
        # Tự động liên kết res.users cho các hồ sơ chưa có user_id nếu có CCCD/Email/SĐT
        for p in profiles.filtered(lambda p: not p.user_id and (p.id_card_number or p.email or p.phone)):
            login = p.id_card_number or p.email or p.phone
            user = Users.search([('login', '=', login)], limit=1) if login else Users.browse()
            if not user:
                display_name = login or f"Sinh viên #{p.id}"
                user = Users.create({'name': display_name, 'login': login or f'student_profile_{p.id}', 'active': True})
            p.write({'user_id': user.id})
        # Lấy user thuộc nhóm quyền Sinh viên
        group = self.env.ref('student_request.group_student_request_user', raise_if_not_found=False)
        group_users = group.users.sudo() if group else Users.browse()
        # Hợp nhất và chỉ lấy user đang active (bao gồm user từ hồ sơ)
        profiles_users = profiles.mapped('user_id')
        users = (profiles_users | group_users).filtered(lambda u: u.active)
        for rec in self:
            # Gán recordset trực tiếp để đảm bảo domain xử lý đúng
            rec.student_user_ids = users

    dormitory_cluster_id = fields.Many2one('student.dormitory.cluster', string='Cụm KTX', help='Cụm ký túc xá của sinh viên gửi yêu cầu dịch vụ này', )
    request_user_name = fields.Char('Tên người gửi', required=False, related='request_user_id.name', help='Họ và tên của người gửi yêu cầu dịch vụ')
    request_user_avatar = fields.Binary('Ảnh đại diện', required=False, related='request_user_id.image_1920', help='Ảnh đại diện của người gửi yêu cầu dịch vụ')
    request_user_phone = fields.Char('Số điện thoại', compute='_compute_user_profile_info', store=True, help='Số điện thoại của sinh viên gửi yêu cầu')
    request_user_dormitory_full = fields.Char('Ký túc xá', compute='_compute_user_profile_info', store=True, help='Thông tin ký túc xá đầy đủ của sinh viên')
    request_user_dormitory_house = fields.Char('Nhà ký túc xá', compute='_compute_user_profile_info', store=True, help='Tên nhà ký túc xá của sinh viên')
    request_user_dormitory_room = fields.Char('Phòng ký túc xá', compute='_compute_user_profile_info', store=True, help='Phòng ký túc xá của sinh viên')
    request_date = fields.Datetime('Ngày gửi', default=fields.Datetime.now, help='Ngày và giờ gửi yêu cầu dịch vụ')
    expired_date = fields.Datetime('Ngày hết hạn', default=fields.Datetime.now() + timedelta(days=7), help='Ngày và giờ hết hạn gửi yêu cầu dịch vụ')
    send_expired_warning = fields.Boolean('Đã gửi cảnh báo sắp hết hạn', default=False, help='Đánh dấu đã gửi cảnh báo yêu cầu sắp hết hạn cho sinh viên')
    is_new = fields.Boolean('Yêu cầu mới', default=True, help='Đánh dấu yêu cầu này là mới')

    # Thông tin hủy yêu cầu
    cancel_reason = fields.Text('Lý do hủy')
    cancel_date = fields.Datetime('Ngày hủy')
    cancel_user_id = fields.Many2one('res.users', string='Người hủy')

    # THÔNG TIN CÁC BƯỚC
    # Tạo tự động theo setup Service:
    # Bao gồm đầy đủ các bước (cả đang khóa/mở) để đảm bảo logic thứ tự và ánh xạ chính xác
    step_ids = fields.One2many(
        'student.service.request.step',
        'request_id',
        string='Các bước quy trình của dịch vụ này'
    )
    
    # DUYỆT
    # Lấy user trong role_ids dồn vào đây, field users sẽ chứa tất cả người dùng có quyền duyệt, đã duyệt và sẽ duyệt dịch vụ này
    users = fields.Many2many('res.users', string='Danh sách người đã và đang duyệt', help='Người có quyền duyệt dịch vụ này')

    def action_back(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Yêu cầu dịch vụ',
            'res_model': 'student.service.request',
            'view_mode': 'list',
            'target': 'current',
        }
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
        ('approved', 'Đã duyệt'), 
        ('rejected', 'Từ chối'),    # Hủy bỏ yêu cầu
        ('adjust_profile', 'Điều chỉnh hồ sơ'),  # Trạng thái yêu cầu sinh viên điều chỉnh hồ sơ
        ('cancelled', 'Đã hủy'),
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
    # Các cờ/ký hiệu để theo dõi khiếu nại
    complaint_count = fields.Integer('Số khiếu nại', compute='_compute_complaint_stats', store=True)
    unresolved_complaint_count = fields.Integer('Số KN chưa giải quyết', compute='_compute_complaint_stats', store=True)
    has_complaint = fields.Boolean('Có khiếu nại', compute='_compute_complaint_stats', store=True)
    has_unresolved_complaint = fields.Boolean('Có KN chưa giải quyết', compute='_compute_complaint_stats', store=True)

    @api.depends('complaint_ids', 'complaint_ids.reply')
    def _compute_complaint_stats(self):
        for rec in self:
            count = len(rec.complaint_ids)
            unresolved = len(rec.complaint_ids.filtered(lambda c: not c.reply or not c.reply.strip()))
            rec.complaint_count = count
            rec.unresolved_complaint_count = unresolved
            rec.has_complaint = count > 0
            rec.has_unresolved_complaint = unresolved > 0

    # GHI NHẬN KẾT QUẢ
    result_ids = fields.One2many('student.service.request.result', 'request_id', string='Kết quả', help='Các kết quả liên quan đến yêu cầu dịch vụ này')

    # GIA HẠN THỜI GIAN
    extension_ids = fields.One2many('request.extension', 'request_id', string='Lịch sử gia hạn', help='Các yêu cầu gia hạn cho dịch vụ này')
    extension_count = fields.Integer('Số lần gia hạn', compute='_compute_extension_stats', help='Tổng số lần đã gia hạn')
    total_extended_hours = fields.Integer('Tổng giờ gia hạn', compute='_compute_extension_stats', help='Tổng số giờ đã gia hạn')
    is_expired = fields.Boolean('Đã quá hạn', compute='_compute_is_expired', help='Yêu cầu đã quá hạn chưa hoàn thành')
    expiry_warning_sent = fields.Boolean('Đã gửi cảnh báo hết hạn', default=False, help='Đã gửi email cảnh báo hết hạn')
    # Theo dõi số lần nhắc quá hạn trong ngày
    expiry_reminder_count = fields.Integer('Số lần nhắc quá hạn trong ngày', default=0)
    expiry_reminder_date = fields.Date('Ngày ghi nhận số lần nhắc', default=fields.Date.today)
        # Trường hiển thị bước hiện tại
    current_step_name = fields.Char(
        string='Bước hiện tại',
        compute='_compute_current_step_name',
        store=False,
        readonly=True,
        help='Tên bước đang được xử lý hiện tại'
    )

    @api.depends('step_ids', 'step_ids.state', 'step_ids.base_secquence', 'final_state')
    def _compute_current_step_name(self):
        """Tính toán tên bước hiện tại đang được xử lý"""
        for record in self:
            current_step_name = ''

            if record.final_state in ['closed', 'cancelled', 'approved']:
                current_step_name = 'Hoàn thành'
            elif record.final_state == 'rejected':
                current_step_name = 'Từ chối'
            else:
                # Tìm bước đang pending đầu tiên theo thứ tự
                pending_steps = record.step_ids.filtered(
                    lambda s: s.state in ['pending', 'assigned', 'repairing']
                ).sorted(lambda s: s.base_secquence or 0)

                if pending_steps:
                    current_step = pending_steps[0]
                    current_step_name = current_step.display_step_name or current_step.base_step_id.name or 'Bước không xác định'
                else:
                    # Nếu không có bước pending, kiểm tra có bước nào chưa
                    if record.step_ids:
                        current_step_name = 'Đang xử lý'
                    else:
                        current_step_name = 'Chưa có bước duyệt'

            record.current_step_name = current_step_name

    step_ids_active = fields.One2many(
        "student.service.request.step",
        compute="_compute_step_ids_active",
        inverse="_inverse_step_ids_active",
        string="Các bước đang hoạt động",
        store=False,
    )

    @api.depends("step_ids.disabled")
    def _compute_step_ids_active(self):
        for rec in self:
            rec.step_ids_active = rec.step_ids.filtered(lambda s: not s.disabled)

    def _inverse_step_ids_active(self):
        # map ngược lại cho step_ids
        for rec in self:
            # gộp cả disabled + active
            rec.step_ids = rec.step_ids_active | rec.step_ids.filtered(lambda s: s.disabled)

    @api.depends('request_user_id')
    def _compute_user_profile_info(self):
        """Tính toán thông tin profile của sinh viên gửi yêu cầu"""
        for record in self:
            if record.request_user_id:
                # Tìm profile sinh viên
                student_profile = self.env['student.user.profile'].search([
                    ('user_id', '=', record.request_user_id.id)
                ], limit=1)
                
                # Lấy phone từ user record trước, nếu không có thì lấy từ profile
                phone = record.request_user_id.phone or record.request_user_id.mobile
                if not phone and student_profile:
                    phone = student_profile.phone
                
                # Xử lý phone - loại bỏ các giá trị False/None/empty
                if phone and phone is not False and phone != 'False' and phone != 'None' and str(phone).strip():
                    record.request_user_phone = str(phone).strip()
                else:
                    record.request_user_phone = ''
                
                if student_profile:
                    record.request_user_dormitory_full = student_profile.dormitory_full_name or ''
                    record.request_user_dormitory_house = student_profile.dormitory_house_name or ''
                    record.request_user_dormitory_room = student_profile.dormitory_room_id or ''
                else:
                    record.request_user_dormitory_full = ''
                    record.request_user_dormitory_house = ''
                    record.request_user_dormitory_room = ''
            else:
                record.request_user_phone = ''
                record.request_user_dormitory_full = ''
                record.request_user_dormitory_house = ''
                record.request_user_dormitory_room = ''
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

    @api.depends('extension_ids', 'extension_ids.state')
    def _compute_extension_stats(self):
        """Tính toán thống kê gia hạn"""
        for record in self:
            approved_extensions = record.extension_ids.filtered(lambda x: x.state == 'approved')
            record.extension_count = len(approved_extensions)
            record.total_extended_hours = sum(approved_extensions.mapped('hours'))

    @api.depends('expired_date', 'final_state')
    def _compute_is_expired(self):
        """Kiểm tra yêu cầu đã quá hạn chưa"""
        now = fields.Datetime.now()
        for record in self:
            record.is_expired = (
                record.expired_date and 
                record.expired_date < now and 
                record.final_state not in ['closed', 'cancelled', 'approved']
            )

    def action_request_extension(self):
        """Mở form yêu cầu gia hạn"""
        self.ensure_one()
        
        # Kiểm tra quyền yêu cầu gia hạn
        if not self._can_request_extension():
            raise UserError("Bạn không có quyền yêu cầu gia hạn cho dịch vụ này!")
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Yêu cầu gia hạn',
            'res_model': 'request.extension.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_request_id': self.id,
                'default_original_deadline': self.expired_date,
            }
        }

    def _can_request_extension(self):
        """Kiểm tra có thể yêu cầu gia hạn không"""
        # Chỉ người được giao hoặc người xử lý mới có thể yêu cầu gia hạn
        current_user = self.env.user
        return (
            current_user.id == self.user_processing_id.id or
            current_user.id == self.approve_user_id.id or
            current_user.id in self.users.ids
        )

    def action_view_extensions(self):
        """Xem lịch sử gia hạn"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Lịch sử gia hạn',
            'res_model': 'request.extension',
            'view_mode': 'list,form',
            'domain': [('request_id', '=', self.id)],
            'context': {'default_request_id': self.id}
        }

    def action_create_new(self):
        super_env = self.with_user(1)
        # Tạo mới yêu cầu dịch vụ
        vals = create_request(self.env, super_env.service_id.id, super_env.id if super_env.id else 0, super_env.request_user_id.id, super_env.note, super_env.image_attachment_ids.ids)
        return { 'type': 'ir.actions.client', 'tag': 'reload' }

    # Lọc trên View theo quyền user
    # user_can_view = fields.Boolean(string='User Can View', compute='_compute_viewer',store=False)
    # @api.depends_context('uid')
    # def _compute_viewer(self):
    #     uid = self.env.user.id
    #     admin_profile = self.env['student.admin.profile'].search([('user_id', '=', uid)], limit=1)
        
    #     for record in self:
    #         try:
    #             # Kiểm tra quyền trực tiếp
    #             has_direct_access = (
    #                 uid in record.service_id.users.ids or 
    #                 (record.approve_user_id and record.approve_user_id.id == uid)
    #             )
                
    #             # Kiểm tra quyền admin profile
    #             has_admin_access = False
    #             admin_profile = self.env['student.admin.profile'].search([('user_id', '=', uid)], limit=1)
                
    #             if admin_profile and admin_profile.department_id and admin_profile.dormitory_clusters:
    #                 has_admin_access = (
    #                     bool(admin_profile.role_ids & record.service_id.role_ids) and
    #                     record.dormitory_cluster_id and
    #                     record.dormitory_cluster_id.id in admin_profile.dormitory_clusters.ids
    #                 )
                
    #             record.user_can_view = has_direct_access or has_admin_access
                
    #         except Exception as e:
    #             # Nếu có lỗi khi truy vấn, mặc định là False
    #             record.user_can_view = False

    def _search(self, args, offset=0, limit=None, order=None):
        uid = self.env.user.id
        user = self.env.user
        # Cho phép Admin hệ thống (base.group_system) và ERP Manager bỏ qua lọc bổ sung
        if uid == 1 or user.has_group('base.group_system') or user.has_group('base.group_erp_manager'):
            return super()._search(args, offset=offset, limit=limit, order=order)

        admin_profile = self.env['student.admin.profile'].search([('user_id', '=', uid)], limit=1)
        # Tạo domain filter
        # OR: là người duyệt, người đang nhận duyệt, hoặc chính người gửi yêu cầu
        domain = ['|', '|',
            ('users', 'in', [uid]), # Đã dồn user trực tiếp vào đây
            ('approve_user_id', '=', uid),
            ('request_user_id', '=', uid)
        ]
        if admin_profile and admin_profile.department_id and admin_profile.dormitory_clusters:
            if admin_profile.role_ids:
                domain = ['|'] + domain + [
                    '&',
                    ('service_id.role_ids', 'in', admin_profile.role_ids.ids),
                    ('dormitory_cluster_id', 'in', admin_profile.dormitory_clusters.ids)
                ]
        
        final_args = domain + args
        # Bỏ tham số count - không có trong _search()
        return super()._search(final_args, offset=offset, limit=limit, order=order)


    # Cron job kiểm tra các request sắp hết hạn và gửi cảnh báo
    @api.model
    def cron_check_timeout_requests(self):
        """Kiểm tra và cập nhật trạng thái timeout cho các request"""
        try:
            # Tìm các request đã quá thời gian xử lý
            timeout_date = fields.Datetime.now() - timedelta(hours=12)
            timeout_requests = self.search([('final_state', '=', 'pending'), ('send_expired_warning', '=', False), ('request_date', '<', timeout_date)])

            # Lấy email template cho yêu cầu quá hạn
            email_template = self.env.ref('student_request.email_template_request_expired', raise_if_not_found=False)
            
            system_user = self.env['res.users'].browse(1)  # Giả sử user hệ thống có ID là 1
            for request in timeout_requests:
                try:
                    # Cập nhật trạng thái timeout
                    print(f"Processing expired request {request.id}: {request.name}")
                    
                    # Gửi email thông báo hết hạn
                    if email_template:
                        # Xác định người nhận email (người xử lý hoặc admin)
                        recipient_email = None
                        target_user_id = None
                        if request.user_processing_id and request.user_processing_id.email:
                            recipient_email = request.user_processing_id.email
                            target_user_id = request.user_processing_id.id
                        elif request.service_id.users:
                            # Lấy email của người duyệt đầu tiên
                            for user in request.service_id.users:
                                if user.email:
                                    recipient_email = user.email
                                    target_user_id = user.id
                                    break
                        
                        if recipient_email:
                            # Gửi email với phương pháp đúng - sử dụng send_mail
                            try:
                                # Tạo context với email_to
                                from odoo.addons.student_request.controllers.service_api.utils import format_datetime_local
                                email_context = {
                                    'email_to': recipient_email,
                                    'auto_delete': False,
                                    'request_date_text': format_datetime_local(request.request_date, user_id=target_user_id) if target_user_id else None,
                                    'expired_date_text': format_datetime_local(request.expired_date, user_id=target_user_id) if target_user_id else None,
                                }
                                # Xác định người gửi hợp lệ để khớp mail server
                                sender = False
                                try:
                                    mail_server = self.env['ir.mail_server'].search([], limit=1)
                                    sender = mail_server.smtp_user if mail_server and mail_server.smtp_user else False
                                    if not sender:
                                        sender = self.env['ir.config_parameter'].sudo().get_param('mail.default.from')
                                    if not sender:
                                        sender = (self.env.company.email or False)
                                    if not sender:
                                        sender = 'noreply@localhost'
                                except Exception:
                                    sender = 'noreply@localhost'
                                email_values = {
                                    'email_to': recipient_email,
                                    'email_from': sender,
                                }
                                mail_id = email_template.with_context(**email_context).send_mail(request.id, force_send=True, email_values=email_values)
                                print(f"Sent expired email notification to {recipient_email} for request {request.name} - Mail ID: {mail_id}")
                            except Exception as email_error:
                                print(f"Error sending email: {email_error}")
                        else:
                            print(f"No recipient email found for request {request.name}")
                    
                    # Gửi FCM notification (giữ lại để tương thích)
                    send_fcm_request(self.env, request, 13)
                    
                    # Cập nhật trạng thái đã gửi cảnh báo
                    request.sudo().write({'send_expired_warning': True})
                    
                except Exception as req_error:
                    print(f"Error processing request {request.id}: {str(req_error)}")
                    continue

            print(f"Processed {len(timeout_requests)} expired requests")
            
        except Exception as e:
            print(f"Error in cron_check_timeout_requests: {str(e)}")

    @api.model
    def _cron_check_expired_requests(self):
        """Cron kiểm tra yêu cầu quá hạn (chạy thường xuyên, 5 phút/lần).
        - Không lọc theo `expiry_warning_sent` để cho phép nhắc nhiều lần.
        - Reset bộ đếm theo ngày và giới hạn tối đa 2 email nhắc/ngày/yêu cầu.
        - Không gửi báo cáo ngày trong cron này (đã có cron riêng)."""
        try:
            now = fields.Datetime.now()
            today = fields.Date.today()

            expired_requests = self.search([
                ('expired_date', '<', now),
                ('final_state', 'not in', ['closed', 'cancelled', 'approved'])
            ])

            processed = 0
            total_overdue = len(expired_requests)

            for request in expired_requests:
                # Reset bộ đếm nếu sang ngày mới
                if request.expiry_reminder_date != today:
                    request.sudo().write({
                        'expiry_reminder_date': today,
                        'expiry_reminder_count': 0,
                    })

                # Giới hạn tối đa 2 lần/ngày
                if request.expiry_reminder_count >= 2:
                    continue

                mail_id = self._send_expiry_notification(request)
                if mail_id:
                    # Ghi log vào chatter khi đã gửi thành công
                    request.message_post(
                        body=f"Yêu cầu đã quá hạn từ {request.expired_date}. Đã gửi email nhắc xử lý.",
                        message_type='notification'
                    )
                    processed += 1

            print(f"Processed {processed} expired requests out of {total_overdue} overdue")

        except Exception as e:
            print(f"Error in _cron_check_expired_requests: {str(e)}")

    def _send_expiry_notification(self, request):
        """Gửi thông báo yêu cầu quá hạn.
        Trả về `mail_id` nếu tạo email thành công, False nếu không."""
        try:
            # Xác định địa chỉ người gửi hợp lệ để khớp mail server
            def _get_default_sender():
                sender = False
                try:
                    mail_server = self.env['ir.mail_server'].search([], limit=1)
                    sender = mail_server.smtp_user if mail_server and mail_server.smtp_user else False
                    if not sender:
                        sender = self.env['ir.config_parameter'].sudo().get_param('mail.default.from')
                    if not sender:
                        sender = (self.env.company.email or False)
                    if not sender:
                        sender = 'noreply@localhost'
                except Exception:
                    sender = 'noreply@localhost'
                return sender

            # Gửi email cho người xử lý, với fallback khi thiếu email
            template = self.env.ref('student_request.email_template_request_expired', raise_if_not_found=False)
            if template:
                recipient_email = False
                target_user_id = False
                # Ưu tiên người đang xử lý
                if request.user_processing_id and request.user_processing_id.email:
                    recipient_email = request.user_processing_id.email
                    target_user_id = request.user_processing_id.id
                # Fallback: người duyệt dịch vụ đầu tiên có email
                elif request.service_id and request.service_id.users:
                    for u in request.service_id.users:
                        if u.email:
                            recipient_email = u.email
                            target_user_id = u.id
                            break
                # Fallback cuối: email quản lý cấu hình hoặc admin
                if not recipient_email:
                    recipient_email = self.env['ir.config_parameter'].sudo().get_param('student_request.manager_email') \
                        or (self.env.company.email or False) \
                        or 'admin@example.com'
                ctx_vals = {
                    'request_date_text': self._format_dt_for_user(request.request_date, user_id=target_user_id),
                    'expired_date_text': self._format_dt_for_user(request.expired_date, user_id=target_user_id),
                }
                email_vals = {
                    'email_to': recipient_email,
                    'email_from': _get_default_sender(),
                }
                mail_id = template.sudo().with_context(**ctx_vals).send_mail(request.id, force_send=True, email_values=email_vals)
                if mail_id:
                    # Tăng bộ đếm và đánh dấu đã gửi cảnh báo
                    request.sudo().write({
                        'expiry_warning_sent': True,
                        'expiry_reminder_count': (request.expiry_reminder_count or 0) + 1,
                        'expiry_reminder_date': fields.Date.today(),
                    })
                    return mail_id
                else:
                    # Fallback: tự tạo mail.mail khi send_mail trả về False
                    try:
                        # Render nội dung từ template
                        generated = template.sudo().with_context(**ctx_vals).generate_email(request.id)
                        subject = generated.get('subject') or f"CẢNH BÁO: Yêu cầu {request.name} đã quá hạn"
                        body = generated.get('body') or ''

                        mail_vals = {
                            'subject': subject,
                            'body_html': body,
                            'email_to': recipient_email,
                            'email_from': _get_default_sender(),
                            'auto_delete': True,
                        }
                        mail = self.env['mail.mail'].sudo().create(mail_vals)
                        if mail:
                            mail.send()
                            request.sudo().write({
                                'expiry_warning_sent': True,
                                'expiry_reminder_count': (request.expiry_reminder_count or 0) + 1,
                                'expiry_reminder_date': fields.Date.today(),
                            })
                            return mail.id
                        else:
                            print(f"Fallback mail creation failed for request {request.id}")
                    except Exception as e:
                        print(f"Fallback send error for request {request.id}: {str(e)}")
                return False

        except Exception as e:
            print(f"Error sending expiry notification: {str(e)}")
            return False

    def _send_daily_expired_report(self, expired_requests):
        """Gửi báo cáo hàng ngày về yêu cầu quá hạn cho lãnh đạo với nội dung chi tiết."""
        try:
            managers = self.env['res.users'].search([
                ('groups_id', 'in', [self.env.ref('student_request.group_student_request_manager').id])
            ])

            # Chuẩn bị dữ liệu báo cáo chi tiết từng yêu cầu
            report_rows = []
            for req in expired_requests:
                # Tính tổng số giờ đã gia hạn (chỉ tính các lần đã được duyệt)
                approved_ext = req.extension_ids.filtered(lambda e: e.state == 'approved')
                total_hours = sum(approved_ext.mapped('hours')) if approved_ext else 0
                extended_days = round(total_hours / 24, 2) if total_hours else 0

                report_rows.append({
                    'id': req.id,
                    'code': req.name,
                    'name': req.name,
                    'deadline': req.expired_date,
                    'extended_hours': total_hours,
                    'extended_days': extended_days,
                    'reason': req.final_data or req.approve_content or '',
                })

            template = self.env.ref('student_request.email_template_daily_expired_report', raise_if_not_found=False)
            if template and managers:
                now_dt = fields.Datetime.now()
                for manager in managers:
                    # Xác định người gửi hợp lệ để khớp mail server
                    sender = False
                    try:
                        mail_server = self.env['ir.mail_server'].search([], limit=1)
                        sender = mail_server.smtp_user if mail_server and mail_server.smtp_user else False
                        if not sender:
                            sender = self.env['ir.config_parameter'].sudo().get_param('mail.default.from')
                        if not sender:
                            sender = (self.env.company.email or False)
                        if not sender:
                            sender = 'noreply@localhost'
                    except Exception:
                        sender = 'noreply@localhost'

                    email_vals = {'email_to': manager.email, 'email_from': sender} if manager.email else {'email_from': sender}
                    # Ánh xạ thời gian theo múi giờ của manager
                    rows_with_text = []
                    for row in report_rows:
                        rows_with_text.append({**row, 'deadline_text': self._format_dt_for_user(row.get('deadline'), user_id=manager.id)})
                    report_date_text = self._format_dt_for_user(now_dt, user_id=manager.id)
                    template.sudo().with_context(
                        report_rows=rows_with_text,
                        expired_count=len(expired_requests),
                        manager=manager,
                        email_to=manager.email,
                        manager_email=manager.email,
                        report_date=now_dt,
                        report_date_text=report_date_text,
                    ).send_mail(expired_requests[0].id, force_send=True, email_values=email_vals)
        except Exception as e:
            print(f"Error sending daily expired report: {str(e)}")

    @api.model
    def cron_send_daily_expired_report(self):
        """Cron hằng ngày: tổng hợp yêu cầu quá hạn và gửi báo cáo cho lãnh đạo"""
        try:
            now = fields.Datetime.now()
            expired_requests = self.search([
                ('expired_date', '<', now),
                ('final_state', 'not in', ['closed', 'cancelled', 'approved'])
            ])
            if expired_requests:
                self._send_daily_expired_report(expired_requests)
        except Exception as e:
            print(f"Error in cron_send_daily_expired_report: {str(e)}")

    def action_view_attachment(self):
        """Mở cửa sổ xem ảnh đính kèm"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Ảnh đính kèm',
            'res_model': 'ir.attachment',
            'view_mode': 'kanban,form',
            'views': [
                (self.env.ref('student_request.view_attachment_kanban_image').id, 'kanban'),
                (self.env.ref('student_request.view_attachment_form_image').id, 'form'),
            ],
            'domain': [('id', 'in', self.image_attachment_ids.ids)],
            'context': {
                'default_res_model': self._name,
                'default_res_id': self.id,
            },
            'target': 'new',
        }
    
# Model quản lý thông tin sinh viên KTX
class StudentUserProfile(models.Model):
    _name = 'student.user.profile'
    _description = 'Thông tin sinh viên KTX'

    user_id = fields.Many2one('res.users', string='User', ondelete='cascade')
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

    def action_fetch_and_create_profile(self, id_card_number):
        external_api_url = "https://sv_test.ktxhcm.edu.vn/MotCuaApi/GetStudentInfo"
        payload = {
            "username": id_card_number,
        }
        resp = py_requests.post(
            external_api_url,
            json=payload,
            timeout=10,
            verify=False,
            headers={"x-api-key": "motcua_ktx_maia_apikey"},
        )

        if resp.status_code != 200:
            raise Exception(f"Lỗi kết nối API ({resp.status_code}): {resp.text}")

        content_type = resp.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            raise Exception("Phản hồi không đúng định dạng JSON")

        external_data = resp.json()
        success = external_data.get("Success", False)
        data = external_data.get("Data")
        message = external_data.get("Message") or "Lỗi không xác định từ hệ thống KTX."
        if not success or data is None:
            raise UserError(message)

        # Thành công: xử lý dữ liệu từ external API
        data = external_data.get("Data", {})

        student_code = data.get("StudentCode")
        full_name = data.get("FullName")
        email = data.get("Email")
        phone = data.get("Phone")
        gender = data.get("Gender")
        birthday = convert_date(data.get("Birthday"))
        university_name = data.get("UniversityName")
        id_card_number = data.get("IdCardNumber")
        id_card_date = convert_date(data.get("IdCardDate"))
        id_card_issued_name = data.get("IdCardIssuedName")
        address = data.get("Address")
        district_name = data.get("DistrictName")
        province_name = data.get("ProvinceName")
        dormitory_full_name = data.get("DormitoryFullName")
        dormitory_area_id = data.get("DormitoryAreaId")
        dormitory_house_name = data.get("DormitoryHouseName")
        dormitory_cluster_id = data.get("DormitoryClusterId")
        dormitory_room_type_name = data.get("DormitoryRoomTypeName")
        dormitory_room_id = data.get("DormitoryRoomId")
        rent_id = data.get("RentId")
        avatar_url = data.get("Avatar")

        # ================================================================
        # Xử lý Area / Cluster (sử dụng self.env thay vì request.env)
        # ================================================================
        try:
            dormitory_area = None
            if dormitory_area_id:
                dormitory_area = self.env["student.dormitory.area"].sudo().search(
                    [("area_id", "=", dormitory_area_id)], limit=1
                )
                if not dormitory_area:
                    dormitory_area = self.env["student.dormitory.area"].sudo().create(
                        {
                            "name": f"Area {dormitory_area_id}",
                            "area_id": dormitory_area_id,
                        }
                    )

            dormitory_cluster = None
            if dormitory_cluster_id:
                dormitory_cluster = self.env["student.dormitory.cluster"].sudo().search(
                    [("qlsv_cluster_id", "=", dormitory_cluster_id)], limit=1
                )
                if not dormitory_cluster:
                    dormitory_cluster = self.env["student.dormitory.cluster"].sudo().create(
                        {
                            "name": f"{dormitory_area.name if dormitory_area else ''} Cluster {dormitory_cluster_id}",
                            "qlsv_cluster_id": dormitory_cluster_id,
                            "qlsv_area_id": dormitory_area.area_id if dormitory_area else False,
                            "area_id": dormitory_area.id if dormitory_area else False,
                        }
                    )
        except Exception as e:
            _logger = self.env["ir.logging"]
            _logger.create(
                {
                    "name": "KTX API",
                    "type": "server",
                    "dbname": self._cr.dbname,
                    "level": "ERROR",
                    "message": f"Lỗi khi tạo area/cluster: {e}",
                    "path": "student.user.profile",
                    "func": "_fetch_and_update_from_ktx_api",
                }
            )
            raise Exception(data.get("Message", e.message))

        # ================================================================
        # Xử lý ảnh avatar (base64)
        # ================================================================
        image_data = False
        if avatar_url:
            try:
                resp = py_requests.get(avatar_url)
                if resp.status_code == 200:
                    image_data = base64.b64encode(resp.content).decode("utf-8")
            except Exception:
                image_data = False

        # ================================================================
        # Xử lý user và profile
        # ================================================================
        # Kiểm tra id_card_number không được null hoặc rỗng
        if not id_card_number:
            raise ValidationError("Số CMND/CCCD không được để trống.")
        
        user = self.env["res.users"].sudo().search([("login", "=", id_card_number)], limit=1)
        if not user:
            # Đảm bảo có tên hợp lệ cho user
            user_name = full_name or id_card_number
            if not user_name:
                user_name = f"User_{id_card_number}"
                
            vals = {
                "name": user_name,
                "login": id_card_number,
                "active": True,
                "groups_id": [(6, 0, [self.env.ref("base.group_public").id])],
                "email": email,
                "phone": phone,
                "image_1920": image_data,
            }
            user = self.env["res.users"].sudo().create(vals)

            if user:
                # Gán quyền "Services / Student Request User" cho user mới
                try:
                    student_request_group = self.env.ref('student_request.group_student_request_user')
                    if student_request_group:
                        user.sudo().write({'groups_id': [(4, student_request_group.id)]})
                except Exception as e:
                    _logger = self.env["ir.logging"]
                    _logger.create({
                        "name": "KTX API Permission",
                        "type": "server",
                        "dbname": self._cr.dbname,
                        "level": "WARNING",
                        "message": f"Không thể gán quyền student_request_user cho user {user.login}: {e}",
                        "path": "student.user.profile",
                        "func": "action_fetch_and_create_profile",
                    })
                # Tạo student.user.profile mới
                self.with_context(skip_ktx_api=True).sudo().env["student.user.profile"].create(
                    {
                        "user_id": user.id,
                        "student_code": student_code,
                        "avatar_url": avatar_url,
                        "birthday": birthday,
                        "gender": gender,
                        "university_name": university_name,
                        "id_card_number": id_card_number,
                        "id_card_date": id_card_date,
                        "id_card_issued_name": id_card_issued_name,
                        "address": address,
                        "district_name": district_name,
                        "province_name": province_name,
                        "dormitory_full_name": dormitory_full_name,
                        "dormitory_area_id": dormitory_area_id,
                        "dormitory_house_name": dormitory_house_name,
                        "dormitory_cluster_id": dormitory_cluster_id,
                        "dormitory_room_type_name": dormitory_room_type_name,
                        "dormitory_room_id": dormitory_room_id,
                        "rent_id": rent_id,
                        "fcm_token": None,
                        "device_id": None,
                    }
                )

                try:
                    remove_user_from_all_firebase_topics(self.env, user.id)
                    add_user_to_firebase_topic(self.env, user.id, dormitory_area_id, dormitory_cluster_id)
                except Exception as e:
                    _logger.create(
                        {
                            "name": "KTX API Firebase",
                            "type": "server",
                            "dbname": self._cr.dbname,
                            "level": "ERROR",
                            "message": f"Lỗi Firebase topic: {e}",
                            "path": "student.user.profile",
                            "func": "_fetch_and_update_from_ktx_api",
                        }
                    )
        else:
            # Cập nhật user đã tồn tại
            user.sudo().write(
                {
                    "email": email,
                    "phone": phone,
                    "image_1920": image_data,
                }
            )

            # Cập nhật hoặc tạo profile
            profile = self.env["student.user.profile"].sudo().search([("user_id", "=", user.id)], limit=1)
            profile_vals = {
                "student_code": student_code,
                "avatar_url": avatar_url,
                "birthday": birthday,
                "gender": gender,
                "university_name": university_name,
                "id_card_number": id_card_number,
                "id_card_date": id_card_date,
                "id_card_issued_name": id_card_issued_name,
                "address": address,
                "district_name": district_name,
                "province_name": province_name,
                "dormitory_full_name": dormitory_full_name,
                "dormitory_area_id": dormitory_area_id,
                "dormitory_house_name": dormitory_house_name,
                "dormitory_cluster_id": dormitory_cluster_id,
                "dormitory_room_type_name": dormitory_room_type_name,
                "dormitory_room_id": dormitory_room_id,
                "rent_id": rent_id,
                "fcm_token": None,
                "device_id": None,
            }

            if profile:
                profile.sudo().write(profile_vals)
            else:
                self.with_context(skip_ktx_api=True).sudo().env["student.user.profile"].sudo().create(
                    {"user_id": user.id, **profile_vals}
                )

        # except Exception as e:
        #     _logger = self.env["ir.logging"]
        #     _logger.create(
        #         {
        #             "name": "KTX API",
        #             "type": "server",
        #             "dbname": self._cr.dbname,
        #             "level": "ERROR",
        #             "message": f"Lỗi khi gọi API KTX: {e}",
        #             "path": "student.user.profile",
        #             "line": "0",
        #             "func": "_fetch_and_update_from_ktx_api",
        #         }
        #     )

class StudentUserProfileWizard(models.TransientModel):
    _name = "student.user.profile.wizard"
    _description = "Quản lý sinh viên KTX"

    id_card_number = fields.Char("Số CCCD")
    student_profile_ids = fields.Many2many(
        "student.user.profile",
        string="Danh sách sinh viên"
    )

    @api.model
    def default_get(self, fields_list):
        """Tự động load danh sách sinh viên khi mở wizard"""
        res = super().default_get(fields_list)
        students = self.env["student.user.profile"].search([])
        res["student_profile_ids"] = [(6, 0, students.ids)]
        return res

    def action_create_profile(self):
        """Gọi hàm tạo profile từ model chính."""
        self.ensure_one()
        id_card = (self.id_card_number or "").strip()
        if not id_card:
            raise UserError("Vui lòng nhập số CCCD.")

        self.env['student.user.profile'].action_fetch_and_create_profile(id_card)

        # Reload lại wizard (có danh sách mới)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'student.user.profile.wizard',
            'view_mode': 'form',
            'target': 'current',
            'name': 'Quản lý sinh viên KTX',
        }


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

    def action_back(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Thông tin quản trị viên',
            'res_model': 'student.admin.profile',
            'view_mode': 'list',
            'target': 'current',
        }

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

    def action_back(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Vai trò hoạt động',
            'res_model': 'student.activity.role',
            'view_mode': 'list',
            'target': 'current',
        }


class ActivityDepartment(models.Model):
    _name = 'student.activity.department'
    _description = 'Phòng ban hoạt động KTX'

    name = fields.Char('Tên phòng ban', required=True)
    description = fields.Text('Mô tả phòng ban')
    admin_profiles = fields.One2many('student.admin.profile', 'department_id', string='Thành viên của Phòng ban')
    cluster_ids = fields.Many2many('student.dormitory.cluster', string='Cụm KTX', help='Các cụm KTX thuộc phòng ban này')

    def action_back(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Phòng ban hoạt động',
            'res_model': 'student.activity.department',
            'view_mode': 'list',
            'target': 'current',
        }


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
    # Gửi thông báo đến người dùng cụ thể
    user_ids = fields.Many2many('res.users', 'student_notify_user_rel', 'notify_id', 'user_id', string='Người nhận', help='Danh sách người dùng nhận thông báo')
    # Gửi thông báo đến cụm ký túc xá
    cluster_ids = fields.Many2many('student.dormitory.cluster', string='Cụm KTX', help='Danh sách cụm ký túc xá nhận thông báo')
    # Gửi thông báo đến vai trò hoạt động
    role_ids = fields.Many2many('student.activity.role', string='Vai trò', help='Danh sách vai trò hoạt động nhận thông báo')
    # Gửi thông báo đến phòng ban
    department_ids = fields.Many2many('student.activity.department', string='Phòng ban', help='Danh sách phòng ban nhận thông báo')

    def action_back(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Thông báo',
            'res_model': 'student.notify',
            'view_mode': 'list',
            'target': 'current',
        }

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

    def action_back(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Khu ký túc xá',
            'res_model': 'student.dormitory.area',
            'view_mode': 'list',
            'target': 'current',
        }

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

    def action_back(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Cụm ký túc xá',
            'res_model': 'student.dormitory.cluster',
            'view_mode': 'list',
            'target': 'current',
        }


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
    _description = "Báo cáo thống kê yêu cầu"

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

    report_line_ids = fields.One2many(
        'student.service.report',
        'wizard_id',
        string="Kết quả báo cáo"
    )

    @api.onchange('mode')
    def _onchange_mode(self):
        self.from_date = self.to_date = False
        self.from_month = self.to_month = False
        self.from_year = self.to_year = False

    def action_generate_report(self):
        self.ensure_one()

        # Xóa kết quả cũ
        self.report_line_ids.unlink()

        params = {"mode": self.mode}
        where_clause = ""

        if self.mode == 'day':
            if not (self.from_date and self.to_date):
                raise UserError("Vui lòng nhập khoảng ngày.")
            formatted_from_date = self.from_date.strftime("%d/%m/%Y")
            formatted_to_date = self.to_date.strftime("%d/%m/%Y")
            parse_to_date = datetime.strptime(formatted_to_date, "%d/%m/%Y").date() + relativedelta(days=1)
            parse_from_date = datetime.strptime(formatted_from_date, "%d/%m/%Y").date()
            where_clause = """
                WHERE r.request_date >= %(parse_from_date)s
                  AND r.request_date < %(parse_to_date)s
            """
            params.update({
                "parse_from_date": parse_from_date,
                "parse_to_date": parse_to_date
            })

        elif self.mode == 'month':
            if not (self.from_month and self.to_month):
                raise UserError("Vui lòng nhập khoảng tháng.")
            where_clause = """
                WHERE r.request_date >= DATE_TRUNC('month', TO_DATE(%(from_month)s, 'MM/YYYY'))
                AND r.request_date < DATE_TRUNC('month', TO_DATE(%(to_month)s, 'MM/YYYY') + INTERVAL '1 month')
            """
            params.update({
                "from_month": self.from_month,
                "to_month": self.to_month,
            })

        elif self.mode == 'year':
            if not (self.from_year and self.to_year):
                raise UserError("Vui lòng nhập khoảng năm.")
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

        # for row in rows:
        #     self.env['student.service.report'].create({
        #         **row,
        #         "wizard_id": self.id
        #     })
        # Xóa dữ liệu cũ
        self.report_line_ids.unlink()

        # Biến tổng
        total_requests = 0
        total_processed = 0
        total_pending = 0
        total_overdue = 0

        self.env.cr.execute(query, params) 
        rows = self.env.cr.dictfetchall() 
        total_requests = total_processed = total_pending = total_overdue = 0 
        for row in rows: 
            total_requests += row.get("total_requests", 0) 
            total_processed += row.get("processed_requests", 0) 
            total_pending += row.get("pending_requests", 0) 
            total_overdue += row.get("overdue_requests", 0) 
            self.env['student.service.report'].create({ **row, "wizard_id": self.id }) 
        if rows: 
            percent = (total_processed * 100.0 / total_requests) if total_requests else 0.0 
            self.env['student.service.report'].create({ 
                "wizard_id": self.id, 
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
        # ⚡ Không return act_window (để form không reload) 
        # return { 
        # 'effect': { 
        #     'fadeout': 'slow', 
        #     'message': 'Đã cập nhật báo cáo', 
        #     'type': 'rainbow_man', 
        #     } 
        # }


class StudentServiceReport(models.TransientModel):
    _name = "student.service.report"
    _description = "Chi tiết báo cáo"

    wizard_id = fields.Many2one('student.service.report.wizard')
    period = fields.Char(string='Ngày/Tháng/Năm')
    area_name = fields.Char(string='Khu ký túc xá')
    cluster_name = fields.Char(string='Cụm')
    group_name = fields.Char(string='Nhóm')
    service_name = fields.Char(string='Dịch vụ')
    total_requests = fields.Integer(string='Tổng yêu cầu')
    processed_requests = fields.Integer(string='Đã xử lý')
    pending_requests = fields.Integer(string='Chưa xử lý')
    overdue_requests = fields.Integer(string='Quá hạn')
    processed_percent = fields.Float(string='% Xử lý', compute="_compute_processed_percent", store=False)

    @api.depends('processed_requests', 'total_requests')
    def _compute_processed_percent(self):
        for rec in self:
            if rec.total_requests:
                rec.processed_percent = rec.processed_requests * 100.0 / rec.total_requests
            else:
                rec.processed_percent = 0.0

# Model trung gian để lưu thứ tự tùy chỉnh và cho phép lặp lại các bước
class ServiceStepSelection(models.Model):
    _name = 'student.service.step.selection'
    _description = 'Lựa chọn bước duyệt cho dịch vụ'
    _order = 'sequence'
    _rec_name = 'name'

    service_id = fields.Many2one('student.service', string='Dịch vụ', required=True, ondelete='cascade')
    step_id = fields.Many2one('student.service.step', string='Bước duyệt', required=True, ondelete='cascade')
    sequence = fields.Integer('Thứ tự', default=1, help='Thứ tự thực hiện bước trong dịch vụ')
    
    # Các trường liên quan từ step_id để hiển thị
    step_name = fields.Char('Tên bước', related='step_id.name', readonly=True, store=True)
    step_description = fields.Text('Mô tả bước', related='step_id.description', readonly=True, store=True)

    # Tên hiển thị rõ ràng cho tag: "Bước <sequence>: <step_name>"
    name = fields.Char(string='Tên hiển thị', compute='_compute_name', store=True)

    @api.depends('sequence', 'step_name')
    def _compute_name(self):
        for record in self:
            if record.step_name:
                record.name = f"Bước {record.sequence}: {record.step_name}"
            else:
                record.name = f"Bước {record.sequence}"

    def name_get(self):
        """Override name_get to display both sequence and step name"""
        result = []
        for record in self:
            # Sử dụng field name đã được compute
            display = record.name or f"Bước {record.sequence}"
            result.append((record.id, display))
        return result

    @api.model
    def create(self, vals):
        _logger.info(f"ServiceStepSelection create called with vals: {vals}")
        
        # Tự động gán sequence nếu không có
        if 'sequence' not in vals or vals['sequence'] == 0:
            service_id = vals.get('service_id')
            if service_id:
                last_sequence = self.search([('service_id', '=', service_id)], order='sequence desc', limit=1)
                vals['sequence'] = (last_sequence.sequence + 1) if last_sequence else 1
                _logger.info(f"Auto-assigned sequence: {vals['sequence']}")
        
        try:
            result = super().create(vals)
            _logger.info(f"ServiceStepSelection created successfully with ID: {result.id}")
            return result
        except Exception as e:
            _logger.error(f"Error creating ServiceStepSelection: {str(e)}")
            raise

    def read(self, fields=None, load='_classic_read'):
        _logger.info(f"ServiceStepSelection read called for IDs: {self.ids}, fields: {fields}")
        result = super().read(fields, load)
        _logger.info(f"ServiceStepSelection read result: {result}")
        return result

    @api.model
    def search_read(self, domain=None, fields=None, offset=0, limit=None, order=None):
        _logger.info(f"ServiceStepSelection search_read called with domain: {domain}, fields: {fields}")
        result = super().search_read(domain, fields, offset, limit, order)
        _logger.info(f"ServiceStepSelection search_read result count: {len(result)}")
        return result
        for record in self:
            # Sử dụng field name đã được compute
            display = record.name or f"Bước {record.sequence}"
            result.append((record.id, display))
        return result

    @api.model
    def create(self, vals):
        _logger.info(f"ServiceStepSelection create called with vals: {vals}")
        
        # Tự động gán sequence nếu không có
        if 'sequence' not in vals or vals['sequence'] == 0:
            service_id = vals.get('service_id')
            if service_id:
                last_sequence = self.search([('service_id', '=', service_id)], order='sequence desc', limit=1)
                vals['sequence'] = (last_sequence.sequence + 1) if last_sequence else 1
                _logger.info(f"Auto-assigned sequence: {vals['sequence']}")
        
        try:
            result = super().create(vals)
            _logger.info(f"ServiceStepSelection created successfully with ID: {result.id}")
            return result
        except Exception as e:
            _logger.error(f"Error creating ServiceStepSelection: {str(e)}")
            raise

    def read(self, fields=None, load='_classic_read'):
        _logger.info(f"ServiceStepSelection read called for IDs: {self.ids}, fields: {fields}")
        result = super().read(fields, load)
        _logger.info(f"ServiceStepSelection read result: {result}")
        return result

    @api.model
    def search_read(self, domain=None, fields=None, offset=0, limit=None, order=None):
        _logger.info(f"ServiceStepSelection search_read called with domain: {domain}, fields: {fields}")
        result = super().search_read(domain, fields, offset, limit, order)
        _logger.info(f"ServiceStepSelection search_read result count: {len(result)}")
        return result