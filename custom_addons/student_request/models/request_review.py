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