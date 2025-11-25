from odoo import models, fields, tools


class StudentRequestStatsService(models.Model):
    _name = 'student.request.stats.service'
    _description = 'Thống kê yêu cầu theo dịch vụ'
    _auto = False

    service_id = fields.Many2one('student.service', string='Dịch vụ', readonly=True)
    stat_date = fields.Date(string='Ngày', readonly=True)
    created_requests = fields.Integer(string='Yêu cầu tạo', readonly=True)
    new_requests = fields.Integer(string='Yêu cầu mới (24h)', readonly=True)
    overdue_requests = fields.Integer(string='Yêu cầu quá hạn', readonly=True)

    def init(self):
        # Xóa view nếu có (đây là VIEW chứ không phải TABLE)
        tools.drop_view_if_exists(self._cr, 'student_request_stats_service')
        # Tạo lại view an toàn
        self._cr.execute(
            """
            CREATE OR REPLACE VIEW student_request_stats_service AS
            SELECT
                s.id AS id,
                s.id AS service_id,
                CURRENT_DATE AS stat_date,
                COALESCE(COUNT(r.id), 0) AS created_requests,
                COALESCE(SUM(CASE WHEN r.create_date >= (NOW() - INTERVAL '1 day') THEN 1 ELSE 0 END), 0) AS new_requests,
                COALESCE(SUM(CASE WHEN r.expired_date IS NOT NULL AND r.expired_date < NOW()
                                   AND r.final_state IN ('pending','assigned') THEN 1 ELSE 0 END), 0) AS overdue_requests
            FROM student_service s
            LEFT JOIN student_service_request r ON r.service_id = s.id
            GROUP BY s.id
            """
        )