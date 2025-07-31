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
from .utils import *

class NotificationApiController(http.Controller):
    
     # Lấy danh sách thông báo của user
    @http.route('/api/notifications/my', type='http', auth='public', methods=['GET'], csrf=False)
    def get_my_notifications(self):
        params = request.httprequest.get_json(force=True, silent=True) or {}
        user_id = params.get('user_id')
        if not user_id:
            return Response(
                json.dumps({'success': False, 'message': 'Missing user_id'}),
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
                'image': n.image or '',
                'article': n.article or '',
                'is_read': profile.user_id.id in n.read_user_ids.ids if n.read_user_ids else False,
                'create_date': n.create_date.strftime('%Y-%m-%d %H:%M:%S') if n.create_date else '',
                'data': safe_json_parse(n.data),
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
                json.dumps({'success': False, 'message': str(e)}),
                content_type='application/json',
                status=500,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )

    # API đánh dấu thông báo đã đọc
    @http.route('/api/notifications/read', type='http', auth='public', methods=['POST'], csrf=False)
    def mark_notification_as_read(self):
        params = request.httprequest.get_json(force=True, silent=True) or {}
        user_id = params.get('user_id')
        notify_id = params.get('notify_id')
        if not user_id or not notify_id:
            return Response(
                json.dumps({'success': False, 'message': 'Missing user_id or notify_id'}),
                content_type='application/json',
                status=400,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )
        try:
            notify = request.env['student.notify'].sudo().browse(int(notify_id))
            user = request.env['res.users'].sudo().browse(int(user_id))
            if not notify.exists() or not user.exists():
                return Response(
                    json.dumps({'success': False, 'message': 'Notification or user not found'}),
                    content_type='application/json',
                    status=404,
                    headers=[
                        ('Access-Control-Allow-Origin', '*'),
                        ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                        ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ]
                )
            notify.sudo().write({'read_user_ids': [(4, user.id)]})
            return Response(
                json.dumps({'success': True, 'message': 'Notification marked as read'}),
                content_type='application/json',
                status=200,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )
        except Exception as e:
            return Response(
                json.dumps({'success': False, 'message': str(e)}),
                content_type='application/json',
                status=500,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )
    
    # API đánh dấu đã đọc tất cả thông báo của user
    @http.route('/api/notifications/read_all', type='http', auth='public', methods=['POST'], csrf=False)
    def mark_all_notifications_as_read(self):
        params = request.httprequest.get_json(force=True, silent=True) or {}
        user_id = params.get('user_id')
        if not user_id:
            return Response(
                json.dumps({'success': False, 'message': 'Missing user_id'}),
                content_type='application/json',
                status=400,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )
        try:
            user = request.env['res.users'].sudo().browse(int(user_id))
            if not user.exists():
                return Response(
                    json.dumps({'success': False, 'message': 'User not found'}),
                    content_type='application/json',
                    status=404,
                    headers=[
                        ('Access-Control-Allow-Origin', '*'),
                        ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                        ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ]
                )
            profile = request.env['student.user.profile'].sudo().search([('user_id', '=', user.id)], limit=1)
            domain = ['|', ('user_ids', 'in', [user.id]), ('dormitory_cluster_ids', 'in', [profile.dormitory_cluster_id])] if profile and profile.dormitory_cluster_id else [('user_ids', 'in', [user.id])]
            notifications = request.env['student.notify'].sudo().search(domain)
            for notify in notifications:
                notify.sudo().write({'read_user_ids': [(4, user.id)]})
            return Response(
                json.dumps({'success': True, 'message': 'Đã đánh dấu tất cả thông báo là đã đọc'}),
                content_type='application/json',
                status=200,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )
        except Exception as e:
            return Response(
                json.dumps({'success': False, 'message': str(e)}),
                content_type='application/json',
                status=500,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )
   
   