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
import threading
from datetime import datetime, timedelta
import pytz
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Hàm để parse JSON an toàn, trả về dict nếu là dict, hoặc cố gắng chuyển đổi từ string
def safe_json_parse(data):
    if isinstance(data, dict):
        return data
    if isinstance(data, str):
        try:
            return json.loads(data.replace("'", '"'))  # tạm thời chuyển ' thành " nếu lỡ sai format
        except Exception:
            return {}
    return {}

# Chuyển đổi định dạng ngày từ dd/MM/yyyy sang yyyy-MM-dd
def convert_date(date_str):
    if not date_str:
        return False
    try:
        # Nếu đúng định dạng dd/MM/yyyy thì chuyển sang yyyy-MM-dd
        return datetime.strptime(date_str, '%d/%m/%Y').strftime('%Y-%m-%d')
    except Exception:
        return date_str  # Nếu đã đúng định dạng thì giữ nguyên

# Đường dẫn đến thư mục chứa file bảo mật
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SECURITY_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', '..', 'security'))


# Khai báo constant secretKey random
SECRET_KEY = 'access-motcua-student-service-maiatech'
REFRESH_KEY = 'refresh-motcua-student-service-maiatech'
FIREBASE_SDK_JSON = 'firebase-adminsdk-fbsvc-75fb4407a3.json'
# Thread lock for Firebase app initialization
_firebase_lock = threading.Lock()

# Tạo JWT token với uid và secretkey, thời hạn 30 ngày
def generate_jwt_token(uid, secretkey):
    payload = {
        'uid': uid,
        'exp': Datetime.now() + timedelta(days=30),
        'app': 'student_service_maiatech',
    }
    token = jwt.encode(payload, secretkey, algorithm='HS256')
    return token

# Giải mã JWT token, trả về payload nếu hợp lệ, hoặc trả về lỗi nếu không hợp lệ
def decode_jwt_token(token, secretkey):
    try:
        payload = jwt.decode(token, secretkey, algorithms=['HS256'])
        return payload
    except jwt.ExpiredSignatureError:
        return {'error': 'Token expired'}
    except jwt.InvalidTokenError:
        return {'error': 'Invalid token'}

# Kiểm tra JWT token từ request, trả về True nếu hợp lệ, hoặc trả về Response lỗi nếu không hợp lệ
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

# Lấy Firebase app - Thread Safe Version with Lock
def get_firebase_app():
    """
    Thread-safe Firebase app initialization with lock
    Prevents race conditions when multiple threads initialize simultaneously
    """
    try:
        # Use lock to prevent race conditions during initialization
        with _firebase_lock:
            # Double-check pattern: check again inside lock
            if _apps:
                return list(_apps.values())[0]
            
            # Initialize new app if none exists
            json_path = os.path.join(SECURITY_DIR, FIREBASE_SDK_JSON)
            if not os.path.exists(json_path):
                raise FileNotFoundError(f"Firebase config file not found: {json_path}")
                
            cred = credentials.Certificate(json_path)
            app = initialize_app(cred)
            print(f"Firebase app initialized successfully: {app.name}")
            return app
            
    except Exception as e:
        error_msg = f"Error initializing Firebase app: {str(e)}"
        print(error_msg)
        raise Exception(error_msg)


# Gửi FCM object Notify đến người dùng - Improved Thread Safety
def send_fcm_notify(env, notify, data):
    """
    Send FCM notification with improved error handling and thread safety
    """
    try:
        firebase_app = get_firebase_app()
    except Exception as e:
        print(f"Failed to get Firebase app: {str(e)}")
        notify.fcm_responses = f"Firebase initialization error: {str(e)}"
        return notify

    notify.fcm_success_count = 0
    notify.fcm_failure_count = 0
    notify.fcm_responses = ''

    # Send to specific users
    if notify.user_ids:
        try:
            profiles = env['student.user.profile'].sudo().search([('user_id', 'in', notify.user_ids.ids)])
            tokens = [p.fcm_token for p in profiles if p.fcm_token]
            
            if tokens:
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
            else:
                notify.fcm_responses += "No valid FCM tokens found for users. "
                
        except Exception as e:
            error_msg = f"Error sending to users: {str(e)}"
            notify.fcm_responses += error_msg
            print(error_msg)

    # Send to dormitory clusters  
    if notify.dormitory_cluster_ids:
        try:
            cluster_names = notify.dormitory_cluster_ids.mapped('name')
            if cluster_names:
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
                # Note: topic messages don't return success/failure counts
                notify.fcm_responses += f"Sent to topics: {cluster_names}. "
            else:
                notify.fcm_responses += "No valid cluster names found. "
                
        except Exception as e:
            error_msg = f"Error sending to topics: {str(e)}"
            notify.fcm_responses += error_msg
            print(error_msg)

    return notify

# Gửi FCM đến danh sách users - Improved with better error handling
def send_fcm_users(env, user_ids, title, body, data):
    """
    Send FCM to specific users with improved error handling
    """
    try:
        firebase_app = get_firebase_app()
    except Exception as e:
        print(f"Failed to get Firebase app in send_fcm_users: {str(e)}")
        # Still create notify record for tracking
        return env['student.notify'].sudo().create({
            'notify_type': 'users',
            'title': title,
            'body': body,
            'data': data,
            'user_ids': user_ids,
            'fcm_success_count': 0,
            'fcm_failure_count': len(user_ids),
            'fcm_responses': f'Firebase initialization error: {str(e)}',
        })

    # Get FCM tokens from both admin and user profiles
    tokens = []
    try:
        admins_profiles = env['student.admin.profile'].sudo().search([('user_id', 'in', user_ids)])
        users_profiles = env['student.user.profile'].sudo().search([('user_id', 'in', user_ids)])
        tokens += [p.fcm_token for p in admins_profiles if p.fcm_token]
        tokens += [p.fcm_token for p in users_profiles if p.fcm_token]
    except Exception as e:
        print(f"Error getting FCM tokens: {str(e)}")

    # Create notify record first
    notify = env['student.notify'].sudo().create({
        'notify_type': 'users',
        'title': title,
        'body': body,
        'data': data,
        'user_ids': [(6, 0, user_ids)],
        'fcm_success_count': 0,
        'fcm_failure_count': 0,
        'fcm_responses': '',
    })

    # Send FCM if we have tokens
    if tokens:
        try:
            message = messaging.MulticastMessage(
                notification=messaging.Notification(title=title, body=body),
                tokens=tokens,
                data=data if data else None,
            )
            
            response = messaging.send_each_for_multicast(message, app=firebase_app)
            notify.sudo().write({
                'fcm_success_count': response.success_count,
                'fcm_failure_count': response.failure_count,
                'fcm_responses': f'Sent to {len(tokens)} tokens',
            })
        except Exception as e:
            error_msg = f"Error sending FCM: {str(e)}"
            notify.sudo().write({
                'fcm_failure_count': len(tokens),
                'fcm_responses': error_msg,
            })
            print(f"Error in send_fcm_users: {error_msg}")
    else:
        notify.sudo().write({
            'fcm_responses': 'No FCM tokens found for target users',
        })

    return notify

# Batch send FCM để tránh overload - New function
def send_fcm_batch(env, tokens, title, body, data=None, batch_size=500):
    """
    Send FCM in batches to prevent overloading Firebase servers
    Firebase recommends max 500 tokens per multicast message
    """
    total_success = 0
    total_failure = 0
    responses = []
    
    try:
        firebase_app = get_firebase_app()
    except Exception as e:
        return {
            'success': False,
            'message': f'Firebase initialization error: {str(e)}',
            'total_success': 0,
            'total_failure': len(tokens),
            'responses': []
        }
    
    # Split tokens into batches
    for i in range(0, len(tokens), batch_size):
        batch_tokens = tokens[i:i + batch_size]
        
        try:
            message = messaging.MulticastMessage(
                notification=messaging.Notification(title=title, body=body),
                tokens=batch_tokens,
                data=data if data else None,
            )
            
            response = messaging.send_each_for_multicast(message, app=firebase_app)
            total_success += response.success_count
            total_failure += response.failure_count
            
            responses.append({
                'batch': i // batch_size + 1,
                'tokens_count': len(batch_tokens),
                'success_count': response.success_count,
                'failure_count': response.failure_count
            })
            
        except Exception as e:
            total_failure += len(batch_tokens)
            responses.append({
                'batch': i // batch_size + 1,
                'tokens_count': len(batch_tokens),
                'success_count': 0,
                'failure_count': len(batch_tokens),
                'error': str(e)
            })
            print(f"Error sending batch {i // batch_size + 1}: {str(e)}")
    
    return {
        'success': total_success > 0,
        'message': f'Sent to {total_success} devices, {total_failure} failed',
        'total_success': total_success,
        'total_failure': total_failure,
        'responses': responses
    }

# Gửi FCM với đầu vào là Request object, data sẽ là {'type': 'request', 'id': f'{request.id}'}
# send_type = 0: tạo mới, 1: cập nhật, 2: đang duyệt qua bước, 3: đã duyệt hoàn thành, 4: Đánh giá, 5: Khiếu nại  
def send_fcm_request(env, request_obj, send_type=0):
    """
    Gửi thông báo FCM khi Yêu cầu dịch vụ có thay đổi (Sinh viên, Người được giao, Các đối tượng liên quan)
        :param env: Odoo environment
        :param request_obj: Đối tượng yêu cầu dịch vụ
        :param send_type: Loại thông báo (
            0: Yêu cầu đã tạo mới,
            1: Yêu cầu đã cập nhật,
            2: Yêu cầu đang duyệt qua bước,
            3: Yêu cầu đã duyệt hoàn thành,
            4: Yêu cầu có đánh giá,
            5: Yêu cầu có khiếu nại,
            6: SV gửi nghiệm thu,
            7: Yêu cầu được gia hạn,
            8: Yêu cầu đã hủy,
            9: Yêu cầu cần duyệt lại,
           10: Đã hoàn thành và đóng yêu cầu,
           11: Quản lý gửi nghiệm thu,
           12: Yêu cầu cần được sửa lại,
           13: Yêu cầu sắp hết hạn 
        )
    """
    data = {'type': 'request', 'id': str(request_obj.id)}
    title = ""
    body = ""
    action = ""
    try:
        if send_type == 0: # Mới tạo yêu cầu
            action = 'Tạo mới'
            send_fcm_users(env, [request_obj.request_user_id.id], f'Yêu cầu dịch vụ {request_obj.service_id.name} đã được tạo thành công', f'Yêu cầu của bạn đã được tạo thành công. Nội dung {request_obj.note}', data)
            # Tạo nội dung gửi Admin
            title = f"Có yêu cầu dịch vụ {request_obj.service_id.name} từ {request_obj.request_user_id.name}" if request_obj.service_id else f"Yêu cầu dịch vụ {action} từ {request_obj.request_user_id.name}"
            body = f"Bạn có một yêu cầu {action}: " + (request_obj.note + "Hay kiểm tra chi tiết trong ứng dụng.")

        elif send_type == 1: # Sửa yêu cầu
            action = 'Cập nhật'
            send_fcm_users(env, [request_obj.request_user_id.id], f'Yêu cầu dịch vụ {request_obj.service_id.name} đã được {action}', f'Yêu cầu của bạn đã được {action}. {request_obj.note}', data)
            #Nội dung thông báo cho người duyệt
            title = f"Cập nhật yêu cầu dịch vụ {request_obj.service_id.name} từ {request_obj.request_user_id.name}"
            body = "Bạn có một yêu cầu đã chỉnh sửa: " + (request_obj.note + "Hay kiểm tra chi tiết trong ứng dụng.")

        elif send_type == 2:
            action = 'Có cập nhật'
            send_fcm_users(env, [request_obj.request_user_id.id], f'Yêu cầu dịch vụ {request_obj.service_id.name} đã được cập nhật', f'Yêu cầu của bạn đã được cập nhật: {request_obj.note}', data)
            #Nội dung thông báo cho người duyệt
            title = f"Duyệt yêu cầu dịch vụ {request_obj.service_id.name} từ {request_obj.request_user_id.name}"
            body = "Yêu cầu đã được cập nhật: " + (request_obj.note + "Hay kiểm tra chi tiết trong ứng dụng.")

        elif send_type == 3:
            action = 'Duyệt hoàn thành'
            send_fcm_users(env, [request_obj.request_user_id.id], f'Yêu cầu dịch vụ {request_obj.service_id.name} đã được hoàn thành cần nghiệm thu', f'Yêu cầu của bạn đã được hoàn thành. {request_obj.note}. Bạn hãy kiểm tra chi tiết và nghiệm thu trong ứng dụng.', data)
            #Nội dung thông báo cho người duyệt
            title = f"Hoàn thành yêu cầu dịch vụ {request_obj.service_id.name} từ {request_obj.request_user_id.name}"
            body = f"Yêu cầu của {request_obj.name} đã được hoàn thành: {request_obj.note}. Hay kiểm tra chi tiết và nghiệm thu trong ứng dụng."

        elif send_type == 4: # Đánh giá
            action = 'Đánh giá'
            send_fcm_users(env, [request_obj.request_user_id.id], f'Bạn đã gửi đánh giá {request_obj.service_id.name} ', f'Đánh giá cho yêu cầu {request_obj.service_id.name} của bạn đã được gửi.', data)
            #Nội dung thông báo cho người duyệt
            title = f"Đánh giá yêu cầu dịch vụ {request_obj.service_id.name} từ {request_obj.request_user_id.name}"
            body = "Sinh viên gửi đánh giá: " + (request_obj.note + "Hay kiểm tra chi tiết trong ứng dụng.")

        elif send_type == 5:
            action = 'Khiếu nại'
            send_fcm_users(env, [request_obj.request_user_id.id], f'Đã gửi khiếu nại dịch vụ {request_obj.service_id.name}', f'Bạn đã gửi khiếu nại yêu cầu dịch vụ {request_obj.service_id.name}. {request_obj.note}', data)
            #Nội dung thông báo cho người duyệt
            title = f"Khiếu nại yêu cầu dịch vụ {request_obj.service_id.name} từ {request_obj.request_user_id.name}"
            body = "Bạn có một yêu cầu đã được khiếu nại: " + (request_obj.note + "Hay kiểm tra chi tiết trong ứng dụng.")

        elif send_type == 6: # Gửi nghiệm thu
            action = 'Gửi nghiệm thu'
            send_fcm_users(env, [request_obj.request_user_id.id], f'Bạn đã gửi nghiệm thu yêu cầu dịch vụ {request_obj.service_id.name}', f'Gửi nghiệm thu yêu cầu dịch vụ {request_obj.service_id.name}. {request_obj.note} thành công', data)
            title = f"Người yêu cầu đã gửi Nghiệm thu: {request_obj.service_id.name} từ {request_obj.request_user_id.name}"
            body = "Bạn có một yêu cầu đã được Sinh viên nghiệm thu: " + (request_obj.note + "Hay kiểm tra chi tiết trong ứng dụng.")

        elif send_type == 7: 
            action = 'Gia hạn'
            send_fcm_users(env, [request_obj.request_user_id.id], f'Yêu cầu dịch vụ {request_obj.service_id.name} đã được gia hạn', f'Yêu cầu dịch vụ {request_obj.service_id.name}. {request_obj.note} đã gia hạn', data)
            title = f'Gia hạn yêu cầu dịch vụ {request_obj.service_id.name}'
            body = f'Thông báo yêu cầu dịch vụ {request_obj.service_id.name}. {request_obj.note} đã gia hạn'

        elif send_type == 8: 
            action = 'Hủy yêu cầu'
            send_fcm_users(env, [request_obj.request_user_id.id], f'Yêu cầu dịch vụ {request_obj.service_id.name} của bạn đã hủy', f'Yêu cầu dịch vụ {request_obj.service_id.name}. {request_obj.note} đã hủy', data)
            title = f'Yêu cầu dịch vụ {request_obj.service_id.name} đã bị hủy'
            body = f'Yêu cầu dịch vụ {request_obj.service_id.name}. {request_obj.note} đã bị hủy: {request_obj.final_data}'

        elif send_type == 9:
            action = 'Yêu cầu làm lại'
            send_fcm_users(env, [request_obj.request_user_id.id], f'Yêu cầu dịch vụ {request_obj.service_id.name} của bạn đang xử lý sửa lại', f'Sửa lại yêu cầu dịch vụ {request_obj.service_id.name}. {request_obj.note}: {request_obj.final_data}', data)
            title = f'Sửa lại yêu cầu dịch vụ {request_obj.name}'
            body = f'Sửa lại yêu cầu dịch vụ {request_obj.name}. {request_obj.note} do không được nghiệm thu'

        elif send_type == 10:
            action = 'Đóng yêu cầu'
            send_fcm_users(env, [request_obj.request_user_id.id], f'Yêu cầu dịch vụ {request_obj.service_id.name} đã nghiệm thu hoàn thành', f'Yêu cầu của Bạn: {request_obj.service_id.name}. {request_obj.note} đã được nghiệm thu và đóng lại', data)
            title = f'Đã hoàn thành và Đóng yêu cầu dịch vụ {request_obj.service_id.name}'
            body = f'Yêu cầu dịch vụ {request_obj.service_id.name}. {request_obj.note} đã xử lý xong và đóng lại!'
        
        elif send_type == 11: # Gửi nghiệm thu
            action = 'Người duyệt nghiệm thu'
            send_fcm_users(env, [request_obj.request_user_id.id], f'Cán bộ quản lý đã nghiệm thu yêu cầu dịch vụ {request_obj.service_id.name} của bạn', f'Đã nghiệm thu yêu cầu dịch vụ {request_obj.service_id.name}. {request_obj.note} thành công', data)
            title = f"{action}: {request_obj.service_id.name} từ {request_obj.request_user_id.name}"
            body = f"Yêu cầu {request_obj.name} đã được duyệt nghiệm thu: " + (request_obj.note + "Hay kiểm tra chi tiết trong ứng dụng.")

        elif send_type == 13: # Gửi thông báo yêu cầu sắp hết hạn
            action = 'Thông báo yêu cầu sắp hết hạn'
            send_fcm_users(env, [request_obj.user_processing_id.id], f'Yêu cầu dịch vụ {request_obj.service_id.name} của bạn sắp hết hạn', f'Yêu cầu dịch vụ {request_obj.service_id.name}. {request_obj.note} sắp hết hạn, cần bạn xử lý gấp hoặc gia hạn yêu cầu này', data)
            title = f"{action}: {request_obj.service_id.name} từ {request_obj.request_user_id.name}"
            body = f"Yêu cầu {request_obj.name} sắp hết hạn xử lý: " + (request_obj.note + "Hay kiểm tra chi tiết trong ứng dụng.")

        # Gửi tới các user được gán xử lý yêu cầu này
        other_user_ids = [u.id for u in request_obj.users if u.id != request_obj.user_processing_id.id] if request_obj.users else []
        if request_obj.user_processing_id and send_type != 13:
            send_fcm_users(env, [request_obj.user_processing_id.id], f'Có cập nhật yêu cầu bạn được giao: {action} - {request_obj.name}', f'Yêu cầu {request_obj.name} được {action} nội dung: {request_obj.note}, cần bạn xử lý tiếp yêu cầu này', data)
        if other_user_ids:
            send_fcm_users(env, other_user_ids, title, body, data)
    except Exception as e:
        pass
    return None

# Thêm người dùng vào topic Firebase - Fixed static app issue
def add_user_to_firebase_topic(env, user_id, topic_area, topic_cluster):
    """
    Add user to Firebase topics with improved error handling
    """
    profile = env['student.user.profile'].sudo().search([('user_id', '=', user_id)], limit=1)
    if not profile or not profile.fcm_token:
        return {'success': False, 'message': 'User FCM token not found'}
    
    try:
        firebase_app = get_firebase_app()
        
        # Subscribe to both topics
        response_area = messaging.subscribe_to_topic([profile.fcm_token], topic_area, app=firebase_app)
        response_cluster = messaging.subscribe_to_topic([profile.fcm_token], topic_cluster, app=firebase_app)
        
        return {
            'success': True,
            'message': f'User subscribed to topics {topic_area} and {topic_cluster}',
            'responses': {
                'area': response_area.__dict__ if hasattr(response_area, '__dict__') else str(response_area),
                'cluster': response_cluster.__dict__ if hasattr(response_cluster, '__dict__') else str(response_cluster)
            }
        }
    except Exception as e:
        return {'success': False, 'message': f'Error subscribing to topics: {str(e)}'}

# Gỡ người dùng khỏi tất cả các topic Firebase - Fixed static app issue  
def remove_user_from_all_firebase_topics(env, user_id):
    """
    Remove user from all Firebase topics with improved error handling
    """
    profile = env['student.user.profile'].sudo().search([('user_id', '=', user_id)], limit=1)
    if not profile or not profile.fcm_token:
        return {'success': False, 'message': 'User FCM token not found'}
    
    try:
        firebase_app = get_firebase_app()
        
        # Get all topics user might be subscribed to
        topics = []
        if profile.dormitory_area_id:
            topics.append(str(profile.dormitory_area_id.id))
        if profile.dormitory_cluster_id:
            topics.append(str(profile.dormitory_cluster_id.id))
            
        # Unsubscribe from all topics
        responses = {}
        for topic in topics:
            try:
                response = messaging.unsubscribe_from_topic([profile.fcm_token], topic, app=firebase_app)
                responses[topic] = response.__dict__ if hasattr(response, '__dict__') else str(response)
            except Exception as topic_error:
                responses[topic] = f'Error: {str(topic_error)}'
                
        return {
            'success': True,
            'message': f'User unsubscribed from topics: {topics}',
            'responses': responses
        }
    except Exception as e:
        return {'success': False, 'message': f'Error unsubscribing from topics: {str(e)}'}
        

def format_datetime_local(dt, user_id=None):
    """
    Chuyển đổi datetime từ UTC sang timezone local của user
    """
    if not dt:
        return ''
    
    # Lấy timezone của user, mặc định là UTC+7 (Asia/Ho_Chi_Minh)
    user_tz = 'Asia/Ho_Chi_Minh'
    if user_id:
        user = request.env['res.users'].sudo().browse(user_id)
        if user and user.exists() and user.tz:
            user_tz = user.tz

    # Chuyển đổi từ UTC sang timezone local
    utc_dt = pytz.UTC.localize(dt.replace(tzinfo=None))
    local_tz = pytz.timezone(user_tz)
    local_dt = utc_dt.astimezone(local_tz)
    
    return local_dt.strftime('%Y-%m-%d %H:%M:%S')