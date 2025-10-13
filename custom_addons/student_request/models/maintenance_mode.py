from odoo import models, fields, api
from datetime import datetime, timedelta, timezone
import logging

_logger = logging.getLogger(__name__)


class ConfigParameter(models.Model):
    _inherit = 'ir.config_parameter'

    # Computed fields cho maintenance mode
    maintenance_status = fields.Selection([
        ('on', 'Bật'),
        ('off', 'Tắt')
    ], string='Trạng thái bảo trì', compute='_compute_maintenance_fields', 
       inverse='_inverse_maintenance_status', default='off')
    
    maintenance_message = fields.Text(
        string='Thông báo bảo trì', 
        compute='_compute_maintenance_fields',
        inverse='_inverse_maintenance_message',
        default='Hệ thống đang được bảo trì, vui lòng quay lại sau.'
    )
    
    maintenance_duration = fields.Char(
        string='Thời gian dự kiến',
        compute='_compute_maintenance_fields',
        inverse='_inverse_maintenance_duration',
        default='30 phút'
    )
    
    maintenance_start_time = fields.Datetime(
        string='Thời gian bắt đầu',
        compute='_compute_maintenance_fields',
        readonly=True
    )
    
    maintenance_end_time = fields.Datetime(
        string='Thời gian kết thúc dự kiến',
        compute='_compute_maintenance_fields',
        readonly=True
    )

    @api.depends('key', 'value')
    def _compute_maintenance_fields(self):
        """Compute maintenance fields từ config parameters"""
        for record in self:
            # Lấy các giá trị từ config parameters
            status = self.env['ir.config_parameter'].sudo().get_param('maintenance.status', 'off')
            message = self.env['ir.config_parameter'].sudo().get_param('maintenance.message', 
                'Hệ thống đang được bảo trì, vui lòng quay lại sau.')
            duration = self.env['ir.config_parameter'].sudo().get_param('maintenance.duration', '30 phút')
            start_time_str = self.env['ir.config_parameter'].sudo().get_param('maintenance.start_time', '')
            end_time_str = self.env['ir.config_parameter'].sudo().get_param('maintenance.end_time', '')
            
            record.maintenance_status = status
            record.maintenance_message = message
            record.maintenance_duration = duration
            
            # Parse datetime strings
            try:
                if start_time_str:
                    record.maintenance_start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                else:
                    record.maintenance_start_time = False
            except:
                record.maintenance_start_time = False
                
            try:
                if end_time_str:
                    record.maintenance_end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
                else:
                    record.maintenance_end_time = False
            except:
                record.maintenance_end_time = False

    def _inverse_maintenance_status(self):
        """Inverse method cho maintenance_status"""
        for record in self:
            self.env['ir.config_parameter'].sudo().set_param('maintenance.status', record.maintenance_status)
            self._update_maintenance_times(record.maintenance_status)

    def _inverse_maintenance_message(self):
        """Inverse method cho maintenance_message"""
        for record in self:
            self.env['ir.config_parameter'].sudo().set_param('maintenance.message', record.maintenance_message)

    def _inverse_maintenance_duration(self):
        """Inverse method cho maintenance_duration"""
        for record in self:
            self.env['ir.config_parameter'].sudo().set_param('maintenance.duration', record.maintenance_duration)

    def _update_maintenance_times(self, status):
        """Cập nhật thời gian bảo trì"""
        # Lưu thời gian theo UTC với hậu tố 'Z' để đồng bộ API/UI
        current_time = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        if status == 'on':
            # Bắt đầu bảo trì
            self.env['ir.config_parameter'].sudo().set_param('maintenance.start_time', current_time)
            
            # Tính toán thời gian kết thúc
            duration = self.env['ir.config_parameter'].sudo().get_param('maintenance.duration', '30 phút')
            try:
                end_time = None
                if 'phút' in duration.lower():
                    minutes = int(''.join(filter(str.isdigit, duration)))
                    end_time = datetime.now(timezone.utc) + timedelta(minutes=minutes)
                elif 'giờ' in duration.lower():
                    hours = int(''.join(filter(str.isdigit, duration)))
                    end_time = datetime.now(timezone.utc) + timedelta(hours=hours)
                elif 'ngày' in duration.lower():
                    days = int(''.join(filter(str.isdigit, duration)))
                    end_time = datetime.now(timezone.utc) + timedelta(days=days)
                
                if end_time:
                    self.env['ir.config_parameter'].sudo().set_param('maintenance.end_time', end_time.isoformat().replace('+00:00', 'Z'))
            except Exception as e:
                _logger.warning(f"Could not parse duration: {duration}, error: {str(e)}")
        else:
            # Kết thúc bảo trì
            self.env['ir.config_parameter'].sudo().set_param('maintenance.end_time', current_time)

    def toggle_maintenance_mode(self):
        """Button action để toggle maintenance mode"""
        current_status = self.env['ir.config_parameter'].sudo().get_param('maintenance.status', 'off')
        new_status = 'off' if current_status == 'on' else 'on'
        
        self.env['ir.config_parameter'].sudo().set_param('maintenance.status', new_status)
        self._update_maintenance_times(new_status)
        
        # Refresh view
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    @api.model
    def get_maintenance_status_api(self):
        """API method để lấy trạng thái bảo trì"""
        config_param = self.env['ir.config_parameter'].sudo()
        
        # Lấy các thông số bảo trì
        maintenance_status = config_param.get_param('maintenance.status', 'off')
        maintenance_message = config_param.get_param('maintenance.message', 
            'Hệ thống đang được bảo trì, vui lòng quay lại sau.')
        maintenance_duration = config_param.get_param('maintenance.duration', '30 phút')
        maintenance_start_time = config_param.get_param('maintenance.start_time', '')
        maintenance_end_time = config_param.get_param('maintenance.end_time', '')
        
        # Kiểm tra nếu thời gian bảo trì đã hết
        if maintenance_status == 'on' and maintenance_end_time:
            try:
                end_time = datetime.fromisoformat(maintenance_end_time.replace('Z', '+00:00'))
                now_utc = datetime.now(timezone.utc)
                if now_utc > end_time:
                    # Tự động tắt bảo trì khi hết thời gian
                    config_param.set_param('maintenance.status', 'off')
                    maintenance_status = 'off'
            except:
                pass
        
        return {
            'status': maintenance_status,
            'message': maintenance_message,
            'duration': maintenance_duration,
            'start_time': maintenance_start_time if maintenance_start_time else None,
            'end_time': maintenance_end_time if maintenance_end_time else None,
        }

    @api.model
    def set_maintenance_status_api(self, status, message=None, duration=None):
        """API method để cập nhật trạng thái bảo trì"""
        if status not in ['on', 'off']:
            raise ValueError('Status phải là "on" hoặc "off"')
        
        config_param = self.env['ir.config_parameter'].sudo()
        
        # Set default values
        if message is None:
            message = 'Hệ thống đang được bảo trì, vui lòng quay lại sau.'
        if duration is None:
            duration = '30 phút'
        
        # Cập nhật thông tin bảo trì
        config_param.set_param('maintenance.status', status)
        config_param.set_param('maintenance.message', message)
        config_param.set_param('maintenance.duration', duration)
        
        # Cập nhật thời gian
        self._update_maintenance_times(status)
        
        return {
            'success': True,
            'status': status,
            'message': message,
            'duration': duration,
            'timestamp': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        }