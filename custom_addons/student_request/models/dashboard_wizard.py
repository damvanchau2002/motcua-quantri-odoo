from odoo import api, fields, models
from datetime import timedelta


class StudentRequestStatsWizard(models.TransientModel):
    _name = 'student.request.stats.wizard'
    _description = 'Wizard tổng hợp thống kê yêu cầu'

    period = fields.Selection([
        ('day', 'Ngày'),
        ('week', 'Tuần'),
        ('month', 'Tháng'),
        ('year', 'Năm'),
    ], string='Khoảng thời gian', default='month')

    date_from = fields.Date(string='Từ ngày')
    date_to = fields.Date(string='Đến ngày')

    total_requests = fields.Integer(string='Tổng yêu cầu', compute='_compute_summary', store=False)
    processing_requests = fields.Integer(string='Đang xử lý', compute='_compute_summary', store=False)
    overdue_requests = fields.Integer(string='Quá hạn', compute='_compute_summary', store=False)
    near_overdue_requests = fields.Integer(string='Gần quá hạn', compute='_compute_summary', store=False)
    avg_daily_users = fields.Float(string='Người dùng trung bình/ngày', compute='_compute_summary', store=False)
    avg_requests_per_day = fields.Float(string='Trung bình yêu cầu/ngày', compute='_compute_summary', store=False)

    @api.onchange('period')
    def _onchange_period(self):
        today = fields.Date.today()
        if self.period == 'day':
            self.date_to = today
            self.date_from = today - timedelta(days=6)
        elif self.period == 'week':
            self.date_to = today
            self.date_from = today - timedelta(weeks=7)
        elif self.period == 'month':
            self.date_to = today
            self.date_from = today - timedelta(days=30)
        elif self.period == 'year':
            self.date_to = today
            self.date_from = today.replace(year=today.year - 1)

    def _ensure_stats_range(self, date_from, date_to):
        Stats = self.env['student.request.stats'].sudo()
        # Gọi đúng API của model, đảm bảo thống kê cho toàn khoảng ngày
        Stats.ensure_range(date_from, date_to)

    @api.depends('date_from', 'date_to')
    def _compute_summary(self):
        for w in self:
            if not w.date_from or not w.date_to:
                w.total_requests = 0
                w.processing_requests = 0
                w.overdue_requests = 0
                w.near_overdue_requests = 0
                w.avg_daily_users = 0.0
                w.avg_requests_per_day = 0.0
                continue

            w._ensure_stats_range(w.date_from, w.date_to)
            Stats = self.env['student.request.stats'].sudo()
            stats = Stats.search([
                ('stat_date', '>=', w.date_from),
                ('stat_date', '<=', w.date_to),
            ])
            days = len(stats)
            total_req = sum(s.created_requests for s in stats)
            total_visits = sum(s.visits for s in stats)

            Request = self.env['student.service.request'].sudo()
            now = fields.Datetime.now()
            processing_count = Request.search_count([('final_state', '=', 'assigned')])
            overdue_count = Request.search_count([
                ('final_state', 'in', ['pending', 'assigned']),
                ('expired_date', '!=', False),
                ('expired_date', '<', now),
            ])
            near_overdue_count = Request.search_count([
                ('final_state', 'in', ['pending', 'assigned']),
                ('expired_date', '!=', False),
                ('expired_date', '>=', now),
                ('expired_date', '<=', now + timedelta(days=1)),
            ])

            w.total_requests = total_req
            w.processing_requests = processing_count
            w.overdue_requests = overdue_count
            w.near_overdue_requests = near_overdue_count
            w.avg_daily_users = round(total_visits / max(days, 1), 2)
            w.avg_requests_per_day = round(total_req / max(days, 1), 2)

    def _action_open_graph(self, measures):
        self.ensure_one()
        context = dict(self.env.context)
        # Apply group_by according to selected period
        if self.period in ('day', 'week', 'month', 'year'):
            context['group_by'] = f'stat_date:{self.period}'
        action = self.env.ref('student_request.action_student_request_stats_graph').sudo().read()[0]
        action['domain'] = [('stat_date', '>=', self.date_from), ('stat_date', '<=', self.date_to)]
        # Graph view shows all measures defined; we can keep measures parameter for future use
        action['context'] = context
        return action

    def action_open_status_graph(self):
        return self._action_open_graph(['new_requests', 'processing_requests', 'overdue_requests', 'near_overdue_requests'])

    def action_open_visits_graph(self):
        action = self.env.ref('student_request.action_student_request_stats_graph').sudo().read()[0]
        action['domain'] = [('stat_date', '>=', self.date_from), ('stat_date', '<=', self.date_to)]
        action['context'] = dict(self.env.context, group_by=f'stat_date:{self.period}')
        # Use a dedicated graph view for visits/created_requests if needed; fallback to main graph
        # To focus on visits, users can toggle measures in graph UI
        return action