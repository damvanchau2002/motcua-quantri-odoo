from odoo import http
from odoo.http import request, Response
from odoo.fields import Datetime
import json
import base64

class ServiceApiController(http.Controller):
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

    @http.route('/api/service/request/list', type='json', auth='public', methods=['GET'], csrf=False)
    def list_service_requests(self, **post):
        domain = []
        if post.get('service_id'):
            domain.append(('service_id', '=', post['service_id']))
        if post.get('request_user_id'):
            domain.append(('request_user_id', '=', post['request_user_id']))
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


