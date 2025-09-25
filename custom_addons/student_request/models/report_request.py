from odoo import models, fields, api

class ServiceRequestReport(models.Model):
    _name = 'service.request.report'
    _description = 'Báo cáo tổng hợp yêu cầu dịch vụ'

    date_from = fields.Datetime('Từ ngày')
    date_to = fields.Datetime('Đến ngày')

    report_date = fields.Date('Ngày')
    cluster = fields.Char('Cụm')
    house = fields.Char('Nhà')
    service_group = fields.Char('Nhóm dịch vụ')
    service_name = fields.Char('Dịch vụ cụ thể')
    total_request = fields.Integer('Tổng yêu cầu')
    processed = fields.Integer('Đã xử lý')
    unprocessed = fields.Integer('Chưa xử lý')
    overdue = fields.Integer('Quá hạn xử lý')
    percent_processed = fields.Float('% xử lý', compute='_compute_percent_processed')

    @api.depends('total_request', 'processed')
    def _compute_percent_processed(self):
        domain = []
        if self.date_from:
            domain.append(('report_date', '>=', self.date_from))
        if self.date_to:
            domain.append(('report_date', '<=', self.date_to))
            
        for rec in self:
            rec.percent_processed = (rec.processed / rec.total_request * 100) if rec.total_request else 0