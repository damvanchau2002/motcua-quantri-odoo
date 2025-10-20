from odoo import http, models, fields
from odoo.http import request, Response
from odoo.fields import Datetime
from firebase_admin import messaging, credentials, initialize_app
from firebase_admin import _apps
import requests as py_requests
import json
import base64
import os
import jwt
from datetime import datetime
from datetime import datetime, timedelta

class UserApiController(http.Controller):
    
    # Lấy danh sách users có quyền phân công (từ admin profiles)
    @http.route('/api/users/forassign', type='http', auth='public', methods=['GET','OPTIONS'], csrf=False)
    def get_settings_users(self):
        if request.httprequest.method == 'OPTIONS':
                        return Response(
                            status=200,
                            headers=[
                                ('Access-Control-Allow-Origin', '*'),
                                ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                                ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                                ('Access-Control-Allow-Credentials', 'true'),
                                ('Access-Control-Max-Age', '86400'),  # Cache preflight for 24 hours
                            ]
                        )  
        
        try:
            # Lấy tất cả admin profiles đã được kích hoạt
            admin_profiles = request.env['student.admin.profile'].sudo().search([
                ('activated', '=', True),
                ('user_id', '!=', False)  # Đảm bảo có user_id
            ])
            
            if not admin_profiles:
                return Response(
                    json.dumps({'success': False, 'message': 'Không tìm thấy admin profiles nào được kích hoạt', 'data': []}),
                    content_type='application/json',
                    status=404,
                    headers=[
                        ('Access-Control-Allow-Origin', '*'),
                        ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                        ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                        ('Access-Control-Allow-Credentials', 'true'),
                    ]
                )
            
            # Lấy danh sách users từ admin profiles
            admin_users = admin_profiles.mapped('user_id')
            
            # Loại bỏ student users (nếu có)
            student_users = request.env['student.user.profile'].sudo().search([]).mapped('user_id')
            final_users = admin_users - student_users
            
            # Lọc chỉ lấy users active
            final_users = final_users.filtered(lambda u: u.active)
            
            # Tạo response data với thông tin chi tiết
            data = []
            for user in final_users:
                admin_profile = admin_profiles.filtered(lambda p: p.user_id.id == user.id)[:1]
                
                # Kiểm tra quyền của user thông qua has_group
                is_manager = user.has_group('student_request.group_student_request_manager')
                is_user = user.has_group('student_request.group_student_request_user')
                
                user_data = {
                    'id': user.id,
                    'name': user.name,
                    'login': user.login,
                    'email': user.email,
                    'is_manager': is_manager,
                    'is_user': is_user,
                    'department_name': admin_profile.department_id.name if admin_profile and admin_profile.department_id else '',
                    'role_names': ', '.join(admin_profile.role_ids.mapped('name')) if admin_profile and admin_profile.role_ids else '',
                    'activated': admin_profile.activated if admin_profile else False
                }
                data.append(user_data)
            
            return Response(
                json.dumps({'success': True, 'message': f'Danh sách {len(data)} users có quyền phân công', 'data': data}),
                content_type='application/json',
                status=200,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true'),
                ]
            )
            
        except Exception as e:
            return Response(
                json.dumps({'success': False, 'message': f'Lỗi khi lấy danh sách users: {str(e)}', 'data': []}),
                content_type='application/json',
                status=500,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true'),
                ]
            )

    # Lấy danh sách các department
    @http.route('/api/department/forassign', type='http', auth='public', methods=['GET','OPTIONS'], csrf=False)
    def get_departments(self):
        if request.httprequest.method == 'OPTIONS':
                        return Response(
                            status=200,
                            headers=[
                                ('Access-Control-Allow-Origin', '*'),
                                ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                                ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                                ('Access-Control-Allow-Credentials', 'true'),
                                ('Access-Control-Max-Age', '86400'),  # Cache preflight for 24 hours
                            ]
                        )
        departments = request.env['student.activity.department'].sudo().search([])
        data = [{'id': d.id, 'name': d.name} for d in departments]
        return Response(
            json.dumps({'success': True, 'message': 'Danh sách các department', 'data': data}),
            content_type='application/json',
            status=200,
            headers=[
                ('Access-Control-Allow-Origin', '*'),
                ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ('Access-Control-Allow-Credentials', 'true'),
            ]
        )

    def _get_active_step_info(self, request_id):
        """Lấy thông tin bước xử lý hiện tại của request"""
        import logging
        _logger = logging.getLogger(__name__)
        
        try:
            if not request_id:
                return {
                    'request_id': None,
                    'error': 'no_request_id',
                    'message': 'Không có request_id được cung cấp'
                }
            
            # Tìm service request
            service_request = request.env['student.service.request'].with_user(1).sudo().search([
                ('id', '=', request_id)
            ], limit=1)
            
            if not service_request:
                return {
                    'request_id': request_id,
                    'error': 'request_not_found',
                    'message': f'Không tìm thấy request với ID {request_id}'
                }
            
            # Lấy tất cả steps của request
            all_steps = service_request.step_ids.with_user(1).sudo()
            
            # Tìm active steps (pending hoặc assigned)
            active_steps = all_steps.filtered(lambda s: s.state in ['pending', 'assigned'])
            
            _logger.info(f"Request {request_id} có {len(all_steps)} steps tổng cộng")
            for step in all_steps:
                _logger.info(f"  Step {step.id}: {step.display_step_name}, state: {step.state}, sequence: {step.base_secquence}")
            
            _logger.info(f"Tìm thấy {len(active_steps)} active steps (pending/assigned)")
            
            # Lấy step hiện tại (step đầu tiên theo sequence)
            current_step = active_steps.sorted(lambda s: s.base_secquence)[0] if active_steps else None
            
            if current_step:
                _logger.info(f"Active step: {current_step.display_step_name} (ID: {current_step.id})")
                return {
                    'request_id': service_request.id,
                    'request_code': service_request.name,
                    'request_state': service_request.final_state,
                    'current_step_id': current_step.id,
                    'current_step_name': current_step.display_step_name,
                    'current_step_state': current_step.state,
                    'current_step_sequence': current_step.base_secquence,
                    'current_department_id': current_step.department_id.id if current_step.department_id else None,
                    'current_department_name': current_step.department_id.name if current_step.department_id else '',
                    'step_department_id': current_step.base_step_id.department_id.id if current_step.base_step_id and current_step.base_step_id.department_id else None,
                    'step_department_name': current_step.base_step_id.department_id.name if current_step.base_step_id and current_step.base_step_id.department_id else '',
                    'assign_user_id': current_step.assign_user_id.id if current_step.assign_user_id else None,
                    'assign_user_name': current_step.assign_user_id.name if current_step.assign_user_id else '',
                    'is_active_step': True
                }
            else:
                _logger.info(f"Không tìm thấy active step cho request {request_id}")
                return {
                    'request_id': service_request.id,
                    'request_code': service_request.name,
                    'request_state': service_request.final_state,
                    'current_step_id': None,
                    'current_step_name': '',
                    'current_step_state': '',
                    'current_step_sequence': 0,
                    'current_department_id': None,
                    'current_department_name': '',
                    'step_department_id': None,
                    'step_department_name': '',
                    'assign_user_id': None,
                    'assign_user_name': '',
                    'is_active_step': False
                }
                
        except Exception as e:
            _logger.error(f"Lỗi khi lấy active step info cho request {request_id}: {str(e)}")
            return {
                'request_id': request_id,
                'error': 'exception',
                'message': f'Lỗi khi xử lý request: {str(e)}'
            }

    # Lấy danh sách người phân công theo department_id
    @http.route('/api/users/forassign/department/<int:department_id>', type='http', auth='public', methods=['GET','OPTIONS'], csrf=False)
    def get_users_by_department(self, department_id):
        if request.httprequest.method == 'OPTIONS':
            return Response(
                status=200,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true'),
                    ('Access-Control-Max-Age', '86400'),  # Cache preflight for 24 hours
                ]
            )
        
        try:
            # Kiểm tra department có tồn tại không
            department = request.env['student.activity.department'].sudo().browse(department_id)
            if not department.exists():
                return Response(
                    json.dumps({'success': False, 'message': f'Không tìm thấy phòng ban với ID {department_id}', 'data': []}),
                    content_type='application/json',
                    status=404,
                    headers=[
                        ('Access-Control-Allow-Origin', '*'),
                        ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                        ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                        ('Access-Control-Allow-Credentials', 'true'),
                    ]
                )
            
            # Lấy admin profiles thuộc department này và đã được kích hoạt
            admin_profiles = request.env['student.admin.profile'].sudo().search([
                ('department_id', '=', department_id),
                ('activated', '=', True),
                ('user_id', '!=', False)  # Đảm bảo có user_id
            ])
            
            if not admin_profiles:
                return Response(
                    json.dumps({'success': True, 'message': f'Không có người phân công nào trong phòng ban "{department.name}"', 'data': []}),
                    content_type='application/json',
                    status=200,
                    headers=[
                        ('Access-Control-Allow-Origin', '*'),
                        ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                        ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                        ('Access-Control-Allow-Credentials', 'true'),
                    ]
                )
            
            # Lấy danh sách users từ admin profiles
            admin_users = admin_profiles.mapped('user_id')
            
            # Loại bỏ student users (nếu có)
            student_users = request.env['student.user.profile'].sudo().search([]).mapped('user_id')
            final_users = admin_users - student_users
            
            # Lọc chỉ lấy users active
            final_users = final_users.filtered(lambda u: u.active)
            
            # Tạo response data với thông tin chi tiết
            data = []
            for user in final_users:
                admin_profile = admin_profiles.filtered(lambda p: p.user_id.id == user.id)[:1]
                
                # Kiểm tra quyền của user thông qua has_group
                is_manager = user.has_group('student_request.group_student_request_manager')
                is_user = user.has_group('student_request.group_student_request_user')
                
                user_data = {
                    'id': user.id,
                    'name': user.name,
                    'login': user.login,
                    'email': user.email,
                    'phone': user.phone if hasattr(user, 'phone') else '',
                    'is_manager': is_manager,
                    'is_user': is_user,
                    'department_id': department_id,
                    'department_name': department.name,
                    'role_names': ', '.join(admin_profile.role_ids.mapped('name')) if admin_profile and admin_profile.role_ids else '',
                    'activated': admin_profile.activated if admin_profile else False,
                    'title_name': admin_profile.title_name if admin_profile else '',
                    'profile_id': admin_profile.id if admin_profile else None,
                    'last_login': user.login_date.strftime('%Y-%m-%d %H:%M:%S') if user.login_date else ''
                }
                data.append(user_data)
            
            # Lấy request_id từ query parameters
            request_id = request.httprequest.args.get('request_id')
            if request_id:
                try:
                    request_id = int(request_id)
                except ValueError:
                    request_id = None
            
            # Lấy thông tin active step
            active_step_info = self._get_active_step_info(request_id)
            
            return Response(
                json.dumps({
                    'success': True, 
                    'message': f'Danh sách {len(data)} người phân công trong phòng ban "{department.name}"', 
                    'data': data,
                    'department': {
                        'id': department.id,
                        'name': department.name,
                        'description': department.description,
                        'active': department.active if hasattr(department, 'active') else True
                    },
                    'active_step_info': active_step_info,
                    'total_users': len(data),
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }),
                content_type='application/json',
                status=200,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true'),
                ]
            )
            
        except Exception as e:
            return Response(
                json.dumps({'success': False, 'message': f'Lỗi khi lấy danh sách người phân công theo phòng ban: {str(e)}', 'data': []}),
                content_type='application/json',
                status=500,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true'),
                ]
            )
    
