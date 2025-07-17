from odoo import http
from odoo.http import request, Response
import json

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

    @http.route('/api/service/request/create', type='json', auth='public', methods=['POST'], csrf=False)
    def create_service_request(self, **post):
        vals = {
            'service_id': post.get('service_id'),
            'request_user_id': post.get('request_user_id'),
            'note': post.get('note', ''),
            'file_ids': [(6, 0, post.get('file_ids', []))],
        }
        req = request.env['student.service.request'].sudo().create(vals)

        

        return {
            'id': req.id,
            'service_id': req.service_id.id,
            'request_user_id': req.request_user_id.id,
            'note': req.note,
            'file_ids': [f.id for f in req.file_ids],
            'request_date': req.request_date,
        }

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


