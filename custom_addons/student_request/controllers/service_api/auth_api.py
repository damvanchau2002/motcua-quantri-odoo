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


class AuthApiController(http.Controller):

    #API làm mới JWT token
    @http.route('/api/public_user/refresh_token', type='http', auth='public', methods=['POST'], csrf=False)
    def refresh_token(self):
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
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )
        payload = decode_jwt_token(token, SECRET_KEY)
        if 'error' in payload:
            return Response(
                json.dumps({'success': False, 'message': payload['error']}),
                content_type='application/json',
                status=401,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )
        uid = payload.get('uid')
        if not uid:
            return Response(
                json.dumps({'success': False, 'message': 'Invalid token payload'}),
                content_type='application/json',
                status=401,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )
        new_token = generate_jwt_token(uid, SECRET_KEY)
        return Response(
            json.dumps({'success': True, 'message': 'Token refreshed', 'token_auth': new_token}),
            content_type='application/json',
            status=200,
            headers=[
                ('Access-Control-Allow-Origin', '*'),
                ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
            ]
        )

    @http.route('/api/<path:any>', type='http', auth='public', methods=['OPTIONS'], csrf=False)
    def catch_all_options(self, any):
        return Response(
            '',
            status=200,
            headers=[
                ('Access-Control-Allow-Origin', '*'),
                ('Access-Control-Allow-Methods', 'POST, GET, OPTIONS, PUT, DELETE'),
                ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ('Access-Control-Allow-Credentials', 'true')
            ]
        )
    # Đăng nhập public user 
    @http.route('/api/public_user/login', type='http', auth='public', methods=['POST'], csrf=False)
    def public_user_login(self):
        params = request.httprequest.get_json(force=True, silent=True) or {}
        username = params.get('username')
        password = params.get('password')
        fcm_token = params.get('fcm_device_token')
        device_id = params.get('device_id')

        if not username:
            return Response(
                json.dumps({'success': False, 'message': 'Thiếu tên đăng nhập.'}),
                content_type='application/json',
                status=200,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true')
                ]
            )

        external_api_url = "https://sv_test.ktxhcm.edu.vn/MotCuaApi/Login"
        try:
            external_resp = py_requests.post(
                external_api_url,
                json={"username": username, "password": password},
                timeout=10,
                verify=False,
                headers={"x-api-key": "motcua_ktx_maia_apikey"}
            )

            if external_resp.status_code != 200:
                return Response(
                    json.dumps({
                        'success': False,
                        'message': 'Không thể kết nối tới hệ thống KTX.',
                        'detail': external_resp.text
                    }),
                    content_type='application/json',
                    status=502,
                    headers=[
                        ('Access-Control-Allow-Origin', '*'),
                        ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                        ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                        ('Access-Control-Allow-Credentials', 'true')
                    ]
                )

            content_type = external_resp.headers.get('Content-Type', '')
            if 'application/json' not in content_type:
                return Response(
                    json.dumps({'success': False, 'message': 'Phản hồi từ hệ thống KTX không đúng định dạng JSON.'}),
                    content_type='application/json',
                    status=502,
                    headers=[
                        ('Access-Control-Allow-Origin', '*'),
                        ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                        ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                        ('Access-Control-Allow-Credentials', 'true')
                    ]
                )

            external_data = external_resp.json()
            success = external_data.get('Success', False)
            data = external_data.get('Data')
            message = external_data.get('Message') or 'Lỗi không xác định từ hệ thống KTX.'

            # Thất bại logic: Success = false hoặc Data = null
            if not success or data is None:
                return Response(
                    json.dumps({
                        'success': False,
                        'message': message,
                        'data': ''
                    }),
                    content_type='application/json',
                    status=200,  # Trả về 200 để client vẫn xử lý được logic
                    headers=[
                        ('Access-Control-Allow-Origin', '*'),
                        ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                        ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                        ('Access-Control-Allow-Credentials', 'true')
                    ]
                )
            # Thành công: xử lý dữ liệu từ external API
            data = external_data.get('Data', {})

            student_code = data.get('StudentCode')
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
                vals = {
                    'name': full_name or student_code,
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
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true')
                ]
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
                    headers=[
                        ('Access-Control-Allow-Origin', '*'),
                        ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                        ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                        ('Access-Control-Allow-Credentials', 'true')
                    ]
                )
        except Exception as e:
            return Response(
                json.dumps({'success': False, 'message': str(e), 'data': ''}),
                content_type='application/json',
                status=500,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true')
                ]
            )

    # Đăng nhập Oauth (Odoo)
    @http.route('/api/public_user/oauth', type='http', auth='public', methods=['POST'], csrf=False)
    def oauth_login(self):
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
   
        if not provider or not token:
            return Response(
                json.dumps({'success': False, 'message': 'Missing provider or token'}),
                content_type='application/json',
                status=400,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )

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
                vals = {
                    'name': fullname or 'Oauth User',
                    'login': email or f'{provider}_user',
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
                status=200,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )

