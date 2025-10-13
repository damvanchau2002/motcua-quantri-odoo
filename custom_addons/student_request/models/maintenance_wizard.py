from odoo import models, fields, api


class MaintenanceDashboard(models.TransientModel):
    _name = 'maintenance.dashboard'
    _description = 'Maintenance Dashboard Holder'

    # Các field hiển thị thông tin trạng thái để dùng trong view
    status_text = fields.Char(string='Trạng thái', compute='_compute_dashboard_info')
    message_text = fields.Text(string='Thông báo', compute='_compute_dashboard_info')
    updated_text = fields.Char(string='Cập nhật', compute='_compute_dashboard_info')

    def _compute_dashboard_info(self):
        ICP = self.env['ir.config_parameter'].sudo()
        status = ICP.get_param('maintenance.status', 'off')
        message = ICP.get_param('maintenance.message', '')
        start_time = ICP.get_param('maintenance.start_time', '')
        end_time = ICP.get_param('maintenance.end_time', '')

        if status == 'on':
            status_label = '🔴 Đang bảo trì'
            when = start_time or ''
            prefix = 'Bắt đầu: '
        else:
            status_label = '🟢 Hoạt động bình thường'
            when = end_time or ''
            prefix = 'Kết thúc: '

        updated = f"{prefix}{when}" if when else 'Chưa có thông tin thời gian'

        for rec in self:
            rec.status_text = status_label
            rec.message_text = message or '—'
            rec.updated_text = updated

    # Khối field hiển thị chi tiết trạng thái giống simple dashboard
    maintenance_status = fields.Selection([
        ('on', 'Bật'),
        ('off', 'Tắt')
    ], string='Trạng thái bảo trì', compute='_compute_status_block', readonly=True)

    maintenance_message = fields.Text(string='Thông báo bảo trì', compute='_compute_status_block', readonly=True)
    maintenance_duration = fields.Char(string='Thời gian dự kiến', compute='_compute_status_block', readonly=True)
    maintenance_start_time = fields.Char(string='Thời gian bắt đầu', compute='_compute_status_block', readonly=True)
    maintenance_end_time = fields.Char(string='Thời gian kết thúc dự kiến', compute='_compute_status_block', readonly=True)

    def _compute_status_block(self):
        ICP = self.env['ir.config_parameter'].sudo()
        status = ICP.get_param('maintenance.status', 'off')
        message = ICP.get_param('maintenance.message', '')
        duration = ICP.get_param('maintenance.duration', '')
        start_time = ICP.get_param('maintenance.start_time', '')
        end_time = ICP.get_param('maintenance.end_time', '')

        for rec in self:
            rec.maintenance_status = status
            rec.maintenance_message = message or ''
            rec.maintenance_duration = duration or ''
            rec.maintenance_start_time = start_time or ''
            rec.maintenance_end_time = end_time or ''


class MaintenanceMessageWizard(models.TransientModel):
    _name = 'maintenance.message.wizard'
    _description = 'Wizard to edit maintenance message'

    message = fields.Text(string='Thông báo', default=lambda self: self._default_message())

    @api.model
    def _default_message(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            'maintenance.message', 'Hệ thống đang bảo trì, vui lòng quay lại sau'
        )

    def action_save(self):
        self.ensure_one()
        self.env['ir.config_parameter'].sudo().set_param('maintenance.message', self.message or '')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '📝 Đã cập nhật thông báo',
                'message': 'Thông báo bảo trì đã được lưu',
                'type': 'success',
                'sticky': False,
            }
        }