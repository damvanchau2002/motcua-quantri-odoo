from odoo import http, SUPERUSER_ID
from odoo.http import request
from odoo.addons.auth_oauth.controllers.main import OAuthController
import base64, json
import requests as py_requests
import werkzeug

import logging
_logger = logging.getLogger(__name__)

class CustomOAuthController(OAuthController):

    @http.route('/auth_oauth/signin', type='http', auth='none', readonly=False)
    def signin(self, **kw):
        """
        Kế thừa logic gốc của Odoo, sau đó bổ sung tạo/cập nhật user, profile, oauth record
        """
        try:
            # --- gọi logic gốc (để xử lý OAuth + login session)
            resp = super(CustomOAuthController, self).signin(**kw)

            params = kw or request.params
            state = json.loads(params.get('state', '{}'))
            code = params.get('code')
            access_token = params.get('access_token')
            id_token = params.get('id_token')

            # --- lấy user đã đăng nhập
            user = request.env.user
            if user and user.id != SUPERUSER_ID:
                state = json.loads(kw.get("state", "{}"))

                email = params.get('email')
                gender = params.get('gender')
                phone = params.get('phone')
                fullname = params.get('fullname')
                avatar = params.get('avatar')
                fcm_device_token = params.get('fcm_device_token')
                device_id = params.get('device_id')

                provider = state.get("p")
                token = kw.get("access_token") or kw.get("id_token")

                # lấy thông tin từ Microsoft (ví dụ email, fullname, avatar) 
                email = user.email
                fullname = user.name
                avatar = None  # bạn có thể call Microsoft Graph API để lấy avatar

                # --- xử lý avatar
                image_data = False
                if avatar:
                    try:
                        resp_img = py_requests.get(avatar)
                        if resp_img.status_code == 200:
                            image_data = base64.b64encode(resp_img.content).decode("utf-8")
                    except Exception:
                        pass

                # --- cập nhật user
                user.sudo().write({
                    'name': fullname or 'Oauth User',
                    'login': email or f'{provider}_user',
                    'active': True,
                    'email': email,
                    'groups_id': [(6, 0, [request.env.ref('base.group_system').id])],
                    'image_1920': image_data,
                })

                # --- tạo/cập nhật profile
                profile = request.env['student.admin.profile'].sudo().search([('user_id', '=', user.id)], limit=1)
                if not profile:
                    profile = request.env['student.admin.profile'].sudo().create({
                        'user_id': user.id,
                        'fcm_token': fcm_device_token,
                        'device_id': device_id,
                        'phone': phone,
                        'gender': gender,
                        'email': email,
                    })
                else:
                    profile.sudo().write({
                        'fcm_token': fcm_device_token,
                        'device_id': device_id,
                        'phone': phone,
                        'gender': gender,
                        'email': email,
                    })

                # --- tạo/cập nhật oauth record
                oauth = request.env['student.admin.oauth'].sudo().search([
                    ('user_id', '=', user.id),
                    ('provider', '=', provider)
                ], limit=1)

                if not oauth:
                    request.env['student.admin.oauth'].sudo().create({
                        'profile_id': profile.id,
                        'user_id': user.id,
                        'provider': provider,
                        'token': token,
                        'avatar_url': avatar,
                    })
                else:
                    oauth.sudo().write({
                        'token': token,
                        'avatar_url': avatar,
                    })

            return resp

        except Exception as e:
            _logger.exception("Custom OAuth signin failed: %s", e)
            return request.redirect("/web/login?oauth_error=99", 303)
