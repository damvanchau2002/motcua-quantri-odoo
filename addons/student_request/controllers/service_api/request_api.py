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
from .utils import send_fcm_request, send_fcm_users, send_fcm_notify


def create_request(env, serviceid, requestid, userid, note, attachments):
    service = env['student.service'].browse(int(serviceid))
    user_name = 'Yêu cầu dịch vụ: '
    user = env['res.users'].sudo().browse(int(userid))
    if not user: return False
    vals = {}
    requestid = int(requestid)
    if requestid > 0:
        # Tạo yêu cầu trên Web thì form đã new object requestid rồi (lúc đó len(vals.step_ids) > 0).  
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
                # Nếu chỉnh sửa yêu cầu trên API sẽ chạy qua đây:
                send_fcm_request(env, vals, 1)
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
    role_users = []
    if service.role_ids:
        vals['role_ids'] = [(6, 0, service.role_ids.ids)]
        # Lấy các user có role trong role_ids rồi add vào users
        # Lấy tất cả các user có role_ids nằm trong service.role_ids từ student.admin.profile
        admin_profiles = request.env['student.admin.profile'].sudo().search([('role_ids', 'in', service.role_ids.ids)])
        role_users = [ap.user_id.id for ap in admin_profiles if ap.user_id]
    if service.users:
        # Thêm các user trong service.users vào role_users
        # Thêm các user_id từ danh sách service.users vào mảng role_users (tránh trùng lặp)
        role_users = list(set(role_users) | set(service.users.ids))
        #role_users = request.env['res.users'].browse(role_users)
    vals['users'] = [(6, 0, role_users)] if role_users else []
    if requestid == 0:
        vals = env['student.service.request'].sudo().create(vals)
    send_fcm_request(env, vals)    
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
    
    next_step_users = [nextuserid]
    #Nếu chưa phải bước cuối cùng và duyệt đã hoàn thành
    if step.base_secquence != 99 and act == 'approved':
        #Tìm bước tiếp theo trong request.step_ids theo sequence
        next_step = request.step_ids.filtered(lambda s: s.base_secquence > step.base_secquence).sorted('base_secquence')
        if next_step:
            #Gán trạng thái cho bước tiếp theo là 'assigned' và gán user xử lý tiếp theo nếu có
            next_step = next_step[0]
            #Lấy users trong base_step_id của bước tiếp theo
            next_step_users = list(set(next_step_users) | set(next_step.base_step_id.user_ids.ids))
            #quét các user trong base_step.role_ids để lấy user_id
            admin_profiles = env['student.admin.profile'].sudo().search([('role_ids', 'in', next_step.base_step_id.role_ids.ids)])
            next_step_users = list(set(next_step_users) | set([ap.user_id.id for ap in admin_profiles if ap.user_id]))

            next_step.sudo().write({
                'state': 'pending',
                'assign_user_id': [(6, 0, [nextuserid])] if nextuserid else [],
                'approve_date': Datetime.now(),
                'approve_content': f'Đang chờ duyệt bước {next_step.base_step_id.name}',
            })
            note = f'Đã duyệt bước {step.base_step_id.name}, đang chờ duyệt bước {next_step.base_step_id.name}'
        

    #Update database: request các field: approve_content approve_date final_state final_data
    request.sudo().write({
        'users': [(4, uid) for uid in next_step_users],
        'approve_content': note,
        'approve_date': Datetime.now(),
        'approve_user_id': nextuserid if nextuserid else False,
        'final_state': act,
        'final_data': final_data if step.base_step_id.sequence == 99 else '',
    })

    if step.base_secquence == 99 and act == 'approved':
        send_fcm_request(env, request, 3)
    else:
        send_fcm_request(env, request, 2)

    return vals

# Controller cho API dịch vụ
class ServiceApiController(http.Controller):
    # Lấy danh sách các nhóm dịch vụ và các dịch vụ trong nhóm
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
        request_id = params.get('request_id')
        step_id = params.get('step_id') 
        user_id = params.get('user_id')          # User thực hiện duyệt
        note = params.get('note', '')            # Nội dung duyệt
        act = params.get('act', '')              # action: 'pending', 'assigned', 'ignored', 'approved', 'rejected'
        next_user_id = params.get('next_user_id')  # User tiếp theo xử lý yêu cầu
        docs = params.get('docs')                # Danh sách file đính kèm nếu bước = 1
        final_data = params.get('final_data')    # Nếu duyệt bước 99 cuối

        if not step_id:
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
            step_data = update_request_step(request.env, request_id, step_id, user_id, note, act, next_user_id, docs, final_data)
            request.env['student.service.request.step'].sudo().write(step_data)

            return Response(
                json.dumps({'success': True, 'message': 'Bước duyệt thành công', 'data': step_data}),
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
        