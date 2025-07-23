from odoo import http, models, fields
from odoo.http import request, Response
from odoo.fields import Datetime
import requests as py_requests

import json
import base64

from datetime import datetime
# Chuyển đổi định dạng ngày từ dd/MM/yyyy sang yyyy-MM-dd
def convert_date(date_str):
    if not date_str:
        return False
    try:
        # Nếu đúng định dạng dd/MM/yyyy thì chuyển sang yyyy-MM-dd
        return datetime.strptime(date_str, '%d/%m/%Y').strftime('%Y-%m-%d')
    except Exception:
        return date_str  # Nếu đã đúng định dạng thì giữ nguyên
        
import os
from firebase_admin import messaging, credentials, initialize_app
# Gửi thông báo FCM đến người dùng
def send_fcm_user(env, user_ids, title, body, data):
    json_path = os.path.join(os.path.dirname(__file__), '../security/serviceAccountKey.json')
    if not hasattr(send_fcm_user, 'firebase_app'):
        cred = credentials.Certificate(json_path)
        send_fcm_user.firebase_app = initialize_app(cred)
    tokens = []
    profiles = env['student.user.profile'].sudo().search([('user_id', 'in', user_ids)])
    for profile in profiles:
        if profile.fcm_token:
            tokens.append(profile.fcm_token)

    message = messaging.MulticastMessage(
        notification=messaging.Notification(
            title=title,
            body=body,
        ),
        tokens=tokens,
        data=data if data else None,
    )

    try:
        response = messaging.send_each_for_multicast(message, app=send_fcm_admin.firebase_app)
        return {
            'success_count': response.success_count,
            'failure_count': response.failure_count,
            'responses': [r.__dict__ for r in response.responses],
        }
    except Exception as e:
        return { 'success_count': 0, 'failure_count': 0, 'responses': [], 'error': str(e) }

# Gửi thông báo FCM đến quản trị viên
def send_fcm_admin(env, user_ids, title, body, data):
    json_path = os.path.join(os.path.dirname(__file__), '../security/serviceAccountKey.json')
    if not hasattr(send_fcm_admin, 'firebase_app'):
        cred = credentials.Certificate(json_path)
        send_fcm_admin.firebase_app = initialize_app(cred)
    tokens = []
    admin_profiles = env['student.admin.profile'].sudo().search([('user_id', 'in', user_ids)])
    for profile in admin_profiles:
        if profile.fcm_token:
            tokens.append(profile.fcm_token)

    message = messaging.MulticastMessage(
        notification=messaging.Notification(
            title=title,
            body=body,
        ),
        tokens=tokens,
        data=data if data else None,
    )

    try:
        response = messaging.send_each_for_multicast(message, app=send_fcm_admin.firebase_app)
        return {
            'success_count': response.success_count,
            'failure_count': response.failure_count,
            'responses': [r.__dict__ for r in response.responses],
        }
    except Exception as e:
        return { 'success_count': 0, 'failure_count': 0, 'responses': [], 'error': str(e) }

# Thêm người dùng vào topic Firebase
def add_user_to_firebase_topic(env, user_id, topic_area, topic_cluster):
    profile = env['student.user.profile'].sudo().search([('user_id', '=', user_id)], limit=1)
    if not profile or not profile.fcm_token:
        return {'success': False, 'message': 'User FCM token not found'}
    json_path = os.path.join(os.path.dirname(__file__), '../security/serviceAccountKey.json')
    if not hasattr(add_user_to_firebase_topic, 'firebase_app'):
        cred = credentials.Certificate(json_path)
        add_user_to_firebase_topic.firebase_app = initialize_app(cred)
    try:
        response = messaging.subscribe_to_topic([profile.fcm_token], topic_area, app=add_user_to_firebase_topic.firebase_app)
        response = messaging.subscribe_to_topic([profile.fcm_token], topic_area + '/' + topic_cluster, app=add_user_to_firebase_topic.firebase_app)
        return {
            'success': True,
            'message': f'User subscribed to topic {topic_area + "/" + topic_cluster}',
            'response': response.__dict__
        }
    except Exception as e:
        return {'success': False, 'message': str(e)}

# Gỡ người dùng khỏi tất cả các topic Firebase
def remove_user_from_all_firebase_topics(env, user_id):
    profile = env['student.user.profile'].sudo().search([('user_id', '=', user_id)], limit=1)
    if not profile or not profile.fcm_token:
        return {'success': False, 'message': 'User FCM token not found'}
    json_path = os.path.join(os.path.dirname(__file__), '../security/serviceAccountKey.json')
    if not hasattr(remove_user_from_all_firebase_topics, 'firebase_app'):
        cred = credentials.Certificate(json_path)
        remove_user_from_all_firebase_topics.firebase_app = initialize_app(cred)
    try:
        # Lấy tất cả các topic mà user đã đăng ký (giả sử lưu trong profile, hoặc định nghĩa cứng)
        topics = []
        if profile.dormitory_area_id:
            topics.append(str(profile.dormitory_area_id))
        if profile.dormitory_cluster_id:
            topics.append(str(profile.dormitory_area_id) + '/' + str(profile.dormitory_cluster_id))
        # Có thể thêm các topic khác nếu cần
        for topic in topics:
            messaging.unsubscribe_from_topic([profile.fcm_token], topic, app=remove_user_from_all_firebase_topics.firebase_app)
        return {
            'success': True,
            'message': f'User unsubscribed from topics: {topics}',
        }
    except Exception as e:
        return {'success': False, 'message': str(e)}

# Controller cho API dịch vụ
class ServiceApiController(http.Controller):
    # Lấy danh sách các nhóm dịch vụ và các dịch vụ trong nhóm
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

    # Create public user without password
    @http.route('/api/public_user/create', type='http', auth='public', methods=['POST'], csrf=False)
    def create_public_user(self):
        params = request.httprequest.get_json(force=True, silent=True) or {}
        username = params.get('username')
        loginname = params.get('loginname')
        image_url = params.get('image_url')
        print("POST API /api/public_user/create:", params, username, image_url)
        
        if not username:
            username = "Test User"
        # Nếu có image_url, tải ảnh về và encode base64
        image_data = False
        if image_url:
            try:
                resp = py_requests.get(image_url)
                if resp.status_code == 200:
                    image_data = base64.b64encode(resp.content).decode('utf-8')
            except Exception:
                image_data = False

        vals = {
            'name': username,
            'login': loginname or username.lower().replace(' ', '_'),
            'active': True,
            'groups_id': [(6, 0, [request.env.ref('base.group_public').id])],  # chỉ gán group public
            # Không set password
        }
        if image_data:
            vals['image_1920'] = image_data

        user = request.env['res.users'].sudo().create(vals)
        return Response(
            json.dumps({
                'id': user.id,
                'name': user.name,
                'can_login': False,
                'image_1920': bool(image_data),
            }),
            content_type='application/json',
            status=200,
            headers=[
                ('Access-Control-Allow-Origin', '*'),
                ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
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

        # Kiểm tra nếu không có username thì trả về lỗi
        if not username:
            return Response(
                json.dumps({'error': 'Missing loginname'}),
                content_type='application/json',
                status=400,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )

        # Gọi API đăng nhập bên ngoài
        external_api_url = "https://sv_test.ktxhcm.edu.vn/MotCuaApi/Login"
        try:
            external_resp = py_requests.post(
                external_api_url,
                json={"username": username, "password": password},
                timeout=10,
                verify=False,  # Bỏ qua xác thực SSL
                headers={
                    "x-api-key": "motcua_ktx_maia_apikey"
                }
            )

            # Nếu API trả về lỗi HTTP khác
            if external_resp.status_code != 200:
                return Response(
                    json.dumps({'error': 'External login failed', 'detail': external_resp.text}),
                    content_type='application/json',
                    status=401,
                    headers=[
                        ('Access-Control-Allow-Origin', '*'),
                        ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                        ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ]
                )

            # Xử lý dữ liệu trả về từ API
            external_data = external_resp.json()
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
                    #'gender': gender,
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

            return Response(
                json.dumps({
                    'success': True,
                    'message': 'Đăng nhập thành công',
                    'data': {
                        'id': user.id,
                        'name': user.name,
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
                    }
                }),
                content_type='application/json',
                status=200,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
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
            # Trả về thông tin Đăng nhập thành công        
            return Response(
                json.dumps({'success': True if profile.activated else False, 'message':  'Thành công' if profile.activated else 'Tài khoản chưa được kích hoạt', 'data': {
                    'id': user.id,
                    'email': email,
                    'fullname': fullname,
                    'avatar_url': avatar,
                    'activated': profile.activated if profile else False,
                    'title_name': profile.title_name if profile else '',
                    'dormitory_area_id': profile.dormitory_area_id if profile and profile.dormitory_area_id else 0,
                    'dormitory_cluster_id': profile.dormitory_cluster_id if profile and profile.dormitory_cluster_id else 0,
                    'oauth': oauth.provider if oauth else '',
                    'providers': oauths.mapped('provider'),
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

    # Tạo yêu cầu dịch vụ mới
    # Fromdata: { service_id, request_user_id, note, files: [file1, file2, ...] }
    @http.route('/api/service/request/create', type='http', auth='public', methods=['POST'], csrf=False)
    def create_service_request(self, **post):
        httprequest = request.httprequest
        files = httprequest.files.getlist('')  # lấy tất cả file upload (không có tên field cụ thể)
        attachment_ids = []
        for file_storage in files:
            file_data = file_storage.read()
            base64_data = base64.b64encode(file_data).decode('utf-8')
            attachment = request.env['ir.attachment'].sudo().create({
                'name': file_storage.filename,
                'datas': base64_data,
                'res_model': 'student.service.request',
                'res_id': 0,
                'type': 'binary',
                'mimetype': file_storage.mimetype or 'image/png',
            })
            attachment_ids.append(attachment.id)

        # Lấy các trường khác từ form
        service_id = httprequest.form.get('service_id')
        request_user_id = httprequest.form.get('request_user_id')
        note = httprequest.form.get('note', '')

        service = request.env['student.service'].sudo().browse(int(service_id)) if service_id else None
        if not service or not service.exists():
            return Response(
                json.dumps({'error': 'Service not found'}),
                content_type='application/json',
                status=404,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )

        # Get user name from vals or fetch from user record
        user_name = 'Yêu cầu dịch vụ: '
        if request_user_id:
            user = request.env['res.users'].sudo().search([('id', '=', int(request_user_id))], limit=1)
            user_name = user.name or ''
        
        vals = {
            'name': f'{user_name}: {service.name}',
            'service_id': service.id,
            'request_user_id': user.id if user else False,
            'note': note,
            'image_attachment_ids': [(6, 0, attachment_ids)],
            'request_date': Datetime.now(),
        }
        # Tạo các bản ghi student.service.request.step ứng với mỗi bước duyệt của dịch vụ
        step_ids = service.step_ids.sorted('sequence')
        step_history_ids = []
        for step in step_ids:
            step_request = request.env['student.service.request.step'].sudo().create({
                'request_id': 0,  # sẽ cập nhật lại sau khi tạo request chính
                'base_step_id': step.id,
                'state': 'pending',
            })
            # Tạo file_checkbox_ids cho từng file của step
            # Nếu là bước đầu tiên, tạo các bản ghi file_checkbox ứng với mỗi file trong service.files
            if step == step_ids[0]:
                vals['step_id'] = step.id
                # Thêm các files cần của Dịch vụ vào file_ids
                if service.files:
                    step_request.file_ids = [(6, 0, service.files.ids)]
            step_history_ids.append(step_request.id)
        if step_history_ids:
            vals['step_history_ids'] = [(6, 0, step_history_ids)]

        # Thêm các Users trong Service.users vào Request
        if service.users:
            vals['users'] = [(6, 0, service.users.ids)]

        
        try:
            req = request.env['student.service.request'].sudo().create(vals)
            # Cập nhật res_id cho attachment
            request.env['ir.attachment'].sudo().browse(attachment_ids).write({'res_id': req.id})
        except Exception as e:
            return Response(
                json.dumps({'error': 'Failed to create service request', 'detail': str(e)}),
                content_type='application/json',
                status=500,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )

        return Response(
            json.dumps({
                'success': True,
                'message': 'Tạo yêu cầu dịch vụ thành công',
                'data': {
                    'id': req.id,
                    'service_id': req.service_id.id,
                    'service_name': req.service_id.name
                }
            }),
            content_type='application/json',
            status=200,
            headers=[
                ('Access-Control-Allow-Origin', '*'),
                ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
            ]
        )

    # Lấy các yêu cầu dịch vụ của 1 User có kèm lịch sử duyệt
    @http.route('/api/service/request/user', type='http', auth='public', methods=['GET'], csrf=False)
    def list_requests_by_user(self):
        domain = []
        params = request.httprequest.get_json(force=True, silent=True) or {}
        user_id = params.get('user_id')
        print("GET API /api/service/request/user:", user_id)
        if user_id:
            domain.append(('request_user_id', '=', user_id))
        requests = request.env['student.service.request'].sudo().search(domain)

        result = []
        for req in requests:
            steps = []
            for step in req.step_history_ids:
                steps.append({
                    'id': step.id,
                    'name': step.base_step_id.name if step.base_step_id else '',
                    'state': step.state,
                    'sequence': step.base_step_id.sequence if step.base_step_id else 0,
                    'files': [
                        {
                            'id': f.id,
                            'name': f.name,
                            'description': f.description,
                        } for f in step.file_ids
                    ],
                })
            # Sắp xếp các bước theo sequence tăng dần
            steps = sorted(steps, key=lambda x: x['sequence'])
            result.append({
                'id': req.id,
                'name': req.name,
                'note': req.note,
                'request_date': req.request_date and req.request_date.strftime('%Y-%m-%d %H:%M:%S') or '',
                'service': {
                    'id': req.service_id.id,
                    'name': req.service_id.name,
                    'description': req.service_id.description,
                } if req.service_id else {},
                'steps': steps,
            })
        # Trả về danh sách yêu cầu dịch vụ của user
        return Response(
            json.dumps({
                'success': True,
                'message': 'Thành công',
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

    # Lấy danh sách các yêu cầu dịch vụ theo: Quyền duyệt của user_id
    @http.route('/api/service/request/list', type='json', auth='public', methods=['GET'], csrf=False)
    def list_service_requests(self, **post):
        domain = []
        params = request.httprequest.get_json(force=True, silent=True) or {}
        user_id = params.get('user_id')
        print("GET API /api/service/request/list:", user_id)
        # Nếu có user_id thì lấy các request mà user này có quyền duyệt
        if user_id:
            domain.append(('users', 'in', [user_id]))
        else:
            # Nếu không có request nào thì trả về rỗng
            return Response(
                json.dumps([]),
                content_type='application/json',
                status=200,
                headers=[
                ('Access-Control-Allow-Origin', '*'),
                ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )

        requests = request.env['student.service.request'].sudo().search(domain)

        result = []
        for req in requests:
            steps = []
            for step in req.step_history_ids:
                steps.append({
                    'id': step.id,
                    'name': step.base_step_id.name if step.base_step_id else '',
                    'state': step.state,
                    'sequence': step.base_step_id.sequence if step.base_step_id else 0,
                    'files': [
                        {
                            'id': f.id,
                            'name': f.name,
                            'description': f.description,
                        } for f in step.file_ids
                    ],
                })
            # Sắp xếp các bước theo sequence tăng dần
            steps = sorted(steps, key=lambda x: x['sequence'])
            result.append({
                'id': req.id,
                'name': req.name,
                'note': req.note,
                'request_date': req.request_date and req.request_date.strftime('%Y-%m-%d %H:%M:%S') or '',
                'service': {
                    'id': req.service_id.id,
                    'name': req.service_id.name,
                    'description': req.service_id.description,
                } if req.service_id else {},
                'steps': steps,
            })
        # Trả về danh sách yêu cầu dịch vụ của user
        return Response(
            json.dumps({
                'success': True,
                'message': 'Thành công',
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


