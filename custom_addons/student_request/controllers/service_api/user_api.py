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
    
    # Lấy danh sách users có group_id.name == 'Settings'
    @http.route('/api/users/forassign', type='http', auth='public', methods=['GET'], csrf=False)
    def get_settings_users(self):
        group = request.env['res.groups'].sudo().search([('name', '=', 'Settings')], limit=1)
        if not group:
            return Response(
                json.dumps({'success': False, 'message': 'Group "Settings" not found', 'data': []}),
                content_type='application/json',
                status=404,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )
        users = group.users
        data = [{'id': u.id, 'name': u.name, 'login': u.login, 'email': u.email} for u in users]
        return Response(
            json.dumps({'success': True, 'message': 'Danh sách users thuộc group Settings', 'data': data}),
            content_type='application/json',
            status=200,
            headers=[
                ('Access-Control-Allow-Origin', '*'),
                ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
            ]
        )
