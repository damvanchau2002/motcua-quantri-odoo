from odoo import models, fields, api

class RequestReview(models.Model):
    _name = 'student.service.request.review'
    _description = 'Request Review'

    name = fields.Char(string='Complaint Title', required=True, default=lambda self: self.env.user.name if self.env.user else '')
    request_id = fields.Many2one('student.service.request', string='Yêu cầu dịch vụ')
    user_id = fields.Many2one('res.users', string='Reviewed By', default=lambda self: self.env.user)
    review_date = fields.Datetime(string='Review Date', default=fields.Datetime.now)
    rating = fields.Selection([
        ('1', 'Rất tệ'),
        ('2', 'Tệ'),
        ('3', 'Bình thường'),
        ('4', 'Tốt'),
        ('5', 'Rất tốt'),
    ], string='Đánh giá', required=True)
    ispublic = fields.Boolean(string='Công bố review này', default=False)
    image_ids = fields.Many2many(
        'ir.attachment',
        'request_review_image_rel',
        'review_id',
        'attachment_id',
        string='Review Images',
        help='Upload and attach multiple images to this review'
    )
    comments = fields.Text(string='Comments')
    reply = fields.Text(string='Phản hồi ')


class RequestComplaint(models.Model):
    _name = 'student.service.request.complaint'
    _description = 'Request Complaint'

    name = fields.Char(string='Complaint Title', required=True, default=lambda self: self.env.user.name if self.env.user else '')
    request_id = fields.Many2one('student.service.request', string='Yêu cầu dịch vụ')
    user_id = fields.Many2one('res.users', string='Complained By', default=lambda self: self.env.user)
    complaint_date = fields.Datetime(string='Complaint Date', default=fields.Datetime.now)
    image_ids = fields.Many2many(
        'ir.attachment',
        'request_complaint_image_rel',
        'complaint_id',
        'attachment_id',
        string='Complaint Images',
        help='Upload and attach multiple images to this complaint'
    )
    description = fields.Text(string='Description')
    reply = fields.Text(string='Trả lời ý kiến')

class TemporaryWizard(models.TransientModel):
    _name = 'temporary.wizard'
    _description = 'Wizard Tạm Thời'

    request_id = fields.Many2one('student.service.request', string='Yêu cầu dịch vụ', required=True)
    user_id = fields.Many2one('res.users', string='Người gửi yêu cầu')
    note = fields.Text(string='Ghi chú')
    action = fields.Selection([
        ('issue', 'Cần sửa lại'),   # Cần sửa lại
        ('accept', 'Chấp nhận'),    # Hoàn thành
        ('reject', 'Từ chối'),      # Không hoàn thành
    ], string='Hành động', required=True)
    star = fields.Integer('Sao đánh giá (1-5)', help='Số sao đánh giá cho yêu cầu dịch vụ này', required=True)
    user_accept = fields.Many2one('res.users', string='Người chấp nhận', default=lambda self: self.env.user)

    
    @api.model
    def default_get(self, fields_list):
        # load user kèm theo
        res = super().default_get(fields_list)
        if res.get('request_id'):
            request = self.env['student.service.request'].browse(res['request_id'])
            res['user_id'] = request.request_user_id.id
        return res

    # Nghiệm thu yêu cầu
    def action_confirm(self):
        # Tạo bản ghi Result
        self.env['student.service.request.result'].create({
            'request_id': self.request_id.id,
            'user_id': self.request_id.request_user_id.id,
            'note': self.note,
            'action': self.action,
            'star': self.star,
            'action_user': self.user_accept.id,
            'acceptance_ids': [(6, 0, self.request_id.users.ids)]
        })

        # Lấy ra Request
        request = self.env['student.service.request'].browse(self.request_id.id)
        if self.action == 'issue':
            request.final_state = 'repairing'
        elif self.action == 'accept':
            request.final_state = 'closed'
        elif self.action == 'reject':
            request.final_state = 'rejected'
        # Cập nhật trạng thái cuối cùng của yêu cầu
        request.write({'final_state': request.final_state})
        # Xóa bản ghi tạm thời
        self.unlink()
        return { 'type': 'ir.actions.client', 'tag': 'reload' }
