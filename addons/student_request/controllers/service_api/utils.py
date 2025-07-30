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
        if not _apps: 
            json_path = os.path.join(os.path.dirname(__file__), '../security/' + FIREBASE_SDK_JSON)
            cred = credentials.Certificate(json_path)
            _firebase_app = initialize_app(cred)
        else:
            _firebase_app = list(_apps.values())[0]  
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
            print(f"Error sending FCM object notify: {str(e)}")

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
        print(f"Error sending FCM send_fcm_users: {str(e)}")
    return notify

# Gửi FCM với đầu vào là Request object, data sẽ là {'type': 'request', 'id': f'{request.id}'}
# send_type = 0: tạo mới, 1: cập nhật, 2: đang duyệt qua bước, 3: đã duyệt
def send_fcm_request(env, request_obj, send_type=0):
    data = {'type': 'request', 'id': str(request_obj.id)}
    # Nội dung thông báo cho người duyệt
    title = f"Có yêu cầu dịch vụ {request_obj.service_id.name} từ {request_obj.request_user_id.name}" if request_obj.service_id else f"Yêu cầu dịch vụ mới từ {request_obj.request_user_id.name}"
    body = "Bạn có một yêu cầu: " + (request_obj.note + "Hay kiểm tra chi tiết trong ứng dụng.")
    if send_type == 0:
        send_fcm_users(env, [request_obj.request_user_id.id], f'Yêu cầu dịch vụ {request_obj.service_id.name} đã được tạo thành công', f'Yêu cầu của bạn đã được tạo thành công. {request_obj.note}', data)
    elif send_type == 1:
        send_fcm_users(env, [request_obj.request_user_id.id], f'Yêu cầu dịch vụ {request_obj.service_id.name} đã được cập nhật', f'Yêu cầu của bạn đã được cập nhật. {request_obj.note}', data)
        #Nội dung thông báo cho người duyệt
        title = f"Cập nhật yêu cầu dịch vụ {request_obj.service_id.name} từ {request_obj.request_user_id.name}"
        body = "Bạn có một yêu cầu đã chỉnh sửa: " + (request_obj.note + "Hay kiểm tra chi tiết trong ứng dụng.")
    elif send_type == 2:
        send_fcm_users(env, [request_obj.request_user_id.id], f'Yêu cầu dịch vụ {request_obj.service_id.name} đã được duyệt', f'Yêu cầu của bạn đã được duyệt. {request_obj.note}', data)
        #Nội dung thông báo cho người duyệt
        title = f"Duyệt yêu cầu dịch vụ {request_obj.service_id.name} từ {request_obj.request_user_id.name}"
        body = "Bạn có một yêu cầu đã được duyệt: " + (request_obj.note + "Hay kiểm tra chi tiết trong ứng dụng.")
    elif send_type == 3:
        send_fcm_users(env, [request_obj.request_user_id.id], f'Yêu cầu dịch vụ {request_obj.service_id.name} đã được hoàn thành', f'Yêu cầu của bạn đã được hoàn thành. {request_obj.note}', data)
        #Nội dung thông báo cho người duyệt
        title = f"Hoàn thành yêu cầu dịch vụ {request_obj.service_id.name} từ {request_obj.request_user_id.name}"
        body = "Yêu cầu của bạn đã được hoàn thành: " + (request_obj.note + "Hay kiểm tra chi tiết trong ứng dụng.")

    # Gửi tới các user được gán xử lý yêu cầu này
    user_ids = request_obj.users.ids if request_obj.users else []
    if user_ids:
        return send_fcm_users(env, user_ids, title, body, data)
    return None

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