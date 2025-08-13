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
    
    @http.route('/api/notifications/my', type='http', auth='public', methods=['GET'], csrf=False)
    def get_my_notifications(self):
        try:
            params = request.params
            user_id = params.get('user_id')
            page = int(params.get('page', 1))
            limit = int(params.get('limit', 10))

            if not user_id:
                return Response(
                    json.dumps({'success': False, 'message': 'Missing user_id'}),
                    content_type='application/json',
                    status=400
                )

            profile = request.env['student.user.profile'].sudo().search([('user_id', '=', int(user_id))], limit=1)
            if not profile:
                return Response(
                    json.dumps({'success': False, 'message': 'User profile not found'}),
                    content_type='application/json',
                    status=404
                )

            if profile.dormitory_cluster_id:
                domain = ['|',
                          ('user_ids', 'in', [profile.user_id.id]),
                          ('dormitory_cluster_ids', 'in', [profile.dormitory_cluster_id])]
            else:
                domain = [('user_ids', 'in', [profile.user_id.id])]

            total = request.env['student.notify'].sudo().search_count(domain)
            offset = (page - 1) * limit
            notifications = request.env['student.notify'].sudo().search(
                domain, order='create_date desc', offset=offset, limit=limit)

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
                json.dumps({
                    'success': True,
                    'message': 'Danh sách thông báo',
                    'data': data,
                    'meta': {
                        'total': total,
                        'page': page,
                        'limit': limit,
                        'has_next': offset + limit < total,
                    }
                }),
                content_type='application/json',
                status=200
            )

        except Exception as e:
            return Response(
                json.dumps({
                    "success": False,
                    "message": str(e)
                }),
                content_type='application/json',
                status=500
            )

        except Exception as e:
            return {'success': False, 'message': str(e)}


    # lấy chi tiết thông báo
    @http.route('/api/notifications/detail', type='http', methods=['POST'], auth='public', csrf=False)
    def get_notification_detail(self):
        params = request.httprequest.get_json(force=True, silent=True) or {}
        notify_id = params.get('notify_id')
        if not notify_id:
            return Response(
                json.dumps({'success': False, 'message': 'Missing notify_id'}),
                content_type='application/json',
                status=400,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )

        try:
            notify = request.env['student.notify'].sudo().browse(int(notify_id))
            if not notify.exists():
                return Response(
                    json.dumps({'success': False, 'message': 'Notification not found'}),
                    content_type='application/json',
                    status=404,
                    headers=[
                        ('Access-Control-Allow-Origin', '*'),
                        ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                        ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ]
                )
            data = {
                'id': notify.id,
                'title': notify.title,
                'body': notify.body,
                'image': notify.image or '',
                'article': notify.article or '',
                'is_read': request.env.user.id in notify.read_user_ids.ids if notify.read_user_ids else False,
                'create_date': notify.create_date.strftime('%Y-%m-%d %H:%M:%S') if notify.create_date else '',
                'data': safe_json_parse(notify.data),
            }
            return Response(
                json.dumps({'success': True, 'message': 'Chi tiết thông báo', 'data': data}),
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
   
    # API lấy số lượng thông báo chưa đọc
    @http.route('/api/notifications/unread/count', type='http', auth='public', methods=['GET'], csrf=False)
    def get_unread_notifications_count(self):
        try:
            params = request.params
            user_id = params.get('user_id')

            if not user_id:
                return Response(
                    json.dumps({
                        'success': False, 
                        'message': 'Missing user_id'
                    }),
                    content_type='application/json',
                    status=400
                )

            profile = request.env['student.user.profile'].sudo().search([('user_id', '=', int(user_id))], limit=1)
            if not profile:
                return Response(
                    json.dumps({
                        'success': False,
                        'message': 'User profile not found'
                    }),
                    content_type='application/json',
                    status=404
                )

            # Tạo domain để tìm thông báo
            if profile.dormitory_cluster_id:
                domain = ['|',
                         ('user_ids', 'in', [profile.user_id.id]),
                         ('dormitory_cluster_ids', 'in', [profile.dormitory_cluster_id])]
            else:
                domain = [('user_ids', 'in', [profile.user_id.id])]

            # Đếm tổng số thông báo
            total_notifications = request.env['student.notify'].sudo().search_count(domain)
            
            # Đếm số thông báo đã đọc
            read_domain = domain + [('read_user_ids', 'in', [profile.user_id.id])]
            read_count = request.env['student.notify'].sudo().search_count(read_domain)
            
            # Tính số thông báo chưa đọc
            unread_count = total_notifications - read_count

            return Response(
                json.dumps({
                    'success': True,
                    'message': 'Thành công',
                    'data': {
                        'total': total_notifications,
                        'unread': unread_count,
                        'read': read_count
                    }
                }),
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
                json.dumps({
                    'success': False,
                    'message': str(e)
                }),
                content_type='application/json',
                status=500,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )
