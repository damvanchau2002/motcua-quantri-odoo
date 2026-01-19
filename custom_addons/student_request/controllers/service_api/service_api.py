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

class ServiceApiController(http.Controller):

    def _get_cors_headers(self):
        origin = request.httprequest.headers.get('Origin')
        return [
            ('Access-Control-Allow-Origin', origin if origin else '*'),
            ('Access-Control-Allow-Methods', 'POST, GET, OPTIONS, PUT, DELETE'),
            ('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Requested-With'),
            ('Access-Control-Allow-Credentials', 'true'),
            ('Access-Control-Max-Age', '86400')
        ]

    # Lấy danh sách các nhóm dịch vụ và các dịch vụ trong nhóm
    @http.route('/api/service/groups', type='http', auth='public', methods=['GET', 'OPTIONS'], csrf=False)
    def get_groups_and_services(self):
        if request.httprequest.method == 'OPTIONS': 
            return Response(status=200, headers=self._get_cors_headers())
        groups = request.env['student.service.group'].search([])
        result = []
        for group in groups:
            services = [{
                'id': s.id,
                'name': s.name,
                'description': s.description,
                'titlenote': s.titlenote,
                'state': s.state,
                'duration': s.duration if hasattr(s, 'duration') else 0,
                'files': [f.name for f in s.files],
            } for s in group.service_ids]
            result.append({
                'id': group.id,
                'name': group.name,
                'description': group.description,
                'parent_id': group.parent_id.id if group.parent_id else False,
                'services': services,
            })
        return Response(
            json.dumps({
                'success': True,
                'message': 'Danh sách nhóm dịch vụ và dịch vụ',
                'data': result
            }),
            content_type='application/json',
            status=200,
            headers=self._get_cors_headers()
        )

    # Bắt tất cả các request OPTIONS để hỗ trợ CORS preflight
    @http.route('/student_service/<path:any>', type='http', auth='public', methods=['OPTIONS'], csrf=False)
    def catch_all_st_options(self, any):
        return Response(status=200, headers=self._get_cors_headers())

    # Lấy danh sách các dịch vụ
    @http.route('/student_service/api/services', type='http', auth='public', methods=['GET','OPTIONS'], csrf=False)
    def list_services(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=self._get_cors_headers())
        services = request.env['student.service'].sudo().search([])
        data = [
            {
                'id': s.id,
                'name': s.name,
                'description': s.description,
            }
            for s in services
        ]
        return Response(
            json.dumps({
                'success': True,
                'message': 'Danh sách dịch vụ',
                'data': data
            }),
            content_type='application/json',
            status=200,
            headers=self._get_cors_headers()
        )

    # Lấy thông tin chi tiết của 1 dịch vụ
    @http.route('/student_service/api/service/<int:service_id>', type='http', auth='public', methods=['GET', 'OPTIONS'], csrf=False)
    def get_service_detail(self, service_id, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=self._get_cors_headers())
        service = request.env['student.service'].sudo().browse(service_id)
        if not service.exists():
            return Response(
                
                json.dumps({'error': 'Service not found'}),
                content_type='application/json',
                status=404,
                headers=self._get_cors_headers()
            )
        data = {
            'id': service.id,
            'name': service.name,
            'description': service.description,
            'titlenote': service.titlenote,
            'state': service.state,
            
            'group_id': service.group_id.id if service.group_id else None,
            'group_name': service.group_id.name if service.group_id else '',
            # Add more fields if needed
            'step_ids': [{'id': step.id, 'name': step.name, 'description': step.description} for step in service.step_ids],
            'users': [{'id': user.id, 'name': user.name} for user in service.users],
            'files': [{'id': f.id, 'name': f.name, 'description': f.description } for f in service.files],
        }
        return Response(
            json.dumps({
                'success': True,
                'message': 'Thành công',
                'data': data
            }),
            content_type='application/json',
            status=200,
            headers=[
                ('Access-Control-Allow-Origin', '*'),
                ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ('Access-Control-Allow-Credentials', 'true')
            ]
        )

    # Lấy danh sách các Files trong student.service.file
    @http.route('/api/service/files', type='http', auth='public', methods=['GET','OPTIONS'], csrf=False)
    def get_service_files(self):
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
        files = request.env['student.service.file'].sudo().search([])
        data = [{'id': f.id, 'name': f.name, 'description': f.description} for f in files]
        return Response(
            json.dumps({'success': True, 'message': 'Danh sách files', 'data': data}),
            content_type='application/json',
            status=200,
            headers=[
                ('Access-Control-Allow-Origin', '*'),
                ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ('Access-Control-Allow-Credentials', 'true')
            ]
        )

    # Lấy cấu trúc Form nhập liệu của dịch vụ
    @http.route('/api/service/<int:service_id>/form', type='http', auth='public', methods=['GET', 'OPTIONS'], csrf=False)
    def get_service_form(self, service_id, **kwargs):
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=[
                ('Access-Control-Allow-Origin', '*'),
                ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ('Access-Control-Allow-Credentials', 'true'),
                ('Access-Control-Max-Age', '86400'),
            ])

        service = request.env['student.service'].sudo().browse(service_id)
        if not service.exists():
            return Response(
                json.dumps({'success': False, 'message': 'Service not found'}),
                content_type='application/json',
                status=404,
                headers=[('Access-Control-Allow-Origin', '*')]
            )

        fields_data = []
        for field in service.form_field_ids:
            field_data = {
                'id': field.id,
                'name': field.name,
                'label': field.label,
                'type': field.field_type,
                'required': field.required,
                'placeholder': field.placeholder or '',
                'sequence': field.sequence,
            }
            
            # Nếu là dropdown -> Lấy options
            if field.field_type in ['select', 'select_multi']:
                field_data['options'] = [
                    {'id': opt.id, 'name': opt.name} 
                    for opt in field.option_ids
                ]
            
            fields_data.append(field_data)

        return Response(
            json.dumps({
                'success': True,
                'message': 'Cấu trúc form dịch vụ',
                'data': {
                    'service_id': service.id,
                    'service_name': service.name,
                    'fields': fields_data
                }
            }),
            content_type='application/json',
            status=200,
            headers=self._get_cors_headers()
        )
