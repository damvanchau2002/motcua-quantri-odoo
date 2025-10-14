from odoo import models, fields, api
from datetime import timedelta


class StudentSystemVisit(models.Model):
    _name = 'student.system.visit'
    _description = 'Lượt truy cập hệ thống theo ngày'

    visit_date = fields.Date(string='Ngày truy cập', required=True, index=True)
    user_id = fields.Many2one('res.users', string='Người dùng', required=True, index=True)

    _sql_constraints = [
        ('unique_daily_visit', 'unique(visit_date, user_id)', 'Mỗi người dùng chỉ được ghi nhận một lượt truy cập mỗi ngày.'),
    ]

    @api.model
    def log_today_visit(self, user_id=None):
        uid = user_id or self.env.user.id
        today = fields.Date.context_today(self)
        existing = self.search([('visit_date', '=', today), ('user_id', '=', uid)], limit=1)
        if not existing:
            self.sudo().create({'visit_date': today, 'user_id': uid})
        return True


class StudentRequestStats(models.Model):
    _name = 'student.request.stats'
    _description = 'Thống kê yêu cầu theo ngày'
    _order = 'stat_date desc'

    stat_date = fields.Date(string='Ngày thống kê', required=True, index=True)

    # Số liệu theo ngày
    new_requests = fields.Integer(string='Yêu cầu mới', default=0)
    created_requests = fields.Integer(string='Yêu cầu tạo', default=0)
    processing_requests = fields.Integer(string='Đang xử lý', default=0)
    overdue_requests = fields.Integer(string='Quá hạn', default=0)
    near_overdue_requests = fields.Integer(string='Gần quá hạn', default=0)
    visits = fields.Integer(string='Lượt truy cập', default=0)

    _sql_constraints = [
        ('unique_stat_date', 'unique(stat_date)', 'Đã có thống kê cho ngày này.'),
    ]

    def _day_bounds(self, day):
        """Trả về khoảng thời gian [start, end) cho một ngày theo timezone người dùng."""
        # fields.Datetime helpers sử dụng timezone context, phù hợp cho thống kê theo ngày
        start = fields.Datetime.to_datetime(day)
        end = start + timedelta(days=1)
        return start, end

    @api.model
    def compute_for_date(self, day):
        """Tính và lưu thống kê cho một ngày cụ thể (idempotent)."""
        start_dt, end_dt = self._day_bounds(day)
        Request = self.env['student.service.request']

        # Yêu cầu tạo trong ngày
        created_count = Request.search_count([
            ('request_date', '>=', start_dt),
            ('request_date', '<', end_dt),
        ])

        # Yêu cầu mới (đồng nhất với created trong ngày)
        new_count = created_count

        # Đang xử lý tạo trong ngày
        processing_count = Request.search_count([
            ('request_date', '>=', start_dt),
            ('request_date', '<', end_dt),
            ('final_state', 'in', ['pending', 'assigned']),
        ])

        # Quá hạn trong ngày: hết hạn trong ngày và vẫn đang xử lý
        overdue_count = Request.search_count([
            ('expired_date', '>=', start_dt),
            ('expired_date', '<', end_dt),
            ('final_state', 'in', ['pending', 'assigned']),
        ])

        # Gần quá hạn: hết hạn trong 24h kể từ đầu ngày
        near_overdue_count = Request.search_count([
            ('expired_date', '>=', start_dt),
            ('expired_date', '<=', start_dt + timedelta(days=1)),
            ('final_state', 'in', ['pending', 'assigned']),
        ])

        # Lượt truy cập theo ngày (mỗi user tối đa 1 lần/ngày)
        visit_count = self.env['student.system.visit'].search_count([
            ('visit_date', '=', day),
        ])

        vals = {
            'stat_date': day,
            'new_requests': new_count,
            'created_requests': created_count,
            'processing_requests': processing_count,
            'overdue_requests': overdue_count,
            'near_overdue_requests': near_overdue_count,
            'visits': visit_count,
        }

        rec = self.search([('stat_date', '=', day)], limit=1)
        if rec:
            rec.write(vals)
        else:
            rec = self.create(vals)
        return rec

    @api.model
    def ensure_range(self, from_date, to_date):
        """Đảm bảo đã có thống kê cho mỗi ngày trong khoảng [from_date, to_date]."""
        if not from_date or not to_date:
            return True
        cur = from_date
        while cur <= to_date:
            self.compute_for_date(cur)
            cur = cur + timedelta(days=1)
        return True

    @api.model
    def cron_compute_daily_stats(self):
        """Cron hằng ngày: tính thống kê cho hôm nay.
        Sử dụng context để tương thích timezone người dùng.
        """
        today = fields.Date.context_today(self)
        self.compute_for_date(today)
        return True