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
    
