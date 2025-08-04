from odoo import models, fields, api

class RequestReview(models.Model):
    _name = 'student.service.request.review'
    _description = 'Request Review'

    name = fields.Char(string='Review Title', required=True)
    request_id = fields.Many2one('student.service.request', string='Yêu cầu dịch vụ')
    user_id = fields.Many2one('res.users', string='Reviewed By', default=lambda self: self.env.user)
    review_date = fields.Datetime(string='Review Date', default=fields.Datetime.now)
    rating = fields.Selection([
        ('excellent', 'Excellent'),
        ('good', 'Good'),
        ('average', 'Average'),
        ('poor', 'Poor'),
    ], string='Rating', required=True)
    comments = fields.Text(string='Comments')


class RequestComplaint(models.Model):
    _name = 'student.service.request.complaint'
    _description = 'Request Complaint'

    name = fields.Char(string='Complaint Title', required=True)
    request_id = fields.Many2one('student.service.request', string='Yêu cầu dịch vụ')
    user_id = fields.Many2one('res.users', string='Complained By', default=lambda self: self.env.user)
    complaint_date = fields.Datetime(string='Complaint Date', default=fields.Datetime.now)
    complaint_type = fields.Selection([
        ('service', 'Service'),
        ('process', 'Process'),
        ('other', 'Other'),
    ], string='Complaint Type', required=True)
    description = fields.Text(string='Description')