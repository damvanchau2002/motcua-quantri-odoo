# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request, Response
import json
import os
import logging
from .utils import get_cors_headers, check_jwt_token, decode_jwt_token, SECRET_KEY

_logger = logging.getLogger(__name__)


class FcmSwController(http.Controller):
    """Serve firebase-messaging-sw.js at root scope for FCM background push."""

    @http.route('/firebase-messaging-sw.js', type='http', auth='public',
                methods=['GET'], csrf=False, save_session=False)
    def serve_fcm_sw(self, **kwargs):
        sw_path = os.path.normpath(os.path.join(
            os.path.dirname(__file__),
            '..', '..', 'static', 'src', 'js', 'firebase-messaging-sw.js'
        ))

        try:
            with open(sw_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except FileNotFoundError:
            _logger.error('[FCM SW] firebase-messaging-sw.js not found at: %s', sw_path)
            return Response('Service Worker not found', status=404)

        return Response(
            content,
            content_type='application/javascript; charset=utf-8',
            status=200,
            headers=[
                ('Service-Worker-Allowed', '/'),
                ('Cache-Control', 'no-cache, no-store, must-revalidate'),
                ('Pragma', 'no-cache'),
                ('Expires', '0'),
            ]
        )


class FcmWebApiController(http.Controller):
    """API for browser to register FCM token after login."""

    @http.route('/api/web/fcm/config', type='http', auth='public',
                methods=['GET', 'OPTIONS'], csrf=False)
    def get_fcm_web_config(self):
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=get_cors_headers(request))

        try:
            params = request.env['ir.config_parameter'].sudo()
            config = {
                'apiKey':            params.get_param('student_request.firebase_web_api_key', ''),
                'authDomain':        params.get_param('student_request.firebase_web_auth_domain', ''),
                'projectId':         params.get_param('student_request.firebase_web_project_id', ''),
                'storageBucket':     params.get_param('student_request.firebase_web_storage_bucket', ''),
                'messagingSenderId': params.get_param('student_request.firebase_web_messaging_sender_id', ''),
                'appId':             params.get_param('student_request.firebase_web_app_id', ''),
                'vapidKey':          params.get_param('student_request.firebase_web_vapid_key', ''),
            }

            configured = all([config['apiKey'], config['projectId'],
                              config['messagingSenderId'], config['vapidKey']])

            return Response(
                json.dumps({'success': True, 'configured': configured, 'config': config},
                           ensure_ascii=False),
                content_type='application/json',
                status=200,
                headers=get_cors_headers(request)
            )
        except Exception as e:
            _logger.exception('Error getting FCM web config: %s', str(e))
            return Response(
                json.dumps({'success': False, 'message': str(e), 'configured': False}),
                content_type='application/json',
                status=500,
                headers=get_cors_headers(request)
            )

    @http.route('/api/web/fcm/register', type='http', auth='public',
                methods=['POST', 'OPTIONS'], csrf=False)
    def register_fcm_token(self):
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=get_cors_headers(request))

        params = request.httprequest.get_json(force=True, silent=True) or {}
        fcm_token = (params.get('fcm_token') or params.get('fcm_device_token') or '').strip()
        device_id = (params.get('device_id') or 'web-browser').strip()

        if not fcm_token:
            return Response(
                json.dumps({'success': False, 'message': 'Missing fcm_token'}),
                content_type='application/json',
                status=400,
                headers=get_cors_headers(request)
            )

        uid = None

        auth_header = request.httprequest.headers.get('Authorization', '')
        if auth_header.lower().startswith('bearer '):
            jwt_token = auth_header[7:]
            payload = decode_jwt_token(jwt_token, SECRET_KEY)
            if 'error' not in payload:
                uid = payload.get('uid')

        if not uid:
            session_uid = request.session.uid
            if session_uid and session_uid != request.env.ref('base.public_user').id:
                uid = session_uid

        if not uid:
            raw_uid = params.get('user_id')
            if raw_uid:
                try:
                    uid = int(raw_uid)
                except (ValueError, TypeError):
                    pass

        if not uid:
            return Response(
                json.dumps({'success': False, 'message': 'Unauthorized. Please login first.'}),
                content_type='application/json',
                status=401,
                headers=get_cors_headers(request)
            )

        try:
            user = request.env['res.users'].sudo().browse(int(uid))
            if not user.exists():
                return Response(
                    json.dumps({'success': False, 'message': 'User not found'}),
                    content_type='application/json',
                    status=404,
                    headers=get_cors_headers(request)
                )

            saved_in = []

            admin_profile = request.env['student.admin.profile'].sudo().search(
                [('user_id', '=', uid)], limit=1
            )
            if admin_profile:
                admin_profile.sudo().write({'fcm_token': fcm_token, 'device_id': device_id})
                saved_in.append('admin_profile')
                _logger.info('FCM web token saved for admin uid=%s', uid)

            student_profile = request.env['student.user.profile'].sudo().search(
                [('user_id', '=', uid)], limit=1
            )
            if student_profile:
                student_profile.sudo().write({'fcm_token': fcm_token, 'device_id': device_id})
                saved_in.append('student_profile')
                _logger.info('FCM web token saved for student uid=%s', uid)

            if not saved_in:
                request.env['student.admin.profile'].sudo().create({
                    'user_id': uid,
                    'fcm_token': fcm_token,
                    'device_id': device_id,
                    'email': user.email or '',
                })
                saved_in.append('admin_profile (created)')
                _logger.info('FCM web token: created admin profile for uid=%s', uid)

            return Response(
                json.dumps({
                    'success': True,
                    'message': 'FCM token saved successfully',
                    'data': {
                        'user_id': uid,
                        'user_name': user.name,
                        'saved_in': saved_in,
                        'device_id': device_id,
                    }
                }, ensure_ascii=False),
                content_type='application/json',
                status=200,
                headers=get_cors_headers(request)
            )

        except Exception as e:
            _logger.exception('Error registering FCM token for uid=%s: %s', uid, str(e))
            return Response(
                json.dumps({'success': False, 'message': str(e)}),
                content_type='application/json',
                status=500,
                headers=get_cors_headers(request)
            )

    @http.route('/api/web/fcm/unregister', type='http', auth='public',
                methods=['POST', 'OPTIONS'], csrf=False)
    def unregister_fcm_token(self):
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=get_cors_headers(request))

        params = request.httprequest.get_json(force=True, silent=True) or {}

        uid = None
        session_uid = request.session.uid
        if session_uid and session_uid != request.env.ref('base.public_user').id:
            uid = session_uid

        if not uid:
            raw_uid = params.get('user_id')
            if raw_uid:
                try:
                    uid = int(raw_uid)
                except (ValueError, TypeError):
                    pass

        if not uid:
            return Response(
                json.dumps({'success': False, 'message': 'Unauthorized'}),
                content_type='application/json',
                status=401,
                headers=get_cors_headers(request)
            )

        try:
            for model in ['student.admin.profile', 'student.user.profile']:
                profile = request.env[model].sudo().search([('user_id', '=', uid)], limit=1)
                if profile and profile.fcm_token:
                    profile.sudo().write({'fcm_token': False, 'device_id': False})

            _logger.info('FCM token cleared for uid=%s', uid)
            return Response(
                json.dumps({'success': True, 'message': 'FCM token cleared'}),
                content_type='application/json',
                status=200,
                headers=get_cors_headers(request)
            )
        except Exception as e:
            return Response(
                json.dumps({'success': False, 'message': str(e)}),
                content_type='application/json',
                status=500,
                headers=get_cors_headers(request)
            )
