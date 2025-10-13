import json
import logging
from datetime import datetime, timedelta, timezone
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
            
            # Chuẩn hóa thời gian để tránh trường hợp start_time > end_time hoặc thiếu end_time
            def _parse_duration(duration_str):
                try:
                    d = (duration_str or '').lower()
                    if 'phút' in d:
                        minutes = int(''.join(filter(str.isdigit, d)))
                        return timedelta(minutes=minutes)
                    if 'giờ' in d:
                        hours = int(''.join(filter(str.isdigit, d)))
                        return timedelta(hours=hours)
                    if 'ngày' in d:
                        days = int(''.join(filter(str.isdigit, d)))
                        return timedelta(days=days)
                except Exception:
                    return None
                return None
            
            def _iso_to_dt(iso_str):
                try:
                    s = (iso_str or '')
                    if not s:
                        return None
                    dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
                    # Đảm bảo timezone-aware theo UTC để so sánh đúng
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    else:
                        dt = dt.astimezone(timezone.utc)
                    return dt
                except Exception:
                    return None
            
            def _dt_to_iso_utc(dt):
                try:
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    else:
                        dt = dt.astimezone(timezone.utc)
                    return dt.isoformat().replace('+00:00', 'Z')
                except Exception:
                    return None
            
            try:
                if maintenance_status == 'on':
                    now_utc = datetime.now(timezone.utc)
                    # Bổ sung start_time nếu thiếu
                    if not maintenance_start_time:
                        maintenance_start_time = _dt_to_iso_utc(now_utc)
                        config_param.set_param('maintenance.start_time', maintenance_start_time)
                    start_dt = _iso_to_dt(maintenance_start_time)
                    # Bổ sung hoặc sửa end_time nếu thiếu hoặc nhỏ hơn start_time
                    end_dt = _iso_to_dt(maintenance_end_time)
                    if end_dt is None or (start_dt and end_dt < start_dt):
                        td = _parse_duration(maintenance_duration) or timedelta(minutes=30)
                        end_dt = (start_dt or now_utc) + td
                        maintenance_end_time = _dt_to_iso_utc(end_dt)
                        config_param.set_param('maintenance.end_time', maintenance_end_time)
                else:
                    # Khi status = off, nếu end_time < start_time thì đưa end_time về start_time để tránh nghịch lý
                    start_dt = _iso_to_dt(maintenance_start_time)
                    end_dt = _iso_to_dt(maintenance_end_time)
                    if start_dt and end_dt and end_dt < start_dt:
                        maintenance_end_time = maintenance_start_time
                        config_param.set_param('maintenance.end_time', maintenance_end_time)
            except Exception as _norm_e:
                _logger.warning(f"Normalization maintenance times failed: {str(_norm_e)}")
            
            # Kiểm tra nếu thời gian bảo trì đã hết (so sánh timezone-aware UTC)
            if maintenance_status == 'on' and maintenance_end_time:
                try:
                    end_dt = _iso_to_dt(maintenance_end_time)
                    now_utc = datetime.now(timezone.utc)
                    if end_dt and now_utc > end_dt:
                        # Tự động tắt bảo trì khi hết thời gian, đồng thời chuẩn hoá lại end_time
                        config_param.set_param('maintenance.status', 'off')
                        maintenance_status = 'off'
                        maintenance_end_time = _dt_to_iso_utc(end_dt)
                        config_param.set_param('maintenance.end_time', maintenance_end_time)
                except Exception as _auto_off_e:
                    _logger.warning(f"Auto-off maintenance compare failed: {str(_auto_off_e)}")
            
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
            
            # Cập nhật thời gian (UTC + 'Z')
            current_time = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
            if status == 'on':
                config_param.set_param('maintenance.start_time', current_time)
                
                # Tính toán thời gian kết thúc dựa trên duration
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
                        config_param.set_param('maintenance.end_time', end_time.isoformat().replace('+00:00', 'Z'))
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