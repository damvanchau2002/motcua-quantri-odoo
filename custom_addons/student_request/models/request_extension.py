from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import datetime, timedelta
import logging

_logger = logging.getLogger(__name__)
from odoo.addons.student_request.controllers.service_api.utils import format_datetime_local


class RequestExtension(models.Model):
    _name = 'request.extension'
    _description = 'Yêu cầu gia hạn thời gian xử lý'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    # Thông tin cơ bản
    name = fields.Char('Tên yêu cầu gia hạn', compute='_compute_name', store=True)
    request_id = fields.Many2one(
        'student.service.request', 
        string='Yêu cầu dịch vụ', 
        required=True,
        ondelete='cascade',
        help='Yêu cầu dịch vụ cần gia hạn'
    )
    
    # Thông tin gia hạn
    hours = fields.Integer(
        'Số giờ gia hạn', 
        required=False,
        help='Số giờ muốn gia hạn thêm (tối đa 720 giờ/lần)'
    )
    reason = fields.Text(
        'Lý do gia hạn', 
        required=True,
        help='Lý do cần gia hạn thời gian xử lý'
    )
    
    # Thông tin người yêu cầu
    requested_by = fields.Many2one(
        'res.users', 
        string='Người yêu cầu', 
        required=True,
        default=lambda self: self.env.user,
        help='Người gửi yêu cầu gia hạn'
    )
    request_date = fields.Datetime(
        'Ngày yêu cầu', 
        default=fields.Datetime.now,
        help='Ngày gửi yêu cầu gia hạn'
    )
    
    # Trạng thái workflow
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('submitted', 'Đã gửi'),
        ('approved', 'Đã duyệt'),
        ('rejected', 'Từ chối')
    ], string='Trạng thái', default='draft')
    
    # Thông tin duyệt
    approved_by = fields.Many2one(
        'res.users', 
        string='Người duyệt',
        help='Người có thẩm quyền duyệt gia hạn'
    )
    approval_date = fields.Datetime(
        'Ngày duyệt',
        help='Ngày duyệt yêu cầu gia hạn'
    )
    rejection_reason = fields.Text(
        'Lý do từ chối',
        help='Lý do từ chối yêu cầu gia hạn'
    )
    rejection_date = fields.Datetime(
        'Ngày từ chối',
        help='Ngày từ chối yêu cầu gia hạn'
    )
    
    # Thông tin deadline
    original_deadline = fields.Datetime(
        'Deadline gốc',
        related='request_id.expired_date',
        store=True,
        help='Thời hạn gốc của yêu cầu'
    )
    new_deadline = fields.Datetime(
        'Deadline mới',
        compute='_compute_new_deadline',
        store=True,
        help='Thời hạn mới sau khi gia hạn'
    )
    
    # Thống kê gia hạn
    total_extensions = fields.Integer(
        'Tổng số lần gia hạn',
        compute='_compute_extension_stats',
        help='Tổng số lần đã gia hạn cho yêu cầu này'
    )
    total_extended_hours = fields.Integer(
        'Tổng số giờ đã gia hạn',
        compute='_compute_extension_stats',
        help='Tổng số giờ đã gia hạn cho yêu cầu này'
    )

    @api.depends('request_id', 'hours')
    def _compute_name(self):
        for record in self:
            if record.request_id:
                record.name = f"Gia hạn {record.hours} giờ - {record.request_id.name}"
            else:
                record.name = f"Gia hạn {record.hours} giờ"

    @api.depends('original_deadline', 'hours')
    def _compute_new_deadline(self):
        for record in self:
            if record.original_deadline and record.hours:
                record.new_deadline = record.original_deadline + timedelta(hours=record.hours)
            else:
                record.new_deadline = False

    @api.depends('request_id')
    def _compute_extension_stats(self):
        for record in self:
            if record.request_id:
                approved_extensions = self.search([
                    ('request_id', '=', record.request_id.id),
                    ('state', '=', 'approved')
                ])
                record.total_extensions = len(approved_extensions)
                record.total_extended_hours = sum(approved_extensions.mapped('hours'))
            else:
                record.total_extensions = 0
                record.total_extended_hours = 0

    @api.constrains('hours')
    def _check_extension_hours(self):
        for record in self:
            if record.hours <= 0:
                raise ValidationError("Số giờ gia hạn phải lớn hơn 0!")
            if record.hours > 720:  # 30 ngày = 720 giờ
                raise ValidationError("Mỗi lần gia hạn tối đa 720 giờ (30 ngày)!")

    @api.constrains('request_id', 'hours')
    def _check_total_extension_limit(self):
        for record in self:
            if record.request_id:
                # Tính tổng số giờ đã gia hạn (bao gồm cả yêu cầu hiện tại)
                approved_extensions = self.search([
                    ('request_id', '=', record.request_id.id),
                    ('state', '=', 'approved'),
                    ('id', '!=', record.id)  # Loại trừ bản ghi hiện tại
                ])
                total_hours = sum(approved_extensions.mapped('hours')) + record.hours
                max_hours = 2160  # 90 ngày = 2160 giờ
                
                if total_hours > max_hours:
                    raise ValidationError(
                        f"Tổng số giờ gia hạn không được vượt quá {max_hours} giờ (90 ngày)! "
                        f"Hiện tại đã gia hạn {total_hours - record.hours} giờ, "
                        f"chỉ có thể gia hạn thêm tối đa {max_hours - (total_hours - record.hours)} giờ."
                    )

    def _format_dt_for_user(self, dt, user_id=None, fmt='%d/%m/%Y %H:%M'):
        """Trả về chuỗi thời gian theo múi giờ người dùng.
        Ưu tiên dùng format_datetime_local; fallback context timezone rồi strftime.
        """
        if not dt:
            return 'N/A'
        try:
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

    def action_submit(self):
        """Gửi yêu cầu gia hạn"""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError("Chỉ có thể gửi yêu cầu ở trạng thái nháp!")
        
        self.write({
            'state': 'submitted'
        })
        
        # Ghi log vào chatter
        self.message_post(
            body=f"Yêu cầu gia hạn {self.hours} giờ đã được gửi. Lý do: {self.reason}",
            message_type='notification'
        )
        
        # Gửi email thông báo cho người xử lý/manager
        try:
            template = self.env.ref('student_request.email_template_extension_submitted', raise_if_not_found=False)
            if template:
                # Sử dụng sudo để đảm bảo có quyền đọc request_id khi render email
                request_date_text = self._format_dt_for_user(self.request_date, user_id=(self.requested_by.id if self.requested_by else None))
                template.sudo().with_context(request_date_text=request_date_text).send_mail(self.id, force_send=True)
                _logger.info(f"Đã gửi email thông báo gửi gia hạn cho extension ID: {self.id}")
            else:
                _logger.warning("Không tìm thấy template email_template_extension_submitted")
        except Exception as e:
            _logger.error(f"Lỗi khi gửi email thông báo gửi gia hạn: {e}")
        return True

    def action_approve(self):
        """Duyệt yêu cầu gia hạn"""
        self.ensure_one()
        if self.state != 'submitted':
            raise UserError("Chỉ có thể duyệt yêu cầu đã được gửi!")
        
        # Cập nhật deadline của yêu cầu gốc
        new_deadline = self.request_id.expired_date + timedelta(hours=self.hours)
        self.request_id.write({
            'expired_date': new_deadline,
            'final_state': 'extended'
        })
        
        # Cập nhật trạng thái gia hạn
        self.write({
            'state': 'approved',
            'approved_by': self.env.user.id,
            'approval_date': fields.Datetime.now()
        })
        
        # Ghi log vào chatter
        # Hiển thị deadline theo múi giờ của người dùng
        try:
            local_deadline = fields.Datetime.context_timestamp(self, new_deadline)
            deadline_text = local_deadline.strftime('%d/%m/%Y %H:%M') if local_deadline else new_deadline.strftime('%d/%m/%Y %H:%M')
        except Exception:
            deadline_text = new_deadline.strftime('%d/%m/%Y %H:%M')
        self.message_post(
            body=f"Yêu cầu gia hạn đã được duyệt. Deadline mới: {deadline_text}",
            message_type='notification'
        )
        
        # Gửi email thông báo cho người yêu cầu
        try:
            template = self.env.ref('student_request.email_template_extension_approved', raise_if_not_found=False)
            if template:
                # Sử dụng sudo để đảm bảo có quyền đọc request_id khi render email
                new_deadline_text = self._format_dt_for_user(self.new_deadline, user_id=(self.requested_by.id if self.requested_by else None))
                template.sudo().with_context(new_deadline_text=new_deadline_text).send_mail(self.id, force_send=True)
                _logger.info(f"Đã gửi email duyệt gia hạn cho extension ID: {self.id}")
            else:
                _logger.warning("Không tìm thấy template email_template_extension_approved")
        except Exception as e:
            _logger.error(f"Lỗi khi gửi email duyệt gia hạn: {e}")
        return True

    def action_reject(self):
        """Từ chối yêu cầu gia hạn"""
        self.ensure_one()
        if self.state != 'submitted':
            raise UserError("Chỉ có thể từ chối yêu cầu đã được gửi!")
        
        # Mở wizard để nhập lý do từ chối
        return {
            'type': 'ir.actions.act_window',
            'name': 'Lý do từ chối',
            'res_model': 'request.extension.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_extension_id': self.id}
        }

    def action_reset_to_draft(self):
        """Đặt lại về trạng thái nháp"""
        self.ensure_one()
        if self.state not in ['rejected']:
            raise UserError("Chỉ có thể đặt lại yêu cầu bị từ chối!")
        
        self.write({
            'state': 'draft',
            'rejection_reason': False
        })
        
        return True

    def write(self, vals):
        """Đảm bảo luôn có rejection_date khi chuyển sang trạng thái 'rejected' và gửi email tự động."""
        # Nếu chuyển sang 'rejected' mà chưa cung cấp rejection_date thì tự động set tại đây
        vals_to_write = dict(vals)
        if vals_to_write.get('state') == 'rejected' and not vals_to_write.get('rejection_date'):
            vals_to_write['rejection_date'] = fields.Datetime.now()

        res = super(RequestExtension, self).write(vals_to_write)
        try:
            if vals_to_write.get('state') == 'rejected':
                template = self.env.ref('student_request.email_template_extension_rejected', raise_if_not_found=False)
                if template:
                    for record in self:
                        rejection_date_text = record._format_dt_for_user(record.rejection_date, user_id=(record.requested_by.id if record.requested_by else None))
                        template.sudo().with_context(rejection_date_text=rejection_date_text).send_mail(record.id, force_send=True)
                        _logger.info(f"Đã gửi email từ chối gia hạn (auto) cho extension ID: {record.id}")
                else:
                    _logger.warning("Không tìm thấy template email_template_extension_rejected khi auto-send")
        except Exception as e:
            _logger.error(f"Lỗi auto-send email khi từ chối gia hạn: {e}")
        return res

    @api.model
    def _setup_admin_permissions(self):
        """Tự động gán quyền manager cho user admin"""
        try:
            admin_user = self.env.ref('base.user_admin')
            manager_group = self.env.ref('student_request.group_student_request_manager')
            if manager_group not in admin_user.groups_id:
                admin_user.groups_id = [(4, manager_group.id)]
                _logger.info("Đã gán quyền Student Request Manager cho user admin")
        except Exception as e:
            _logger.warning(f"Không thể gán quyền cho admin: {e}")


class RequestExtensionRejectWizard(models.TransientModel):
    _name = 'request.extension.reject.wizard'
    _description = 'Wizard từ chối yêu cầu gia hạn'

    extension_id = fields.Many2one('request.extension', string='Yêu cầu gia hạn', required=True)
    rejection_reason = fields.Text('Lý do từ chối', required=True)

    def action_reject_extension(self):
        """Từ chối yêu cầu gia hạn - alias cho action_confirm_reject"""
        return self.action_confirm_reject()

    def action_confirm_reject(self):
        """Xác nhận từ chối"""
        self.extension_id.write({
            'state': 'rejected',
            'rejection_reason': self.rejection_reason,
            'approved_by': self.env.user.id,
            'approval_date': fields.Datetime.now(),
            'rejection_date': fields.Datetime.now()
        })
        
        # Ghi log vào chatter
        self.extension_id.message_post(
            body=f"Yêu cầu gia hạn đã bị từ chối. Lý do: {self.rejection_reason}",
            message_type='notification'
        )
        
        # Gửi email thông báo cho người yêu cầu
        try:
            template = self.env.ref('student_request.email_template_extension_rejected')
            if template:
                # Sử dụng sudo để đảm bảo có quyền đọc request_id khi render email
                rejection_date_text = self.extension_id._format_dt_for_user(self.extension_id.rejection_date, user_id=(self.extension_id.requested_by.id if self.extension_id.requested_by else None))
                template.sudo().with_context(rejection_date_text=rejection_date_text).send_mail(self.extension_id.id, force_send=True)
                _logger.info(f"Đã gửi email từ chối gia hạn cho extension ID: {self.extension_id.id}")
        except Exception as e:
            _logger.error(f"Lỗi khi gửi email từ chối gia hạn: {e}")
        
        return {'type': 'ir.actions.act_window_close'}