from odoo import http, models, fields
from odoo.http import request, Response
from odoo.fields import Datetime
import requests as py_requests

import json
import base64

from datetime import datetime
def convert_date(date_str):
    if not date_str:
        return False
    try:
        # Nếu đúng định dạng dd/MM/yyyy thì chuyển sang yyyy-MM-dd
        return datetime.strptime(date_str, '%d/%m/%Y').strftime('%Y-%m-%d')
    except Exception:
        return date_str  # Nếu đã đúng định dạng thì giữ nguyên
        
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
            json.dumps(result),
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
            json.dumps(data),
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
            'state': service.state,
            'group_id': service.group_id.id if service.group_id else None,
            'group_name': service.group_id.name if service.group_id else '',
            # Add more fields if needed
            'step_ids': [{'id': step.id, 'name': step.name, 'description': step.description} for step in service.step_ids],
            'users': [{'id': user.id, 'name': user.name} for user in service.users],
            'files': [{'id': f.id, 'name': f.name, 'description': f.description } for f in service.files],
        }
        return Response(
            json.dumps(data),
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
                    'gender': gender,
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

            return Response(
                json.dumps({
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
                    json.dumps({'error': 'External login unsuccessful', 'detail': external_data}),
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
                json.dumps({'error': 'External login exception', 'detail': str(e)}),
                content_type='application/json',
                status=500,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )


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

        vals = {
            'service_id': service_id,
            'request_user_id': request_user_id,
            'note': note,
            'image_attachment_ids': [(6, 0, attachment_ids)],
            'request_date': Datetime.now(),
        }
        req = request.env['student.service.request'].sudo().create(vals)

        # Cập nhật res_id cho attachment
        request.env['ir.attachment'].sudo().browse(attachment_ids).write({'res_id': req.id})

        return Response(
            json.dumps({
                'id': req.id,
                'service_id': req.service_id.id,
                'request_user_id': req.request_user_id.id,
                'note': req.note,
                'image_attachment_ids': attachment_ids,
                'file_ids': [f.id for f in req.file_ids],
                'request_date': Datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
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
        data = []
        for req in requests:
            histories = []
            for h in req.step_history_ids:
                histories.append({
                    'id': h.id,
                    'step_id': h.step_id.id if h.step_id else None,
                    'step_name': h.step_id.name if h.step_id else '',
                    'user_id': h.user_id.id if h.user_id else None,
                    'user_name': h.user_id.name if h.user_id else '',
                    'state': h.state,
                    'approve_content': h.approve_content,
                    'approve_date': h.approve_date.strftime('%Y-%m-%d %H:%M:%S') if h.approve_date else '',
                })
            data.append({
                'id': req.id,
                'service_id': req.service_id.id,
                'service_name': req.service_id.name,
                'request_user_id': req.request_user_id.id,
                'request_user_name': req.request_user_id.name,
                'note': req.note,
                'file_ids': [f.id for f in req.file_ids],
                'image_attachment_ids': [a.id for a in req.image_attachment_ids],
                'request_date': req.request_date.strftime('%Y-%m-%d %H:%M:%S') if req.request_date else '',
                'final_state': req.final_state,
                'step_history': histories,
            })
        return Response(
            json.dumps(data),
            content_type='application/json',
            status=200,
            headers=[
                ('Access-Control-Allow-Origin', '*'),
                ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
            ]
        )

    @http.route('/api/service/request/list', type='json', auth='public', methods=['GET'], csrf=False)
    def list_service_requests(self, **post):
        domain = []
        if post.get('service_id'):
            domain.append(('service_id', '=', post['service_id']))
        if post.get('request_user_id'):
            domain.append(('request_user_id', '=', post['request_user_id']))
        # Lọc theo user đang đăng nhập có trong service.users
        user = request.env.user
        service_ids = request.env['student.service'].sudo().search([
            ('users', 'in', user.id)
        ]).ids
        if service_ids:
            domain.append(('service_id', 'in', service_ids))
        else:
            # Nếu user không có quyền duyệt dịch vụ nào thì trả về rỗng
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
        data = []
        for req in requests:
            data.append({
                'id': req.id,
                'service_id': req.service_id.id,
                'service_name': req.service_id.name,
                'request_user_id': req.request_user_id.id,
                'request_user_name': req.request_user_id.name,
                'note': req.note,
                'file_ids': [f.id for f in req.file_ids],
                'request_date': req.request_date,
                'final_state': req.final_state,
            })

        return Response(
            json.dumps(data),
            content_type='application/json',
            status=200,
            headers=[
                ('Access-Control-Allow-Origin', '*'),
                ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
            ]
        )


