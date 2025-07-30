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

class NotificationApiController(http.Controller):
    
    @http.route('/api/notifications/my', type='http', auth='public', methods=['GET'], csrf=False)
    def get_my_notifications(self):
        params = request.httprequest.get_json(force=True, silent=True) or {}
        user_id = params.get('user_id')
        if not user_id:
            return Response(
                json.dumps({'success': False, 'message': 'Missing user_id', 'data': []}),
                content_type='application/json',
                status=400,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )

        try:
            profile = request.env['student.user.profile'].sudo().search([('user_id', '=', int(user_id))], limit=1)
            domain = ['|', ('user_ids', 'in', [profile.user_id.id]), ('dormitory_cluster_ids', 'in', [profile.dormitory_cluster_id])] if profile and profile.dormitory_cluster_id else [('user_ids', 'in', [profile.user_id.id])]
            notifications = request.env['student.notify'].sudo().search(domain, order='create_date desc')
            
            data = [{
                'id': n.id,
                'title': n.title,
                'body': n.body,
                'is_read': profile.user_id.id in n.read_user_ids.ids if n.read_user_ids else False,
                'create_date': n.create_date.strftime('%Y-%m-%d %H:%M:%S') if n.create_date else '',
                'data': n.data or {},
            } for n in notifications]

            return Response(
                json.dumps({'success': True, 'message': 'Danh sách thông báo', 'data': data}),
                content_type='application/json',
                status=200,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )
        except Exception as e:
            return Response(
                json.dumps({'success': False, 'message': str(e), 'data': []}),
                content_type='application/json',
                status=500,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )


    # TODO API duyệt yêu cầu dịch vụ ()