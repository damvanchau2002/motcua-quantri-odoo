from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import datetime, timedelta


class RequestExtensionWizard(models.TransientModel):
    _name = 'request.extension.wizard'
    _description = 'Wizard yêu cầu gia hạn'

    request_id = fields.Many2one(
        'student.service.request', 
        string='Yêu cầu dịch vụ', 
        required=True,
        readonly=True
    )
    
    # Thông tin hiện tại
    current_deadline = fields.Datetime(
        'Deadline hiện tại',
        related='request_id.expired_date',
        readonly=True
    )
    current_status = fields.Selection(
        related='request_id.final_state',
        readonly=True
    )
    
    # Thông tin gia hạn hiện có
    current_extensions = fields.Integer(
        'Số lần đã gia hạn',
        related='request_id.extension_count',
        readonly=True
    )
    current_extended_hours = fields.Integer(
        'Tổng giờ đã gia hạn',
        related='request_id.total_extended_hours',
        readonly=True
    )
    
    # Yêu cầu gia hạn mới
    hours = fields.Integer(
        'Số giờ gia hạn', 
        required=True,
        default=168,  # 7 ngày = 168 giờ
        help='Số giờ muốn gia hạn thêm (tối đa 720 giờ/lần)'
    )
    reason = fields.Text(
        'Lý do gia hạn', 
        required=True,
        help='Lý do cần gia hạn thời gian xử lý'
    )
    
    # Thông tin tính toán
    new_deadline = fields.Datetime(
        'Deadline mới',
        compute='_compute_new_deadline',
        help='Thời hạn mới sau khi gia hạn'
    )
    remaining_hours_allowed = fields.Integer(
        'Số giờ còn có thể gia hạn',
        compute='_compute_remaining_hours',
        help='Số giờ còn có thể gia hạn (tối đa 2160 giờ tổng)'
    )
    
    @api.depends('current_deadline', 'hours')
    def _compute_new_deadline(self):
        for record in self:
            if record.current_deadline and record.hours:
                record.new_deadline = record.current_deadline + timedelta(hours=record.hours)
            else:
                record.new_deadline = False

    @api.depends('current_extended_hours')
    def _compute_remaining_hours(self):
        for record in self:
            record.remaining_hours_allowed = max(0, 2160 - record.current_extended_hours)  # 90 ngày = 2160 giờ

    @api.constrains('hours')
    def _check_extension_hours(self):
        for record in self:
            if record.hours <= 0:
                raise ValidationError("Số giờ gia hạn phải lớn hơn 0!")
            if record.hours > 720:  # 30 ngày = 720 giờ
                raise ValidationError("Mỗi lần gia hạn tối đa 720 giờ (30 ngày)!")
            if record.hours > record.remaining_hours_allowed:
                raise ValidationError(
                    f"Không thể gia hạn {record.hours} giờ! "
                    f"Chỉ còn có thể gia hạn tối đa {record.remaining_hours_allowed} giờ "
                    f"(đã gia hạn {record.current_extended_hours}/2160 giờ)."
                )

    def action_submit_extension(self):
        """Gửi yêu cầu gia hạn"""
        self.ensure_one()
        
        # Tạo yêu cầu gia hạn mới
        extension = self.env['request.extension'].create({
            'request_id': self.request_id.id,
            'hours': self.hours,
            'reason': self.reason,
            'requested_by': self.env.user.id,
        })
        
        # Gửi yêu cầu
        extension.action_submit()
        
        # Hiển thị thông báo thành công và tự động đóng popup
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Thành công',
                'message': f'Yêu cầu gia hạn {self.hours} giờ đã được gửi thành công!',
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'}
            }
        }