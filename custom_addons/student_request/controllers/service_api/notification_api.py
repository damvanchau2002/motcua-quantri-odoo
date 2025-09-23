from odoo import http, models, fields
from odoo.http import request, Response
from odoo.fields import Datetime
from odoo.osv import expression
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
                    status=400,
                    headers=[
                        ('Access-Control-Allow-Origin', '*'),
                        ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                        ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                        ('Access-Control-Allow-Credentials', 'true')
                    ]
                )

            user_id_int = int(user_id)

            # Lấy profile của user, có thể là student, admin, hoặc staff
            student_profile = request.env['student.user.profile'].sudo().search([('user_id', '=', user_id_int)], limit=1)
            admin_profile = request.env['student.admin.profile'].sudo().search([('user_id', '=', user_id_int)], limit=1)
            staff_profile = None
            try:
                staff_profile = request.env['hr.employee'].sudo().search([('user_id', '=', user_id_int)], limit=1)
            except KeyError:
                pass  # hr.employee model might not exist

            profile = student_profile or admin_profile or staff_profile

            if not profile:
                return Response(
                    json.dumps({'success': False, 'message': 'User profile not found'}),
                    content_type='application/json',
                    status=404,
                    headers=[
                        ('Access-Control-Allow-Origin', '*'),
                        ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                        ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                        ('Access-Control-Allow-Credentials', 'true')
                    ]
                )

            # Xây dựng domain để query thông báo
            # 1. Thông báo gửi trực tiếp cho user
            base_domain = [('user_ids', 'in', [user_id_int])]
            
            # 2. Thông báo gửi cho khu KTX của user
            if student_profile and student_profile.dormitory_cluster_id:
                base_domain = expression.OR([base_domain, [('dormitory_cluster_ids', 'in', [student_profile.dormitory_cluster_id])]])
            elif admin_profile and admin_profile.dormitory_clusters:
                base_domain = expression.OR([base_domain, [('dormitory_cluster_ids', 'in', admin_profile.dormitory_clusters.ids)]])

            # Domain cho thông báo chưa đọc
            unread_domain = expression.AND([base_domain, [('read_user_ids', 'not in', [user_id_int])]])

            # Đếm tổng số thông báo
            total_all = request.env['student.notify'].sudo().search_count(base_domain)
            total_unread = request.env['student.notify'].sudo().search_count(unread_domain)
            
            # Lấy danh sách TẤT CẢ thông báo (phân trang)
            offset = (page - 1) * limit
            notifications = request.env['student.notify'].sudo().search(base_domain, order='create_date desc', offset=offset, limit=limit)

            data = [{'id': n.id,
                'title': n.title,
                'body': n.body,
                'image': n.image or '',
                'article': n.article or '',
                'is_read': user_id_int in n.read_user_ids.ids,
                'create_date': n.create_date.strftime('%Y-%m-%d %H:%M:%S') if n.create_date else '',
                'data': safe_json_parse(n.data),
            } for n in notifications]

            return Response(
                json.dumps({
                    'success': True,
                    'message': 'Danh sách thông báo',
                    'data': data,
                    'meta': {
                        'total_all': total_all,
                        'total_unread': total_unread,
                        'page': page,
                        'limit': limit,
                        'has_next': offset + limit < total_all,
                    }
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

        except Exception as e:
            return Response(
                json.dumps({
                    "success": False,
                    "message": str(e)
                }),
                content_type='application/json',
                status=500,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true')
                ]
            )


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
                    ('Access-Control-Allow-Credentials', 'true')
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
                        ('Access-Control-Allow-Credentials', 'true')
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
                    ('Access-Control-Allow-Credentials', 'true')
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
                    ('Access-Control-Allow-Credentials', 'true')
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
                    ('Access-Control-Allow-Credentials', 'true')
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
                        ('Access-Control-Allow-Credentials', 'true')
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
                    ('Access-Control-Allow-Credentials', 'true')
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
                    ('Access-Control-Allow-Credentials', 'true')
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
                    ('Access-Control-Allow-Credentials', 'true')
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
                        ('Access-Control-Allow-Credentials', 'true')
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
                    ('Access-Control-Allow-Credentials', 'true')
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
                    ('Access-Control-Allow-Credentials', 'true')
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
            
            user_id_int = int(user_id)
            
            # Lấy profile của user, có thể là student, admin, hoặc staff
            student_profile = request.env['student.user.profile'].sudo().search([('user_id', '=', user_id_int)], limit=1)
            admin_profile = request.env['student.admin.profile'].sudo().search([('user_id', '=', user_id_int)], limit=1)
            staff_profile = None
            try:
                staff_profile = request.env['hr.employee'].sudo().search([('user_id', '=', user_id_int)], limit=1)
            except KeyError:
                pass # hr.employee model might not exist
            
            profile = student_profile or admin_profile or staff_profile

            if not profile:
                return Response(
                    json.dumps({
                        'success': False,
                        'message': 'User profile not found'
                    }),
                    content_type='application/json',
                    status=404
                )

            # Xây dựng domain để query thông báo
            # 1. Thông báo gửi trực tiếp cho user
            domain = [('user_ids', 'in', [user_id_int])]
            
            # 2. Thông báo gửi cho khu KTX của user
            if student_profile and student_profile.dormitory_cluster_id:
                domain = ['|'] + domain + [('dormitory_cluster_ids', 'in', [student_profile.dormitory_cluster_id.id])]
            elif admin_profile and admin_profile.dormitory_clusters:
                domain = ['|'] + domain + [('dormitory_cluster_ids', 'in', admin_profile.dormitory_clusters.ids)]

            # Đếm tổng số thông báo theo domain
            total_count = request.env['student.notify'].sudo().search_count(domain)
            
            # Đếm số thông báo đã đọc
            read_domain = domain + [('read_user_ids', 'in', [user_id_int])]
            read_count = request.env['student.notify'].sudo().search_count(read_domain)
            
            # Tính số thông báo chưa đọc
            unread_count = total_count - read_count

            return Response(
                json.dumps({
                    'success': True,
                    'message': 'Thành công',
                    'data': {
                        'total': total_count,
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
                    ('Access-Control-Allow-Credentials', 'true')
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
                    ('Access-Control-Allow-Credentials', 'true')
                ]
            )