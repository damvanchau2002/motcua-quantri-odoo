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

    @http.route('/api/service/groups', type='http', auth='public', methods=['GET'], csrf=False)
    def get_groups_and_services(self):
        groups = request.env['student.service.group'].search([])
        result = []
        for group in groups:
            services = [{
                'id': s.id,
                'name': s.name,
                'description': s.description,
                'state': s.state,
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
            headers=[
                ('Access-Control-Allow-Origin', '*'),
                ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
            ]
        )

    # Lấy danh sách các dịch vụ
    @http.route('/student_service/api/services', type='http', auth='public', methods=['GET'], csrf=False)
    def list_services(self, **kwargs):
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
            headers=[
                ('Access-Control-Allow-Origin', '*'),
                ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
            ]
        )

    # Lấy thông tin chi tiết của 1 dịch vụ
    @http.route('/student_service/api/service/<int:service_id>', type='http', auth='public', methods=['GET'], csrf=False)
    def get_service_detail(self, service_id, **kwargs):
        service = request.env['student.service'].sudo().browse(service_id)
        if not service.exists():
            return Response(
                json.dumps({'error': 'Service not found'}),
                content_type='application/json',
                status=404,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
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
            ]
        )

    # API làm mới JWT token
    @http.route('/api/service/files', type='http', auth='public', methods=['GET'], csrf=False)
    def get_service_files(self):
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
            ]
        )

    # Lấy chi tiết 1 yêu cầu dịch vụ