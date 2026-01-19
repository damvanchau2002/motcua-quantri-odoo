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
import urllib3
from .utils import *



class AuthApiController(http.Controller):

    def _get_cors_headers(self):
        origin = request.httprequest.headers.get('Origin')
        return [
            ('Access-Control-Allow-Origin', origin if origin else '*'),
            ('Access-Control-Allow-Methods', 'POST, GET, OPTIONS, PUT, DELETE'),
            ('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Requested-With'),
            ('Access-Control-Allow-Credentials', 'true'),
            ('Access-Control-Max-Age', '86400')
        ]

    #API làm mới JWT token
    @http.route('/api/public_user/refresh_token', type='http', auth='public', methods=['POST','OPTIONS'], csrf=False)
    def refresh_token(self):
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=self._get_cors_headers())
        params = request.httprequest.get_json(force=True, silent=True) or {}
        auth_header = request.httprequest.headers.get('Authorization')
        token = None
        if auth_header and auth_header.lower().startswith('bearer '):
            token = auth_header[7:]
        else:
            token = request.httprequest.headers.get('token')
        if not token:
            return Response(
                json.dumps({'success': False, 'message': 'Missing authorization token'}),
                content_type='application/json',
                status=400,
                headers=self._get_cors_headers()
            )
        payload = decode_jwt_token(token, SECRET_KEY)
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=self._get_cors_headers())
        if 'error' in payload:
            return Response(
                json.dumps({'success': False, 'message': payload['error']}),
                content_type='application/json',
                status=401,
                headers=self._get_cors_headers()
            )
        uid = payload.get('uid')
        if not uid:
            return Response(
                json.dumps({'success': False, 'message': 'Invalid token payload'}),
                content_type='application/json',
                status=401,
                headers=self._get_cors_headers()
            )
        new_token = generate_jwt_token(uid, SECRET_KEY)
        return Response(
            json.dumps({'success': True, 'message': 'Token refreshed', 'token_auth': new_token}),
            content_type='application/json',
            status=200,
            headers=self._get_cors_headers()
        )

    # Bắt tất cả các request OPTIONS để hỗ trợ CORS preflight
    @http.route('/api/<path:any>', type='http', auth='public', methods=['OPTIONS'], csrf=False)
    def catch_all_options(self, any):
        return Response(status=200, headers=self._get_cors_headers())
    # Đăng nhập public user 
    @http.route('/api/public_user/login', type='http', auth='public', methods=['POST','OPTIONS'], csrf=False)
    def public_user_login(self):
        # Suppress insecure request warnings when verify=False is used
        try:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=self._get_cors_headers())
        params = request.httprequest.get_json(force=True, silent=True) or {}
        username = params.get('username')
        password = params.get('password')
        fcm_token = params.get('fcm_device_token')
        device_id = params.get('device_id')

        if not username:
            return Response(
                json.dumps({'success': False, 'message': 'Thiếu tên đăng nhập.'}),
                content_type='application/json',
                status=400,
                headers=self._get_cors_headers()
            )
        if not password:
            return Response(
                json.dumps({'success': False, 'message': 'Thiếu mật khẩu.'}),
                content_type='application/json',
                status=400,
                headers=self._get_cors_headers()
            )

        external_api_url = "https://sv_test.ktxhcm.edu.vn/MotCuaApi/Login"
        
        # Thử các định dạng username khác nhau
        username_variants = [username]
        if username.startswith('P'):
            username_variants.append(username[1:])  # Bỏ prefix P
        elif not username.startswith('P'):
            username_variants.append(f'P{username}')  # Thêm prefix P
        
        external_resp = None
        external_data = None
        last_error = None
        
        try:
            for variant in username_variants:
                print(f"DEBUG - Trying username variant: '{variant}'")
                external_resp = py_requests.post(
                    external_api_url,
                    json={"username": variant, "password": password},
                    timeout=10,
                    verify=False,
                    headers={"x-api-key": "motcua_ktx_maia_apikey"}
                )
                
                if external_resp.status_code == 200:
                    content_type = external_resp.headers.get('Content-Type', '')
                    if 'application/json' in content_type:
                        external_data = external_resp.json()
                        success = external_data.get('Success', False)
                        if success:
                            print(f"DEBUG - Success with username variant: '{variant}'")
                            break
                        else:
                            last_error = external_data.get('Message', 'Unknown error')
                            print(f"DEBUG - Failed with variant '{variant}': {last_error}")
                    else:
                        last_error = f"Unexpected content-type: {content_type}"
                
            if not external_resp or external_resp.status_code != 200:
                return Response(
                    json.dumps({
                        'success': False,
                        'message': f'Không thể kết nối tới hệ thống KTX. {last_error}',
                        'detail': last_error
                    }),
                    content_type='application/json',
                    status=502,
                    headers=self._get_cors_headers()
                )

            # external_data đã được lấy trong vòng lặp trên (nếu có)
            if not external_data:
                return Response(
                    json.dumps({
                        'success': False,
                        'message': last_error or 'Không nhận được dữ liệu JSON hợp lệ từ hệ thống KTX.',
                        'data': None
                    }),
                    content_type='application/json',
                    status=502,
                    headers=self._get_cors_headers()
                )

            success = external_data.get('Success', False)
            data = external_data.get('Data')
            message = external_data.get('Message') or 'Lỗi không xác định từ hệ thống KTX.'

            # Debug logging
            print(f"DEBUG - External API Response: {external_data}")
            print(f"DEBUG - Success: {success}, Data: {data}, Message: {message}")

            # Thất bại logic: Success = false hoặc Data = null
            if not success or data is None:
                return Response(
                    json.dumps({
                        'success': False,
                        'message': message,
                        'data': None
                    }),
                    content_type='application/json',
                    status=401,  # Sai thông tin đăng nhập hoặc không tìm thấy sinh viên
                    headers=self._get_cors_headers()
                )
            # Thành công: xử lý dữ liệu từ external API
            data = external_data.get('Data', {})

            student_code = data.get('StudentCode')
            id_card_number = data.get('IdCardNumber')
            
            # Debug logging cho student_code
            print(f"DEBUG - StudentCode from API: '{student_code}' (type: {type(student_code)})")
            print(f"DEBUG - IdCardNumber from API: '{id_card_number}' (type: {type(id_card_number)})")
            
            # Sử dụng IdCardNumber làm fallback nếu StudentCode là null
            if not student_code and id_card_number:
                student_code = id_card_number
                print(f"DEBUG - Using IdCardNumber as StudentCode: '{student_code}'")
            
            # Kiểm tra student_code không được null hoặc rỗng
            if not student_code:
                return Response(
                    json.dumps({
                        'success': False,
                        'message': 'Mã sinh viên không hợp lệ từ hệ thống KTX.',
                        'data': ''
                    }),
                    content_type='application/json',
                    status=200,
                    headers=self._get_cors_headers()
                )
            
            full_name = data.get('FullName')
            email = data.get('Email')
            phone = data.get('Phone')
            gender = data.get('Gender')
            birthday = convert_date(data.get('Birthday'))
            university_name = data.get('UniversityName')
            id_card_number = data.get('IdCardNumber')
            id_card_date = convert_date(data.get('IdCardDate'))
            id_card_issued_name = data.get('IdCardIssuedName')
            address = data.get('Address')
            district_name = data.get('DistrictName')
            province_name = data.get('ProvinceName')
            dormitory_full_name = data.get('DormitoryFullName')
            dormitory_area_id = data.get('DormitoryAreaId')
            dormitory_house_name = data.get('DormitoryHouseName')
            dormitory_cluster_id = data.get('DormitoryClusterId')
            dormitory_room_type_name = data.get('DormitoryRoomTypeName')
            dormitory_room_id = data.get('DormitoryRoomId')
            rent_id = data.get('RentId')
            avatar_url = data.get('Avatar')

            try:
                # Tạo hoặc lấy student.dormitory.area
                dormitory_area = None
                if dormitory_area_id:
                    dormitory_area = request.env['student.dormitory.area'].sudo().search([('area_id', '=', dormitory_area_id)], limit=1)
                    if not dormitory_area:
                        dormitory_area = request.env['student.dormitory.area'].sudo().create({
                            'name': f'Area {dormitory_area_id}',
                            'area_id': dormitory_area_id,
                        })

                    # Tạo hoặc lấy student.dormitory.cluster
                    dormitory_cluster = None
                    if dormitory_cluster_id:
                        dormitory_cluster = request.env['student.dormitory.cluster'].sudo().search([('qlsv_cluster_id', '=', dormitory_cluster_id)], limit=1)
                        if not dormitory_cluster:
                            dormitory_cluster = request.env['student.dormitory.cluster'].sudo().create({
                                'name': f'{dormitory_area.name} Cluster {dormitory_cluster_id}',
                                'qlsv_cluster_id': dormitory_cluster_id,
                                'qlsv_area_id': dormitory_area.area_id,
                                'area_id': dormitory_area.id,
                            })
            except Exception as e:
                print(f"Error processing user data: {e}")
                pass  # Bỏ qua lỗi nếu không tìm thấy hoặc tạo được area/cluster

            # Nếu có avatar_url, tải ảnh về và encode base64
            image_data = False
            if avatar_url:
                try:
                    resp = py_requests.get(avatar_url)
                    if resp.status_code == 200:
                        image_data = base64.b64encode(resp.content).decode('utf-8')
                except Exception:
                    image_data = False

            user = request.env['res.users'].sudo().search([('login', '=', student_code)], limit=1)
            if not user:
                # Đảm bảo có tên hợp lệ cho user
                user_name = full_name or student_code
                if not user_name:
                    user_name = f"User_{student_code}"
                
                vals = {
                    'name': user_name,
                    'login': student_code,
                    'active': True,
                    'groups_id': [(6, 0, [request.env.ref('base.group_public').id])],
                    'email': email,
                    'phone': phone,
                    'image_1920': image_data
                }

                user = request.env['res.users'].sudo().create(vals)
                if user:
                    # Tạo StudentUserProfile kèm theo user
                    request.env['student.user.profile'].sudo().create({
                        'user_id': user.id,
                        'student_code': student_code,
                        'avatar_url': avatar_url,
                        'birthday': birthday,
                        'gender': gender,
                        'university_name': university_name,
                        'id_card_number': id_card_number,
                        'id_card_date': id_card_date,
                        'id_card_issued_name': id_card_issued_name,
                        'address': address,
                        'district_name': district_name,
                        'province_name': province_name,
                        'dormitory_full_name': dormitory_full_name,
                        'dormitory_area_id': dormitory_area_id,
                        'dormitory_house_name': dormitory_house_name,
                        'dormitory_cluster_id': dormitory_cluster_id,
                        'dormitory_room_type_name': dormitory_room_type_name,
                        'dormitory_room_id': dormitory_room_id,
                        'rent_id': rent_id,
                        'fcm_token': fcm_token,
                        'device_id': device_id,
                    })

                    try:
                        remove_user_from_all_firebase_topics(request.env, user.id)
                        add_user_to_firebase_topic(request.env, user.id, dormitory_area_id, dormitory_cluster_id)
                    except Exception as e:
                        print(f"Error subscribing user to Firebase topic: {e}")
            else:
                #có user rồi trả về thông tin user
                # Cập nhật thông tin User
                user.sudo().write({
                    'email': email,
                    'phone': phone,
                    'image_1920': image_data,
                })
                # Cập nhật hoặc tạo StudentUserProfile
                profile = request.env['student.user.profile'].sudo().search([('user_id', '=', user.id)], limit=1)
                if profile:
                    profile.sudo().write({
                        'student_code': student_code,
                        'avatar_url': avatar_url,
                        'birthday': birthday,
                        'gender': gender,
                        'university_name': university_name,
                        'id_card_number': id_card_number,
                        'id_card_date': id_card_date,
                        'id_card_issued_name': id_card_issued_name,
                        'address': address,
                        'district_name': district_name,
                        'province_name': province_name,
                        'dormitory_full_name': dormitory_full_name,
                        'dormitory_area_id': dormitory_area_id,
                        'dormitory_house_name': dormitory_house_name,
                        'dormitory_cluster_id': dormitory_cluster_id,
                        'dormitory_room_type_name': dormitory_room_type_name,
                        'dormitory_room_id': dormitory_room_id,
                        'rent_id': rent_id,
                        'fcm_token': fcm_token,
                        'device_id': device_id,
                    })
                else:
                    request.env['student.user.profile'].sudo().create({
                        'user_id': user.id,
                        'student_code': student_code,
                        'avatar_url': avatar_url,
                        'birthday': birthday,
                        'gender': gender,
                        'university_name': university_name,
                        'id_card_number': id_card_number,
                        'id_card_date': id_card_date,
                        'id_card_issued_name': id_card_issued_name,
                        'address': address,
                        'district_name': district_name,
                        'province_name': province_name,
                        'dormitory_full_name': dormitory_full_name,
                        'dormitory_area_id': dormitory_area_id,
                        'dormitory_house_name': dormitory_house_name,
                        'dormitory_cluster_id': dormitory_cluster_id,
                        'dormitory_room_type_name': dormitory_room_type_name,
                        'dormitory_room_id': dormitory_room_id,
                        'rent_id': rent_id,
                        'fcm_token': fcm_token,
                        'device_id': device_id,
                    })

                try:
                    remove_user_from_all_firebase_topics(request.env, user.id)
                    add_user_to_firebase_topic(request.env, user.id, dormitory_area_id, dormitory_cluster_id)
                except Exception as e:
                    print(f"Error subscribing user to Firebase topic: {e}")

            jwt_token = generate_jwt_token(user.id, SECRET_KEY)
            refresh_token = generate_jwt_token(user.id, REFRESH_KEY)

            return Response(
                json.dumps({
                    'success': True,
                    'message': 'Đăng nhập thành công',
                    'data': {
                        'id': user.id,
                        'fullname': user.name,
                        'email': email,
                        'phone': phone,
                        'gender': gender,
                        'birthday': birthday,
                        'can_login': False,
                        'image_1920': bool(user.image_1920),

                        'student_code': student_code,
                        'avatar_url': avatar_url,
                        'university_name': university_name,
                        'id_card_number': id_card_number,
                        'id_card_date': id_card_date,
                        'id_card_issued_name': id_card_issued_name,
                        'address': address,
                        'district_name': district_name,
                        'province_name': province_name,
                        'dormitory_full_name': dormitory_full_name,
                        'dormitory_area_id': dormitory_area_id,
                        'dormitory_house_name': dormitory_house_name,
                        'dormitory_cluster_id': dormitory_cluster_id,
                        'dormitory_room_type_name': dormitory_room_type_name,
                        'dormitory_room_id': dormitory_room_id,
                        'rent_id': rent_id,

                        'access_token': jwt_token,
                        'refresh_token': refresh_token,
                    }
                }),
                content_type='application/json',
                status=200,
                headers=self._get_cors_headers()
            )

            # Nếu API trả về lỗi hoặc không có dữ liệu mong muốn
            if not external_data.get('success', False):
                return Response(
                    json.dumps({
                        'success': False,
                        'message': external_data,
                        'data': '' 
                    }),
                    content_type='application/json',
                    status=401,
                    headers=self._get_cors_headers()
                )
        except Exception as e:
            return Response(
                json.dumps({'success': False, 'message': str(e), 'data': ''}),
                content_type='application/json',
                status=500,
                headers=self._get_cors_headers()
            )
    @http.route('/api/avatar/<string:student_code>', type='http', auth='public', methods=['GET','OPTIONS'], csrf=False)
    def proxy_avatar(self, student_code):
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=self._get_cors_headers())
        
        # Logic xử lý proxy avatar ở đây (nếu có thêm code phía sau)
        profile = request.env['student.user.profile'].sudo().search([('student_code', '=', student_code)], limit=1)
        if not profile or not profile.avatar_url:
            return Response(status=404)

        try:
            resp = py_requests.get(profile.avatar_url, timeout=10)
            if resp.status_code == 200:
                return Response(
                    resp.content,
                    content_type=resp.headers.get("Content-Type", "image/jpeg"),
                    headers=self._get_cors_headers()
                )
        except Exception as e:
            return Response(str(e), status=500, headers=self._get_cors_headers())
    # Đăng nhập Oauth (Odoo)
    @http.route('/api/public_user/oauth', type='http', auth='public', methods=['POST','OPTIONS'], csrf=False)
    def oauth_login(self):   
        if request.httprequest.method == 'OPTIONS':
            return Response(status=200, headers=self._get_cors_headers())
     
        params = request.httprequest.get_json(force=True, silent=True) or {}
        user_id = params.get('user_id')

        email = params.get('email')
        gender = params.get('gender')
        phone = params.get('phone')
        fullname = params.get('fullname')
        avatar = params.get('avatar')
        fcm_device_token = params.get('fcm_device_token')
        device_id = params.get('device_id')
        
        provider = params.get('provider')
        token = params.get('token')
        try:
            image_data = False
            if avatar:
                try:
                    resp = py_requests.get(avatar)
                    if resp.status_code == 200:
                        image_data = base64.b64encode(resp.content).decode('utf-8')
                except Exception:
                    image_data = False
            # Kiểm tra xem user_id có được cung cấp không
            user = request.env['res.users'].sudo().browse(user_id) if user_id else request.env['res.users'].sudo().search([('login', '=', email)], limit=1)
            if not user.exists():
                # Nếu không có user_id, tạo mới user
                # Đảm bảo login không null
                login_value = email or f'{provider or "oauth"}_user'
                if not login_value:
                    login_value = f'oauth_user_{int(datetime.now().timestamp())}'
                
                vals = {
                    'name': fullname or 'Oauth User',
                    'login': login_value,
                    'active': True,
                    'email': email,
                    'groups_id': [(6, 0, [request.env.ref('base.group_system').id])],
                    'image_1920': image_data,
                }
                user = request.env['res.users'].sudo().create(vals)
                # Tạo Thông tin cá nhân:
                profile = request.env['student.admin.profile'].sudo().search([('user_id', '=', user.id)], limit=1)
                if not profile:
                    profile = request.env['student.admin.profile'].sudo().create({
                        'user_id': user.id,
                        'fcm_token': fcm_device_token,
                        'device_id': device_id,
                        'phone': phone,
                        'gender': gender,
                        'email': email,
                        #các thông tin khác chờ duyệt
                    })
                else:
                    profile.sudo().write({
                        'fcm_token': fcm_device_token,
                        'device_id': device_id,
                        'phone': phone,
                        'gender': gender,
                        'email': email,
                        #các thông tin khác chờ duyệt
                    })
  
                # Tạo student.admin.oauth record
                oauth = request.env['student.admin.oauth'].sudo().search([('user_id', '=', user.id), ('provider', '=', provider)], limit=1)
                if not oauth:
                    oauth = request.env['student.admin.oauth'].sudo().create({
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
            else:
                # Nếu đã có user, cập nhật thông tin
                user.sudo().write({
                    'image_1920': image_data,
                })
                # Cập nhật hoặc tạo AdminProfile
                # Tạo Thông tin cá nhân:
                profile = request.env['student.admin.profile'].sudo().search([('user_id', '=', user.id)], limit=1)
                if not profile:
                    profile = request.env['student.admin.profile'].sudo().create({
                        'user_id': user.id,
                        'fcm_token': fcm_device_token,
                        'device_id': device_id,
                        'phone': phone,
                        'gender': gender,
                        'email': email,
                        #các thông tin khác chờ duyệt
                    })
                else:
                    profile.sudo().write({
                        'fcm_token': fcm_device_token,
                        'device_id': device_id,
                        'phone': phone,
                        'gender': gender,
                        'email': email,
                        #các thông tin khác chờ duyệt
                    })

                # Tạo student.admin.oauth record
                oauth = request.env['student.admin.oauth'].sudo().search([('user_id', '=', user.id), ('provider', '=', provider)], limit=1)
                if not oauth:
                    oauth = request.env['student.admin.oauth'].sudo().create({
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
            oauths = request.env['student.admin.oauth'].sudo().search([('user_id', '=', user.id)])
            
            jwt_token = generate_jwt_token(user.id, SECRET_KEY)
            refresh_token = generate_jwt_token(user.id, REFRESH_KEY)
            # Trả về thông tin Đăng nhập thành công        
            return Response(
                json.dumps({'success': True if profile.activated else False, 'message':  'Thành công' if profile.activated else 'Tài khoản chưa được kích hoạt', 'data': {
                    'id': user.id,
                    'email': email,
                    'fullname': fullname,
                    'avatar_url': avatar,
                    'activated': profile.activated if profile else False,
                    'title_name': str(profile.title_name or '') if profile else '',
                    'dormitory_area_id': profile.dormitory_area_id.id if profile and profile.dormitory_area_id else 0,
                    'dormitory_clusters': profile.dormitory_clusters.ids if profile and profile.dormitory_clusters else [],
                    'oauth': oauth.provider if oauth else '',
                    'providers': oauths.mapped('provider'),
                    'access_token': jwt_token,
                    'refresh_token': refresh_token,
                }}),
                content_type='application/json',
                status=200,
                headers=self._get_cors_headers()
            )

        except Exception as e:
            return Response(
                json.dumps({'success': False, 'message': str(e)}),
                content_type='application/json',
                status=200,
                headers=self._get_cors_headers()
            )

