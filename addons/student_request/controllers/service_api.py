from odoo import http, models, fields
from odoo.http import request, Response
from odoo.fields import Datetime
from firebase_admin import messaging, credentials, initialize_app
import requests as py_requests
import json
import base64
import os
import jwt

from datetime import datetime
from datetime import timedelta
# Chuyển đổi định dạng ngày từ dd/MM/yyyy sang yyyy-MM-dd
def convert_date(date_str):
    if not date_str:
        return False
    try:
        # Nếu đúng định dạng dd/MM/yyyy thì chuyển sang yyyy-MM-dd
        return datetime.strptime(date_str, '%d/%m/%Y').strftime('%Y-%m-%d')
    except Exception:
        return date_str  # Nếu đã đúng định dạng thì giữ nguyên

# Khai báo constant secretKey random
SECRET_KEY = 'access-motcua-student-service-maiatech'
REFRESH_KEY = 'refresh-motcua-student-service-maiatech'
FIREBASE_SDK_JSON = 'firebase-adminsdk-fbsvc-75fb4407a3.json'
_firebase_app = None


def generate_jwt_token(uid, secretkey):
    payload = {
        'uid': uid,
        'exp': Datetime.now() + timedelta(days=30),
        'app': 'student_service_maiatech',
    }
    token = jwt.encode(payload, secretkey, algorithm='HS256')
    return token

def decode_jwt_token(token, secretkey):
    try:
        payload = jwt.decode(token, secretkey, algorithms=['HS256'])
        return payload
    except jwt.ExpiredSignatureError:
        return {'error': 'Token expired'}
    except jwt.InvalidTokenError:
        return {'error': 'Invalid token'}

def check_jwt_token(request, secretkey):
    try:
        auth_header = request.httprequest.headers.get('Authorization')
        token = None
        if auth_header and auth_header.lower().startswith('bearer '):
            token = auth_header[7:]
        else:
            token = request.httprequest.headers.get('token')

        payload = jwt.decode(token, secretkey, algorithms=['HS256'])
        # Nếu decode thành công, kiểm tra thời hạn token
        exp = payload.get('exp')
        if exp and datetime.utcnow().timestamp() > exp:
            raise jwt.ExpiredSignatureError
        return True
    except jwt.ExpiredSignatureError:
        return Response(
            json.dumps({'success': False, 'message': 'Token expired or Invalid', 'data': ''}),
            content_type='application/json',
            status=401,
            headers=[
                ('Access-Control-Allow-Origin', '*'),
                ('Access-Control-Allow-Methods', 'GET, POST, OPTIONS'),
                ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
            ]
        )

    except Exception as e:
        return Response(
            json.dumps({'success': False, 'message': str(e), 'data': ''}),
            content_type='application/json',
            status=401,
            headers=[
                ('Access-Control-Allow-Origin', '*'),
                ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
            ]
        )

def get_firebase_app():
    global _firebase_app
    if _firebase_app is None:
        json_path = os.path.join(os.path.dirname(__file__), '../security/' + FIREBASE_SDK_JSON)
        cred = credentials.Certificate(json_path)
        _firebase_app = initialize_app(cred)
    return _firebase_app

# Gửi FCM object Notify đến người dùng
def send_fcm_notify(env, notify, data):
    firebase_app = get_firebase_app()

    notify.fcm_success_count = 0
    notify.fcm_failure_count = 0
    notify.fcm_responses = ''

    if notify.user_ids:
        try:
            tokens = []
            profiles = env['student.user.profile'].sudo().search([('user_id', 'in', notify.user_ids.ids)])
            tokens = [p.fcm_token for p in profiles if p.fcm_token]

            message = messaging.MulticastMessage(
                notification=messaging.Notification(
                    title=notify.title,
                    body=notify.body,
                ),
                tokens=tokens,
                data=data if data else None,
            )
            response = messaging.send_each_for_multicast(message, app=firebase_app)
            notify.fcm_success_count += response.success_count
            notify.fcm_failure_count += response.failure_count
        except Exception as e:
            notify.fcm_responses += str(e)

    if notify.dormitory_cluster_ids:
        try:
            cluster_names = notify.dormitory_cluster_ids.mapped('name')
            topics = ' || '.join([f"'{name}' in topics" for name in cluster_names])

            message = messaging.Message(
                notification=messaging.Notification(
                    title=notify.title,
                    body=notify.body,
                ),
                condition=topics,
                data=data if data else None,
            )
            response = messaging.send(message, app=firebase_app)
            notify.fcm_success_count += response.success_count
            notify.fcm_failure_count += response.failure_count
        except Exception as e:
            notify.fcm_responses += str(e)

    return notify

# Gửi FCM đến danh sách users (nếu user đó có FCM token) và tạo bản ghi Notify
def send_fcm_users(env, user_ids, title, body, data):
    firebase_app = get_firebase_app()

    tokens = []
    admins_profiles = env['student.admin.profile'].sudo().search([('user_id', 'in', user_ids)])
    users_profiles = env['student.user.profile'].sudo().search([('user_id', 'in', user_ids)])
    tokens += [p.fcm_token for p in admins_profiles if p.fcm_token]
    tokens += [p.fcm_token for p in users_profiles if p.fcm_token]

    message = messaging.MulticastMessage(
        notification=messaging.Notification(title=title, body=body),
        tokens=tokens,
        data=data if data else None,
    )

    notify = env['student.notify'].sudo().create({
        'notify_type': 'users',
        'title': title,
        'body': body,
        'data': data,
        'user_ids': user_ids,
        'fcm_success_count': 0,
        'fcm_failure_count': 0,
        'fcm_responses': '',
    })

    try:
        response = messaging.send_each_for_multicast(message, app=firebase_app)
        notify.sudo().write({
            'fcm_success_count': response.success_count,
            'fcm_failure_count': response.failure_count,
            'fcm_responses': '',
        })
    except Exception as e:
        notify.sudo().write({
            'fcm_responses': str(e),
        })

    return notify

# Gửi FCM object Notify đến người dùng (trên web) 
def send_fcm_notify_old(env, notify, data):
    json_path = os.path.join(os.path.dirname(__file__), '../security/' + FIREBASE_SDK_JSON)
    if not hasattr(send_fcm_notify, 'firebase_app'):
        cred = credentials.Certificate(json_path)
        send_fcm_notify.firebase_app = initialize_app(cred)

    notify.fcm_success_count = 0
    notify.fcm_failure_count = 0
    notify.fcm_responses = ''

    if notify.user_ids:  
        try:  
            tokens = []
            profiles = env['student.user.profile'].sudo().search([('user_id', 'in', notify.user_ids.ids)])
            for profile in profiles:
                if profile.fcm_token:
                    tokens.append(profile.fcm_token)

            message = messaging.MulticastMessage(
                notification=messaging.Notification(
                    title = notify.title,
                    body = notify.body,
                ),
                tokens=tokens,
                data=data if data else None,
            )
            response = messaging.send_each_for_multicast(message, app=send_fcm_notify.firebase_app)
            notify.fcm_success_count += response.success_count
            notify.fcm_failure_count += response.failure_count
            # notify.fcm_responses += response.responses if response.responses else ''
        except Exception as e:
            notify.fcm_responses += str(e)

    if notify.dormitory_cluster_ids:  
        try:  
            cluster_names = notify.dormitory_cluster_ids.mapped('name')
            topics = ' || '.join([f"'{name}' in topics" for name in cluster_names])
            
            message = messaging.Message(
                notification=messaging.Notification(
                    title = notify.title,
                    body = notify.body,
                ),
                condition=topics,
                data=data if data else None,
            )
            response = messaging.send(message, app=send_fcm_notify.firebase_app)
            notify.fcm_success_count += response.success_count
            notify.fcm_failure_count += response.failure_count
            # notify.fcm_responses += response.responses if response.responses else ''
        except Exception as e:
            notify.fcm_responses += str(e)
            pass

    return notify


# Gửi FCM đến danh sách users (nếu user đó có FCM token) và tạo 1 bản ghi Notify
def send_fcm_users_old(env, user_ids, title, body, data):
    json_path = os.path.join(os.path.dirname(__file__), '../security/' + FIREBASE_SDK_JSON)
    if not hasattr(send_fcm_users, 'firebase_app'):
        cred = credentials.Certificate(json_path)
        send_fcm_users.firebase_app = initialize_app(cred)

    tokens = []
    admins_profiles = env['student.admin.profile'].sudo().search([('user_id', 'in', user_ids)])
    users_profiles = env['student.user.profile'].sudo().search([('user_id', 'in', user_ids)])
    for profile in admins_profiles:
        if profile.fcm_token:
            tokens.append(profile.fcm_token)
    for profile in users_profiles:
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
    # Tạo bản ghi notification
    vals = env['student.notify'].sudo().create({
        'notify_type': 'users',
        'title': title,
        'body': body,
        'data': data,
        'user_ids': user_ids,

        'fcm_success_count': 0,
        'fcm_failure_count': 0,
        'fcm_responses': '',
    })

    try:
        response = messaging.send_each_for_multicast(message, app=send_fcm_users.firebase_app)

        vals.fcm_responses = str(e)
        vals.sudo().write({
            'fcm_success_count': response.success_count,
            'fcm_failure_count': response.failure_count,
            'fcm_responses': str(e),
        })
        return vals
    except Exception as e:
        vals.fcm_responses = str(e)
        vals.sudo().write({
            'fcm_responses': str(e),
        })
        return vals

# Thêm người dùng vào topic Firebase
def add_user_to_firebase_topic(env, user_id, topic_area, topic_cluster):
    profile = env['student.user.profile'].sudo().search([('user_id', '=', user_id)], limit=1)
    if not profile or not profile.fcm_token:
        return {'success': False, 'message': 'User FCM token not found'}
    json_path = os.path.join(os.path.dirname(__file__), '../security/' + FIREBASE_SDK_JSON)
    if not hasattr(add_user_to_firebase_topic, 'firebase_app'):
        cred = credentials.Certificate(json_path)
        add_user_to_firebase_topic.firebase_app = initialize_app(cred)
    try:
        response = messaging.subscribe_to_topic([profile.fcm_token], topic_area, app=add_user_to_firebase_topic.firebase_app)
        response = messaging.subscribe_to_topic([profile.fcm_token], topic_cluster, app=add_user_to_firebase_topic.firebase_app)
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
    json_path = os.path.join(os.path.dirname(__file__), '../security/' + FIREBASE_SDK_JSON)
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

# Tạo Request mới
def create_request(env, serviceid, requestid, userid, note, attachments):
    service = env['student.service'].browse(int(serviceid))
    user_name = 'Yêu cầu dịch vụ: '
    user = env['res.users'].sudo().browse(int(userid))
    if not user: return False
    vals = {}
    requestid = int(requestid)
    if requestid > 0:
        vals = env['student.service.request'].browse(requestid)
        if vals.exists():
            vals['name'] = f'{user.name}: {service.name}'
            vals['service_id'] = service.id
            vals['request_user_id'] = user.id
            vals['note'] = note
            vals['image_attachment_ids'] = [(6, 0, attachments if attachments else [])]
            vals['request_date'] = Datetime.now()

            vals['final_state'] = 'pending'
            env['student.service.request'].sudo().write(vals)
            if len(vals.step_ids) > 0:
                return vals
    else:
        vals = {
            'name': f'{user.name}: {service.name}',
            'service_id': service.id,
            'request_user_id': user.id,
            'note': note,
            'image_attachment_ids': [(6, 0, attachments if attachments else [])],
            'request_date': Datetime.now(),
            'final_state': 'pending',
        }
    # Tạo các bản ghi student.service.request.step ứng với mỗi bước duyệt của dịch vụ
    _steps = service.step_ids.sorted('sequence')
    step_ids = []
    for step in _steps:
        step_request = env['student.service.request.step'].create({
            'request_id': False,
            'base_step_id': step.id,
            'state': 'pending',
        })
        # Tạo file_checkbox_ids cho từng file của step
        # Nếu là bước đầu tiên, tạo các bản ghi file_checkbox ứng với mỗi file trong service.files
        if step == _steps[0]:
            if service.files:
                step_request.file_ids = [(6, 0, service.files.ids)]
        step_ids.append(step_request.id)
    if step_ids:
        vals['step_ids'] = [(6, 0, step_ids)]

    # Ai sẽ duyệt dịch vụ này:
    if service.users:
        vals['users'] = [(6, 0, service.users.ids)]
    if service.role_ids:
        vals['role_ids'] = [(6, 0, service.role_ids.ids)]

    if requestid == 0:
        vals = env['student.service.request'].sudo().create(vals)    
    return vals

#Duyệt 1 bước (env, dịch vụ, bước, người duyệt, ghi chú, file đính kèm)
def update_request_step(env, requestid, stepid, userid, note, act, nextuserid, docs, final_data):
    request = env['student.service.request'].browse(requestid)
    step = request.step_ids.browse(stepid)
    # Lấy bước theo thứ tự sequence, lấy bước đầu tiên chưa ignored, approved hoặc rejected
    # step = service.step_ids.filtered(lambda s: s.state not in ('ignored', 'approved', 'rejected')).sorted('sequence')
    # step = step[0] if step else service.step_ids.browse(stepid)
    if not step.exists():
        return False
    # nếu act khác pending thì tìm các bước trước đó còn pending cập nhật nó thanh ignored
    if act != 'pending':
        prev_steps = request.step_ids.filtered(lambda s: s.base_secquence < step.base_secquence and (s.state == 'pending' or s.state != 'assigned' or s.state != 'rejected'))
        for s in prev_steps:
            s.state = 'ignored'
            # Tạo bản ghi history cho các bước đã ignored
            h = env['student.service.request.step.history'].create({
                'request_id': requestid,
                'step_id': s.id,
                'state': 'ignored',
                'user_id': userid,
                'note': 'Đã bỏ qua bước này',
                'date': Datetime.now(),
            })
            # Cập nhật bản ghi request
            s.sudo().write({
                'state': 'ignored',
                'approve_content': 'Đã duyệt bước sau, bỏ qua bước này',
                'approve_date': Datetime.now(),
                'assign_user_id': [(6, 0, [nextuserid])] if nextuserid else [],
                'history_ids': [(4, h.id)],
            })

    # Tạo bản ghi history cho bước đang duyệt
    hh = env['student.service.request.step.history'].sudo().create({
        'request_id': requestid,
        'step_id': step.id,
        'state': act,
        'user_id': userid,
        'note': note,
        'date': Datetime.now(),
    })

    vals = {
        'request_id': requestid,
        'base_step_id': step.base_step_id.id if step.base_step_id else False,
        'approve_content': note,
        'state': act,
        'approve_date': Datetime.now(),
        'assign_user_id': [(6, 0, [nextuserid])] if nextuserid else [],
        'history_ids': [(4, hh.id)],
    }
    
    if step.base_secquence == 1:
        vals['file_ids'] = step.file_ids
        vals['file_checkbox_ids'] = step.file_checkbox_ids
    if step.base_secquence == 99:
        vals['final_data'] = final_data

    # Update database: request các field: approve_content approve_date final_state final_data
    request.sudo().write({
        'users': [(4, nextuserid)] if nextuserid else [],
        'approve_content': note,
        'approve_date': Datetime.now(),
        'approve_user_id': nextuserid if nextuserid else False,
        'final_state': act,
        'final_data': final_data if step.base_step_id.sequence == 99 else '',
    })

    return vals

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

    # API làm mới JWT token
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

            # Nếu API trả về Json
            if external_resp.headers.get('Content-Type') == 'application/json':
                external_data = external_resp.json()
                if not external_data.get('Success'):
                    return Response(
                        json.dumps({'success': False, 'message': external_data.get('Message', 'Lỗi kết nối với hệ thống QLSV!'), 'data': ''}),
                        content_type='application/json',
                        status=500,
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
                    'title_name': profile.title_name if profile else '',
                    'dormitory_area_id': profile.dormitory_area_id.id if profile and profile.dormitory_area_id else 0,
                    'dormitory_cluster_id': profile.dormitory_cluster_id.id if profile and profile.dormitory_cluster_id else 0,
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

    # Tạo yêu cầu dịch vụ mới
    # Fromdata: { service_id, request_user_id, note, files: [file1, file2, ...] }
    @http.route('/api/service/request/create', type='http', auth='public', methods=['POST'], csrf=False)
    def create_service_request(self, **post):
        # Kiểm tra JWT token
        #checklogin = check_jwt_token(request, SECRET_KEY)
        #if checklogin != True: return checklogin #Response lỗi nếu không hợp lệ

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
        request_id = httprequest.form.get('request_id', 0)  # Có thể có request_id nếu là cập nhật
        request_user_id = httprequest.form.get('request_user_id')
        assign_user_id = httprequest.form.get('assign_user_id')
        note = httprequest.form.get('note', '')

        service = request.env['student.service'].sudo().browse(int(service_id)) if service_id else None
        if not service or not service.exists():
            return Response(
                json.dumps({'success': False, 'message': 'Service not found'}),
                content_type='application/json',
                status=404,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )       

        vals = {}   
        try:
            vals = create_request(request.env, service_id, request_id, request_user_id, note, attachment_ids)
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
                    'id': vals.id,
                    'service_id': vals.service_id.id,
                    'service_name': vals.service_id.name,
                    'content': vals.note,
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
        

    # TODO Lấy các yêu cầu dịch vụ của 1 User có kèm lịch sử duyệt
    @http.route('/api/service/request/user', type='http', auth='public', methods=['GET'], csrf=False)
    def list_requests_by_user(self):
        domain = []
        params = request.httprequest.get_json(force=True, silent=True) or {}
        try:
            user_id = params.get('user_id')
            print("GET API /api/service/request/user:", user_id)
            if user_id:
                domain.append(('request_user_id', '=', user_id))
            requests = request.env['student.service.request'].sudo().search(domain)

            result = []
            for req in requests:
                sumhistories = []
                for step in req.step_ids:
                    for h in step.history_ids:
                        sumhistories.append({
                            'id': h.id,
                            'step_id': step.id,
                            'step_name': step.base_step_id.name if step.base_step_id else '',
                            'state': h.state,
                            'user_id': h.user_id.id if h.user_id else None,
                            'user_name': h.user_id.name if h.user_id else '',
                            'note': h.note,
                            'date': h.date.strftime('%Y-%m-%d %H:%M:%S') if h.date else '',
                        })

                result.append({
                    'id': req.id,

                    'service': {
                        'id': req.service_id.id,
                        'name': req.service_id.name,
                        'description': req.service_id.description,
                    } if req.service_id else {},

                    'name': req.name,
                    'note': req.note,
                    'request_date': req.request_date and req.request_date.strftime('%Y-%m-%d %H:%M:%S') or '',
                    'approve_user_id': req.approve_user_id.id if req.approve_user_id else None,
                    'approve_user_name': req.approve_user_id.name if req.approve_user_id else '',
                    'approve_content': req.approve_content,
                    'approve_date': req.approve_date and req.approve_date.strftime('%Y-%m-%d %H:%M:%S') or '',
                    'final_state': req.final_state,
                    'finalfinal_data': req.final_data,

                    'histories': sorted(sumhistories, key=lambda x: x['date'], reverse=True),
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

    # Lấy danh sách các yêu cầu dịch vụ theo: Quyền duyệt của user_id
    @http.route('/api/service/request/list', type='http', auth='public', methods=['GET'], csrf=False)
    def list_service_requests(self, **post):
        domain = []
        params = request.httprequest.get_json(force=True, silent=True) or {}
        try:
            user_id = int(params.get('user_id')) if params.get('user_id') else 0
            aprofile = request.env['student.admin.profile'].sudo().search([('user_id', '=', user_id)], limit=1) if user_id else None
            
            # Lọc các yêu cầu dịch vụ mà user_id nằm trong users hoặc một trong các role_id của aprofile nằm trong role_ids

            domain.append('|')
            domain.append(('users', 'in', [user_id]))
            domain.append(('role_ids', 'in', aprofile.role_ids.ids))

            requests = request.env['student.service.request'].sudo().search(domain)

            results = []
            for req in requests:
                steps = []
                for step in req.step_ids:
                    steps.append({
                        'id': step.id,
                        'name': step.base_step_id.name if step.base_step_id else '',
                        'state': step.state,
                        'base_secquence': step.base_secquence,
                        'approve_content': step.approve_content,
                        'approve_date': step.approve_date and step.approve_date.strftime('%Y-%m-%d %H:%M:%S') or '',
                        'history_ids': [
                            {
                                'state': f.state,
                                'note': f.note,
                                'date': f.date and f.date.strftime('%Y-%m-%d %H:%M:%S') or '',
                                'user_id': f.user_id.name if f.user_id.name else '[Admin]',
                            } for f in step.history_ids
                        ],
                    })
                # Sắp xếp các bước theo sequence tăng dần
                steps = sorted(steps, key=lambda x: x['base_secquence'])
                results.append({
                    'id': req.id,

                    'name': req.name,
                    'note': req.note,
                    'request_date': req.request_date and req.request_date.strftime('%Y-%m-%d %H:%M:%S') or '',
                    'approve_user_id': req.approve_user_id.id if req.approve_user_id else None,
                    'approve_user_name': req.approve_user_id.name if req.approve_user_id else '',
                    'approve_content': req.approve_content,
                    'approve_date': req.approve_date and req.approve_date.strftime('%Y-%m-%d %H:%M:%S') or '',
                    'final_state': req.final_state,
                    'finalfinal_data': req.final_data,

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
                    'data': results
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
                json.dumps({'success': False, 'message': str(e), 'data': []}),
                content_type='application/json',
                status=500,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )

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

    # Lấy danh sách các Files trong student.service.file
    @http.route('/api/service/files', type='http', auth='public', methods=['GET'], csrf=False)
    def get_service_files(self):
        files = request.env['student.service.file'].sudo().search([])
        data = [{'id': f.id, 'name': f.name, 'description': f.description} for f in files]
        return Response(
            json.dumps({'success': True, 'message': 'Danh sách files', 'data': data}),
            content_type='application/json',
            status=200,
            headers=[
                ('Access-Control-Allow-Origin', '*'),
                ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
            ]
        )

    # Lấy chi tiết 1 yêu cầu dịch vụ
    @http.route('/api/service/request/detail/<int:request_id>', type='http', auth='public', methods=['GET'], csrf=False)
    def get_service_request_detail(self, request_id):
        req = request.env['student.service.request'].sudo().browse(request_id)
        if not req.exists():
            return Response(
                json.dumps({'success': False, 'message': 'Service request not found', 'data': {}}),
                content_type='application/json',
                status=404,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )

        sumhistories = []
        for step in req.step_ids:
            for h in step.history_ids:
                sumhistories.append({
                    'id': h.id,
                    'step_id': step.id,
                    'step_name': step.base_step_id.name if step.base_step_id else '',
                    'state': h.state,
                    'user_id': h.user_id.id if h.user_id else None,
                    'user_name': h.user_id.name if h.user_id else '',
                    'note': h.note,
                    'date': h.date.strftime('%Y-%m-%d %H:%M:%S') if h.date else '',
                })
        req_data = {
            'id': req.id,
            
            'service_id': req.service_id.id if req.service_id else None,
            'name': req.name,
            'note': req.note,
            
            'image_attachment_ids': [{'id': att.id, 'name': att.name, 'url': att.public_url if hasattr(att, 'public_url') else ''} for att in req.image_attachment_ids],
            'request_date': req.request_date.strftime('%Y-%m-%d %H:%M:%S') if req.request_date else '',
            
            'request_user_id': req.request_user_id.id if req.request_user_id else None,
            'request_user_name': req.request_user_id.name if req.request_user_id else '',

            'step_ids': [{
                'id': step.id,
                'name': step.base_step_id.name if step.base_step_id else '',
                'state': step.state,
                'sequence': step.base_step_id.sequence if step.base_step_id else 0,
                'approve_content': step.approve_content,
                'approve_date': step.approve_date.strftime('%Y-%m-%d %H:%M:%S') if step.approve_date else '',
                'file_ids': [{'id': f.id, 'name': f.name, 'description': f.description} for f in step.file_ids],
                'file_checkbox_ids': [{'id': f.id, 'name': f.name, 'description': f.description} for f in step.file_checkbox_ids],
                'history_ids': [{
                    'id': h.id,
                    'state': h.state,
                    'user_id': h.user_id.id if h.user_id else None,
                    'user_name': h.user_id.name if h.user_id else '',
                    'note': h.note,
                    'date': h.date.strftime('%Y-%m-%d %H:%M:%S') if h.date else '',
                } for h in step.history_ids],
            } for step in req.step_ids],
            'users': [{'id': u.id, 'name': u.name} for u in req.users],
            'role_ids': [{'id': r.id, 'name': r.name} for r in req.role_ids],

            'final_state': req.final_state,
            'final_data': req.final_data,
            'approve_content': req.approve_content,
            'approve_date': req.approve_date.strftime('%Y-%m-%d %H:%M:%S') if req.approve_date else '',
            'histories': sumhistories,
        }

        return Response(
            json.dumps({'success': True, 'message': 'Thành công', 'data': req_data}),
            content_type='application/json',
            status=200,
            headers=[
                ('Access-Control-Allow-Origin', '*'),
                ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
            ]
        )

    # Submit 1 bước duyệt
    @http.route('/api/service/request/step/submit', type='json', auth='public', methods=['POST'], csrf=False)
    def submit_service_request_step(self, **post):
        params = request.httprequest.get_json(force=True, silent=True) or {}
        # Đầu vao: { step_id, approve_content, user_id, action, file_checked_ids, final_data } 
        # nếu là base_sequence = 1: file_checked_ids: [file_id1, file_id2, ...]
        # nếu là base_sequence = 99: final_data
        requestid = params.get('request_id')
        stepid = params.get('step_id') 
        userid = params.get('user_id')          # User thực hiện duyệt
        note = params.get('note', '')           # Nột dung duyệt
        act = params.get('act', '')             # action: 'pending', 'assigned', 'ignored', 'approved', 'rejected'
        nextuserid = params.get('next_user_id') # User tiếp theo xử lý yêu cầu
        docs = params.get('docs')               # Danh sách file đính kèm nếu bước = 1
        final_data = params.get('final_data')   # Nếu duyệt bước 99 cuối

        if not stepid:
            return Response(
                json.dumps({'success': False, 'message': 'Missing step_id', 'data': []}),
                content_type='application/json',
                status=400,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )

        try:
            step = request.env['student.service.request.step'].sudo().browse(step_id)
            if not step:
                return Response(
                    json.dumps({'success': False, 'message': 'Step not found', 'data': []}),
                    content_type='application/json',
                    status=404,
                    headers=[
                        ('Access-Control-Allow-Origin', '*'),
                        ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                        ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ]
                )

            # Xử lý logic duyệt bước ở đây
            step = update_request_step(request.env, requestid, stepid, userid, note, act, nextuserid, docs, final_data)
            request.env['student.service.request.step'].sudo().write(step)

            return Response(
                json.dumps({'success': True, 'message': 'Bước duyệt thành công', 'data': step.read()}),
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

    # Lấy danh sách thông báo của user
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
    @http.route('/api/service/request/approve', type='http', auth='public', methods=['POST'], csrf=False)
    def approve_service_request(self, **post):
        params = request.httprequest.get_json(force=True, silent=True) or {}
        request_id = params.get('request_id')
        user_id = params.get('user_id')
        asign_user_id = params.get('asign_user_id')
        step_id = params.get('step_id')
        checked_ids = params.get('checked_ids')
        state = params.get('state', '')
        note = params.get('note', '')
        final = params.get('final', '')

        if not request_id or not user_id or not step_id:
            return Response(
                json.dumps({'success': False, 'message': 'Missing request_id, user_id, or step_id'}),
                content_type='application/json',
                status=400,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )

        req = request.env['student.service.request'].sudo().browse(int(request_id))
        user = request.env['res.users'].sudo().browse(int(user_id))
        step = request.env['student.service.request.step'].sudo().browse(int(step_id))

        if not req.exists() or not user.exists() or not step.exists():
            return Response(
                json.dumps({'success': False, 'message': 'Request, user, or step not found'}),
                content_type='application/json',
                status=404,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )

        # Kiểm tra quyền duyệt
        # if user not in req.users:
        #     return Response(
        #         json.dumps({'success': False, 'message': 'User does not have approval rights'}),
        #         content_type='application/json',
        #         status=403,
        #         headers=[
        #             ('Access-Control-Allow-Origin', '*'),
        #             ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
        #             ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
        #         ]
        #     )

        try:
            # Cập nhật bước duyệt
            vals = update_request_step(request.env, request_id, step_id, user_id, note, state, asign_user_id, checked_ids, final)
            step.sudo().write(vals)
            return Response(
                json.dumps({'success': True, 'message': 'Yêu cầu đã được duyệt', 'data': {'request_id': req.id, 'step_id': step.id, 'user_id': user.id, 'state': state, 'note': note}}),
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
        