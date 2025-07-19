from odoo import http
from odoo.http import request, Response
from odoo.fields import Datetime
import requests as py_requests

import json
import base64

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


