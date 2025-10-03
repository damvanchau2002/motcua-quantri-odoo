import json
import logging
from datetime import datetime, timedelta
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class MaintenanceAPI(http.Controller):
    
    @http.route('/api/maintenance/status', type='http', auth='none', methods=['GET', 'OPTIONS'], csrf=False, cors='*')
    def get_maintenance_status(self, **kwargs):
        """
        API để lấy trạng thái bảo trì hiện tại
        GET /api/maintenance/status
        
        Response:
        {
            "status": "on/off",
            "message": "Nội dung thông báo",
            "duration": "Thời gian dự kiến",
            "start_time": "2024-01-01T10:00:00",
            "end_time": "2024-01-01T12:00:00"
        }
        """
        try:
            # Handle CORS preflight request
            if request.httprequest.method == 'OPTIONS':
                response = request.make_response('', headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ])
                return response

            # Lấy thông tin bảo trì từ ir.config_parameter
            config_param = request.env['ir.config_parameter'].sudo()
            
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
                    if datetime.now() > end_time:
                        # Tự động tắt bảo trì khi hết thời gian
                        config_param.set_param('maintenance.status', 'off')
                        maintenance_status = 'off'
                except:
                    pass
            
            response_data = {
                'status': maintenance_status,
                'message': maintenance_message,
                'duration': maintenance_duration,
                'start_time': maintenance_start_time if maintenance_start_time else None,
                'end_time': maintenance_end_time if maintenance_end_time else None,
            }
            
            response = request.make_response(
                json.dumps(response_data, ensure_ascii=False),
                headers=[
                    ('Content-Type', 'application/json; charset=utf-8'),
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )
            return response
            
        except Exception as e:
            _logger.error(f"Error in get_maintenance_status: {str(e)}")
            error_response = {
                'error': 'Lỗi hệ thống',
                'message': str(e)
            }
            response = request.make_response(
                json.dumps(error_response, ensure_ascii=False),
                headers=[
                    ('Content-Type', 'application/json; charset=utf-8'),
                    ('Access-Control-Allow-Origin', '*'),
                ]
            )
            response.status_code = 500
            return response

    @http.route('/api/maintenance/set', type='http', auth='user', methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    def set_maintenance_status(self, **kwargs):
        """
        API để cập nhật trạng thái bảo trì (chỉ admin)
        POST /api/maintenance/set
        
        Body:
        {
            "status": "on/off",
            "message": "Nội dung thông báo (optional)",
            "duration": "Thời gian dự kiến (optional)"
        }
        
        Response:
        {
            "success": true,
            "status": "on/off",
            "message": "Thông báo",
            "duration": "Thời gian"
        }
        """
        try:
            # Handle CORS preflight request
            if request.httprequest.method == 'OPTIONS':
                response = request.make_response('', headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ])
                return response

            # Kiểm tra quyền admin
            if not request.env.user.has_group('base.group_system'):
                error_response = {
                    'error': 'Không có quyền thực hiện thao tác này',
                    'message': 'Chỉ admin mới có thể thay đổi trạng thái bảo trì'
                }
                response = request.make_response(
                    json.dumps(error_response, ensure_ascii=False),
                    headers=[
                        ('Content-Type', 'application/json; charset=utf-8'),
                        ('Access-Control-Allow-Origin', '*'),
                    ]
                )
                response.status_code = 403
                return response

            # Lấy dữ liệu từ request
            data = json.loads(request.httprequest.data.decode('utf-8'))
            status = data.get('status', 'off')
            message = data.get('message', 'Hệ thống đang được bảo trì, vui lòng quay lại sau.')
            duration = data.get('duration', '30 phút')
            
            # Validate status
            if status not in ['on', 'off']:
                error_response = {
                    'error': 'Trạng thái không hợp lệ',
                    'message': 'Status phải là "on" hoặc "off"'
                }
                response = request.make_response(
                    json.dumps(error_response, ensure_ascii=False),
                    headers=[
                        ('Content-Type', 'application/json; charset=utf-8'),
                        ('Access-Control-Allow-Origin', '*'),
                    ]
                )
                response.status_code = 400
                return response

            # Cập nhật thông tin bảo trì
            config_param = request.env['ir.config_parameter'].sudo()
            config_param.set_param('maintenance.status', status)
            config_param.set_param('maintenance.message', message)
            config_param.set_param('maintenance.duration', duration)
            
            # Cập nhật thời gian
            current_time = datetime.now().isoformat()
            if status == 'on':
                config_param.set_param('maintenance.start_time', current_time)
                
                # Tính toán thời gian kết thúc dựa trên duration
                try:
                    end_time = None
                    if 'phút' in duration.lower():
                        minutes = int(''.join(filter(str.isdigit, duration)))
                        end_time = datetime.now() + timedelta(minutes=minutes)
                    elif 'giờ' in duration.lower():
                        hours = int(''.join(filter(str.isdigit, duration)))
                        end_time = datetime.now() + timedelta(hours=hours)
                    elif 'ngày' in duration.lower():
                        days = int(''.join(filter(str.isdigit, duration)))
                        end_time = datetime.now() + timedelta(days=days)
                    
                    if end_time:
                        config_param.set_param('maintenance.end_time', end_time.isoformat())
                except Exception as e:
                    _logger.warning(f"Could not parse duration: {duration}, error: {str(e)}")
            else:
                # Khi tắt bảo trì, cập nhật thời gian kết thúc
                config_param.set_param('maintenance.end_time', current_time)
            
            response_data = {
                'success': True,
                'status': status,
                'message': message,
                'duration': duration,
                'timestamp': current_time
            }
            
            response = request.make_response(
                json.dumps(response_data, ensure_ascii=False),
                headers=[
                    ('Content-Type', 'application/json; charset=utf-8'),
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )
            return response
            
        except json.JSONDecodeError:
            error_response = {
                'error': 'Dữ liệu JSON không hợp lệ',
                'message': 'Vui lòng kiểm tra định dạng JSON'
            }
            response = request.make_response(
                json.dumps(error_response, ensure_ascii=False),
                headers=[
                    ('Content-Type', 'application/json; charset=utf-8'),
                    ('Access-Control-Allow-Origin', '*'),
                ]
            )
            response.status_code = 400
            return response
            
        except Exception as e:
            _logger.error(f"Error in set_maintenance_status: {str(e)}")
            error_response = {
                'error': 'Lỗi hệ thống',
                'message': str(e)
            }
            response = request.make_response(
                json.dumps(error_response, ensure_ascii=False),
                headers=[
                    ('Content-Type', 'application/json; charset=utf-8'),
                    ('Access-Control-Allow-Origin', '*'),
                ]
            )
            response.status_code = 500
            return response

    @http.route('/api/maintenance/toggle', type='http', auth='user', methods=['POST', 'OPTIONS'], csrf=False, cors='*')
    def toggle_maintenance_status(self, **kwargs):
        """
        API để chuyển đổi trạng thái bảo trì (on <-> off)
        POST /api/maintenance/toggle
        
        Response:
        {
            "success": true,
            "status": "on/off",
            "message": "Thông báo"
        }
        """
        try:
            # Handle CORS preflight request
            if request.httprequest.method == 'OPTIONS':
                response = request.make_response('', headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ])
                return response

            # Kiểm tra quyền admin
            if not request.env.user.has_group('base.group_system'):
                error_response = {
                    'error': 'Không có quyền thực hiện thao tác này',
                    'message': 'Chỉ admin mới có thể thay đổi trạng thái bảo trì'
                }
                response = request.make_response(
                    json.dumps(error_response, ensure_ascii=False),
                    headers=[
                        ('Content-Type', 'application/json; charset=utf-8'),
                        ('Access-Control-Allow-Origin', '*'),
                    ]
                )
                response.status_code = 403
                return response

            # Lấy trạng thái hiện tại
            config_param = request.env['ir.config_parameter'].sudo()
            current_status = config_param.get_param('maintenance.status', 'off')
            
            # Chuyển đổi trạng thái
            new_status = 'off' if current_status == 'on' else 'on'
            
            # Gọi API set để cập nhật
            data = {
                'status': new_status,
                'message': config_param.get_param('maintenance.message', 
                    'Hệ thống đang được bảo trì, vui lòng quay lại sau.'),
                'duration': config_param.get_param('maintenance.duration', '30 phút')
            }
            
            # Simulate request data for set_maintenance_status
            original_data = request.httprequest.data
            request.httprequest.data = json.dumps(data).encode('utf-8')
            
            result = self.set_maintenance_status()
            
            # Restore original data
            request.httprequest.data = original_data
            
            return result
            
        except Exception as e:
            _logger.error(f"Error in toggle_maintenance_status: {str(e)}")
            error_response = {
                'error': 'Lỗi hệ thống',
                'message': str(e)
            }
            response = request.make_response(
                json.dumps(error_response, ensure_ascii=False),
                headers=[
                    ('Content-Type', 'application/json; charset=utf-8'),
                    ('Access-Control-Allow-Origin', '*'),
                ]
            )
            response.status_code = 500
            return response