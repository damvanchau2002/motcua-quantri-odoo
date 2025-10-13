from odoo import models, fields, api


class MaintenanceDashboard(models.TransientModel):
    _name = 'maintenance.dashboard'
    _description = 'Maintenance Dashboard Holder'


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