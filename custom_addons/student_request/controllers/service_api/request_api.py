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
from .utils import send_fcm_request, send_fcm_users, send_fcm_notify, format_datetime_local


def get_user_received_requests(env, cluster_id, service, step):
    """ Lấy danh sách các Users sẽ nhận được yêu cầu
        :param env: Odoo environment
        :param cluster_id: ID của cụm KTX (dùng để lọc user)
        :param service: Dịch vụ cần lấy yêu cầu
        :param step: Bước xử lý của dịch vụ
        :return: Danh sách các user sẽ nhận được yêu cầu này """
    received_users = []
    if service.users: # Nếu dịch vụ có gán user thì lấy luôn
        received_users += service.users.ids
    # try:
    #     if step.assign_user_id: # Nếu bước có gán user thì lấy luôn
    #         received_users += [step.assign_user_id.id]
    # except Exception as e:
    #     pass # Nếu không có assign_user_id thì bỏ qua

    #if step.base_step_id.user_ids: # Nếu bước có gán user_ids thì lấy luôn
    #    received_users += step.base_step_id.user_ids.ids

    # Lấy các user trong cụm KTX
    if cluster_id > 0:
        domain = [('dormitory_clusters', 'in', [cluster_id]), ('role_ids', 'in', service.role_ids.ids)]
        dormitory_admins = env['student.admin.profile'].sudo().search(domain)

        if dormitory_admins:  # Nếu có quản lý KTX thì lấy user_id của họ
            received_users += dormitory_admins.mapped('user_id.id')

    return received_users


def create_request(env, serviceid, requestid, userid, note, attachments):
    """
    Tạo hoặc cập nhật yêu cầu dịch vụ
            :param env: Odoo environment
            :param serviceid: ID của dịch vụ
            :param requestid: ID của yêu cầu (nếu có)
            :param userid: ID của người dùng yêu cầu
            :param note: Ghi chú của yêu cầu
            :param attachments: Danh sách ID của các file đính kèm
        :return: Record của yêu cầu dịch vụ đã tạo hoặc cập nhật
    """
    if not userid:
        raise ValueError("Thiếu user id")

    if not serviceid:
        raise ValueError("Thiếu service id")

    user = env['res.users'].sudo().browse(int(userid))
    if not user.exists():
        raise ValueError(f"User không tồn tại: {userid}")

    user_profile = env['student.user.profile'].sudo().search([('user_id', '=', user.id)], limit=1)
    if not user_profile.exists():
        raise ValueError(f"User profile không tồn tại: {userid}")

    # ID của cụm KTX
    cluster_id = user_profile.dormitory_cluster_id if user_profile.dormitory_cluster_id else 0

    service = env['student.service'].sudo().browse(int(serviceid))
    if not service.exists():
        raise ValueError(f"Service không tồn tại: {serviceid}")
    

    attachments = attachments or []
    vals = {}
    # Nếu có request_id => cập nhật (chô này nếu tạo trên Web sẽ luôn có request_id và không có step_ids)
    if requestid and str(requestid).isdigit() and int(requestid) > 0:
        vals = env['student.service.request'].sudo().browse(int(requestid))
        if vals.exists():
            vals.sudo().write({
                'name': f'{user.name}: {service.name}',
                'service_id': service.id,
                'request_user_id': user.id,
                'note': note,
                'image_attachment_ids': [(6, 0, attachments)],
                'request_date': Datetime.now(),
                'final_state': 'pending',
                'dormitory_cluster_id': cluster_id,  # Gán cụm KTX nếu có
            })
            if len(vals.step_ids.ids) > 0:
                # Sửa yêu cầu ok
                send_fcm_request(env, vals, 1)
                return vals
    else:
        # Tạo mới yêu cầu
        vals = {
            'name': f'{user.name}: {service.name}',
            'service_id': service.id,
            'request_user_id': user.id,
            'note': note,
            'image_attachment_ids': [(6, 0, attachments)],
            'request_date': Datetime.now(),
            'final_state': 'pending',
            'dormitory_cluster_id': cluster_id,  # Gán cụm KTX nếu có
        }

    # Tạo mới yêu cầu các bước xử lý
    received_users = [] # Danh sách user sẽ nhận yêu cầu
    step_ids = [] # Danh sách các bước duyệt
    for step in service.step_ids.sorted('sequence'):
        step_vals = {
            'request_id': False,
            'base_step_id': step.id,
            'state': 'pending',
        }
        step_request = env['student.service.request.step'].create(step_vals)
        if step == service.step_ids.sorted('sequence')[0] and service.files:
            # Nếu là bước đầu tiên thì gán file_ids từ service.files
            step_request.file_ids = [(6, 0, service.files.ids)]
            # Lấy user duyệt trong cấu hình step đầu tiên
            #if step.user_ids: step_request.user_ids = [(6, 0, step.user_ids.ids)]
            #received_users = get_user_received_requests(env, cluster_id, service, step_request)
            #if received_users: vals['users'] = [(6, 0, received_users)] # Gán user nhận yêu cầu

        step_ids.append(step_request.id)

    if step_ids:
        vals['step_ids'] = [(6, 0, step_ids)]

    # Gán role và người duyệt
    if service.role_ids:
        vals['role_ids'] = [(6, 0, service.role_ids.ids)]

    # Tìm user quản lý sinh viên (level=1) trong cụm KTX
    user_processing_id = 0
    qlsv_profiles = env['student.admin.profile'].sudo().search([
        ('role_ids', 'in', service.role_ids.ids),
        ('dormitory_clusters.qlsv_cluster_id', '=', cluster_id)
    ])
    if qlsv_profiles:
        user_processing_id = qlsv_profiles[0].user_id.id
        received_users += qlsv_profiles.mapped('user_id.id')

    if user_processing_id > 0:
        vals['user_processing_id'] = user_processing_id
        received_users.append(user_processing_id)

    if len(received_users) > 0:
        vals['users'] = [(6, 0, received_users)]
        
    try:
        if vals.id > 0:
            return vals
    
        raise ValueError("Thiếu ID yêu cầu")
    except Exception as e:
        vals = env['student.service.request'].sudo().create(vals)
        send_fcm_request(env, vals, 0)
        pass
    return vals


def update_request(env, requestid, userid, note=None, attachments=None, final_state='pending'):
    """
    Cập nhật yêu cầu dịch vụ đã có
        :param env: Odoo environment
        :param requestid: ID của yêu cầu cần cập nhật
        :param userid: ID của người cập nhật
        :param note: Ghi chú mới (tùy chọn)
        :param attachments: Danh sách ID file đính kèm (tùy chọn)
        :param final_state: Trạng thái cuối (tùy chọn, mặc định là 'pending')
        :return: Record yêu cầu dịch vụ đã cập nhật
    """
    if not requestid:
        raise ValueError("Thiếu request id")

    if not userid:
        raise ValueError("Thiếu user id")

    request = env['student.service.request'].sudo().browse(int(requestid))
    if not request.exists():
        raise ValueError(f"Yêu cầu không tồn tại: {requestid}")

    user = env['res.users'].sudo().browse(int(userid))
    if not user.exists():
        raise ValueError(f"User không tồn tại: {userid}")

    vals = {
        'request_user_id': user.id,
        'request_date': Datetime.now(),
    }

    if note is not None:
        vals['note'] = note

    if attachments:
        vals['image_attachment_ids'] = [(4, attach_id) for attach_id in attachments] # 4: Thêm file đính kèm, 6: Gán file mới


    # Cập nhật
    request.sudo().write(vals)

    # Gửi FCM thông báo cập nhật yêu cầu
    send_fcm_request(env, request, 1)

    return request


#Duyệt 1 bước (env, dịch vụ, bước, người duyệt, ghi chú, action duyệt, user được giao, file đính kèm, kết luận)
def update_request_step(env, requestid, stepid, userid, note, act, nextuserid, docs, final_data, department_id = 0):
    """
    Cập nhật bước yêu cầu dịch vụ (Update a service request step).
    Args:
        env (Environment): Đối tượng môi trường Odoo (Odoo environment object).
        requestid (int): ID của yêu cầu dịch vụ (ID of the service request).
        stepid (int): ID của bước hiện tại trong quy trình (ID of the current step in the process).
        userid (int): ID của người thực hiện hành động (ID of the user performing the action).
        note (str): Ghi chú hoặc nội dung phê duyệt (Approval note or comment).
        act (str): Hành động thực hiện trên bước ('pending', 'approved', 'rejected', ...) (Action to perform on the step).
        nextuserid (int): ID của người dùng tiếp theo sẽ xử lý (ID of the next user to process the step).
        docs (list): Danh sách tài liệu đính kèm (List of attached documents).
        final_data (str): Dữ liệu cuối cùng của yêu cầu (Final data of the request).
        department_id (int, optional): ID của phòng ban liên quan (ID of the related department). Mặc định là 0.
    Returns:
        dict or bool: Trả về dict chứa thông tin cập nhật nếu thành công, False nếu không tìm thấy bước (Returns a dict with updated information if successful, False if the step is not found).
    """
    request = env['student.service.request'].browse(requestid)
    step = request.step_ids.browse(stepid)
    # Lấy bước theo thứ tự sequence, lấy bước đầu tiên chưa ignored, approved hoặc rejected
    # step = service.step_ids.filtered(lambda s: s.state not in ('ignored', 'approved', 'rejected')).sorted('sequence')
    # step = step[0] if step else service.step_ids.browse(stepid)
    if not step.exists():
        return False
    # nếu act khác pending thì tìm các bước trước đó còn pending cập nhật nó thanh ignored
    if act != 'pending':
        prev_steps = request.step_ids.filtered(lambda s: s.base_secquence < step.base_secquence and (s.state == 'pending' or s.state == 'assigned' or s.state == 'rejected'))
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
                'assign_user_id': nextuserid if nextuserid else 0,
                'history_ids': [(4, h.id)],
            })
        next_steps = request.step_ids.filtered(lambda s: s.base_secquence > step.base_secquence and (s.state != 'pending'))
        for s in next_steps:
            s.state = 'pending'
            s.sudo().write({
                'state': 'pending',
                'approve_content': 'Chuyển lại trạng thái chờ duyệt do thay đổi trạng thái bước trước',
                'approve_date': Datetime.now(),
                'assign_user_id': nextuserid if nextuserid else 0,
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
        'assign_user_id': nextuserid if nextuserid else 0,
        'history_ids': [(4, hh.id)],
    }
    
    if step.base_secquence == 1:
        vals['file_ids'] = step.file_ids
        vals['file_checkbox_ids'] = step.file_checkbox_ids
    if step.base_secquence == 99:
        vals['final_data'] = final_data
    next_step_users = []
    department_user_id = 0
    # Chỗ này tìm người tiếp theo được phân công theo nextuserid hoặc department_id gán vào mảng next_step_users
    if nextuserid and nextuserid > 0:
        next_step_users.append(nextuserid)
    if department_id and department_id > 0:
        department_users = env['student.admin.profile'].search([('department_id', '=', department_id), ('role_ids.level', 'in', [9])])
        department_user_id = department_users and department_users[0].id or 0
        next_step_users.extend(department_users.ids)

    #Nếu chưa phải bước cuối cùng và duyệt đã hoàn thành
    if step.base_secquence != 99 and act == 'approved':
        #Tìm bước tiếp theo trong request.step_ids theo sequence
        next_step = request.step_ids.filtered(lambda s: s.base_secquence > step.base_secquence).sorted('base_secquence')
        if next_step:
            next_step = next_step[0]
            next_step.sudo().write({
                'state': 'assigned',
                'assign_user_id': nextuserid if nextuserid else 0,
                'approve_date': Datetime.now(),
                'approve_content': f'Đang chờ duyệt bước {next_step.base_step_id.name}',
            })
            note = f'Đã duyệt bước {step.base_step_id.name}, đang chờ duyệt bước {next_step.base_step_id.name}'
            act = 'pending'
            received_users = get_user_received_requests(env, request.dormitory_cluster_id.id, request.service_id, next_step)
            if received_users:
                next_step_users += received_users

    #Update database: request các field: approve_content approve_date final_state final_data
    request.sudo().write({
        'users': [(4, uid) for uid in next_step_users],
        'approve_content': note,
        'approve_date': Datetime.now(),
        'approve_user_id': userid,
        'is_new': False,
        'user_processing_id': nextuserid if nextuserid else department_user_id if department_user_id else None,
        'final_state': act,
        'final_data': final_data if step.base_step_id.sequence == 99 else '',
        'department_ids': [(4, department_id)] if department_id else [],
    })

    if step.base_secquence == 99 and act == 'approved':
        send_fcm_request(env, request, 3)
    else:
        send_fcm_request(env, request, 2)

    return vals

# Controller cho API dịch vụ
class ServiceApiController(http.Controller):

    # Tạo yêu cầu dịch vụ mới
    # Fromdata: { service_id, request_user_id, note, files: [file1, file2, ...] }
    @http.route('/api/service/request/create', type='http', auth='public', methods=['POST'], csrf=False)
    def create_service_request(self, **post):
        try:
            httprequest = request.httprequest
            files = httprequest.files.getlist('attachment')

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
                    'mimetype': file_storage.mimetype or 'application/octet-stream',
                })
                attachment_ids.append(attachment.id)

            # Lấy dữ liệu từ form
            form = httprequest.form
            service_id = form.get('service_id')
            request_id = form.get('request_id')
            request_user_id = form.get('request_user_id')
            note = form.get('note', '')

            # Gọi hàm tạo yêu cầu
            request_rec = create_request(request.env, service_id, request_id, request_user_id, note, attachment_ids)

            return Response(
                json.dumps({
                    'success': True,
                    'message': 'Tạo yêu cầu dịch vụ thành công',
                    'data': {
                        'id': request_rec.id,
                        'service_id': request_rec.service_id.id,
                        'service_name': request_rec.service_id.name,
                        'content': request_rec.note,
                        'request_date': format_datetime_local(request_rec.create_date, request_user_id)
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

        except Exception as e:
            return Response(
                json.dumps({
                    'success': False,
                    'message': 'Không thể tạo yêu cầu',
                    'detail': str(e)
                }),
                content_type='application/json',
                status=500,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )

        
    # Cập nhật yêu cầu dịch vụ
    # todo: cần kiểm tra trạng thái của yêu cầu trước khi cập nhật (chỉ cho cập nhật nếu là pending hoặc repairing )
    # Formdata: { request_id, request_user_id, note, files: [file1, file2, ...] }
    @http.route('/api/service/request/update', type='http', auth='public', methods=['POST'], csrf=False)
    def update_service_request(self, **post):
        try:
            httprequest = request.httprequest
            files = httprequest.files.getlist('attachment')

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
                    'mimetype': file_storage.mimetype or 'application/octet-stream',
                })
                attachment_ids.append(attachment.id)

            # Lấy dữ liệu từ form
            form = httprequest.form
            request_id = form.get('request_id')
            request_user_id = form.get('request_user_id')
            note = form.get('note', '')

            if not request_id:
                raise ValueError("Thiếu request_id")

            if not request_user_id:
                raise ValueError("Thiếu request_user_id")

            # Gọi hàm cập nhật yêu cầu
            request_rec = update_request(
                env=request.env,
                requestid=request_id,
                userid=request_user_id,
                note=note,
                attachments=attachment_ids
            )

            return Response(
                json.dumps({
                    'success': True,
                    'message': 'Cập nhật yêu cầu dịch vụ thành công',
                    'data': {
                        'id': request_rec.id,
                        'service_id': request_rec.service_id.id,
                        'service_name': request_rec.service_id.name,
                        'content': request_rec.note,
                        'request_date': format_datetime_local(request_rec.write_date or request_rec.create_date, request_user_id)
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

        except Exception as e:
            return Response(
                json.dumps({
                    'success': False,
                    'message': 'Không thể cập nhật yêu cầu',
                    'detail': str(e)
                }),
                content_type='application/json',
                status=500,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )


    # TODO Lấy các yêu cầu dịch vụ của 1 User có kèm lịch sử duyệt
    @http.route('/api/service/request/user', type='http', auth='public', methods=['GET'], csrf=False)
    def list_requests_by_user(self):
        try:
            # params = request.httprequest.get_json(force=True, silent=True) or {}
            params = request.params
            user_id = params.get('user_id')
            page = int(params.get('page', 1))
            limit = int(params.get('limit', 10))
            keyword = params.get('keyword', '').strip()

            if not user_id:
                raise ValueError("Thiếu user_id")

            domain = [('request_user_id', '=', int(user_id))]

            if keyword is not None and keyword != '':
                domain += ['|', ('name', 'ilike', keyword), ('note', 'ilike', keyword)]

            offset = (page - 1) * limit

            total = request.env['student.service.request'].sudo().search_count(domain)
            requests_data = request.env['student.service.request'].sudo().search(domain, offset=offset, limit=limit, order='request_date desc')
            result = []
            for req in requests_data:
                sumhistories_dict = {}
                for step in req.step_ids:
                    for h in step.history_ids:
                        step_id = step.id
                        history_data = {
                            'id': h.id,
                            'step_id': step_id,
                            'step_name': step.base_step_id.name if step.base_step_id else '',
                            'state': h.state,
                            'user_id': h.user_id.id if h.user_id else None,
                            'user_name': h.user_id.name if h.user_id else '',
                            'note': h.note,
                            'date': format_datetime_local(h.date, user_id),
                        }

                        if (
                            step_id not in sumhistories_dict
                            or h.date > sumhistories_dict[step_id]['_raw_date']
                        ):
                            history_data['_raw_date'] = h.date  
                            sumhistories_dict[step_id] = history_data

                # Bỏ _raw_date trước khi trả ra, và sort theo date mới nhất
                sumhistories = sorted(
                    [
                        {k: v for k, v in data.items() if k != '_raw_date'}
                        for data in sumhistories_dict.values()
                    ],
                    key=lambda x: x['date'],
                    reverse=True
                )


                result.append({
                    'id': req.id,
                    'service': {
                        'id': req.service_id.id,
                        'name': req.service_id.name,
                        'description': req.service_id.description,
                    } if req.service_id else {},
                    'name': req.name,
                    'note': req.note,
                    'request_date': format_datetime_local(req.request_date, user_id),
                    'approve_user_id': req.approve_user_id.id if req.approve_user_id else None,
                    'approve_user_name': req.approve_user_id.name if req.approve_user_id else '',
                    'approve_content': req.approve_content,
                    'approve_date': format_datetime_local(req.approve_date, user_id),
                    'final_state': req.final_state,
                    'finalfinal_data': req.final_data,
                    'histories': sorted(sumhistories, key=lambda x: x['date'], reverse=True),
                })

            return Response(
                json.dumps({
                    'success': True,
                    'message': 'Thành công',
                    'meta': {
                        'page': page,
                        'limit': limit,
                        'total': total,
                        'total_pages': (total + limit - 1) // limit
                    },
                    'data': result,
                    
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

            #domain.append('|')
            domain.append(('users', 'in', [user_id]))
            #domain.append(('role_ids', 'in', aprofile.role_ids.ids))

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
                    'request_date': format_datetime_local(req.create_date, user_id),
                    'approve_user_id': req.approve_user_id.id if req.approve_user_id else None,
                    'approve_user_name': req.approve_user_id.name if req.approve_user_id else '',
                    'approve_content': req.approve_content,
                    'approve_date': format_datetime_local(req.approve_date, user_id),
                    'final_state': req.final_state,
                    'finalfinal_data': True if req.final_data else False,  # Chuyển đổi rõ ràng

                    'service': {
                        'id': req.service_id.id,
                        'name': req.service_id.name,
                        'description': req.service_id.description,
                    } if req.service_id else {},

                    'steps': steps,
                    'is_new': req.is_new
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

     # Lấy danh sách các yêu cầu dịch vụ của user_id được giao
    @http.route('/api/service/request/myasigned', type='http', auth='public', methods=['GET'], csrf=False)
    def list_service_requests(self, **post):
        domain = []
        params = request.httprequest.get_json(force=True, silent=True) or {}
        try:
            user_id = int(params.get('user_id')) if params.get('user_id') else 0
            aprofile = request.env['student.admin.profile'].sudo().search([('user_id', '=', user_id)], limit=1) if user_id else None

            domain.append(('user_processing_id', '=', user_id))

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
                    'request_date': format_datetime_local(req.create_date, user_id),
                    'approve_user_id': req.approve_user_id.id if req.approve_user_id else None,
                    'approve_user_name': req.approve_user_id.name if req.approve_user_id else '',
                    'approve_content': req.approve_content,
                    'approve_date': format_datetime_local(req.approve_date, user_id),
                    'final_state': req.final_state,
                    'finalfinal_data': True if req.final_data else False,  # Chuyển đổi rõ ràng

                    'service': {
                        'id': req.service_id.id,
                        'name': req.service_id.name,
                        'description': req.service_id.description,
                    } if req.service_id else {},

                    'steps': steps,
                    'is_new': req.is_new
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
                    'date': format_datetime_local(h.date),
                })
        req_data = {
            'id': req.id,
            
            'service_id': req.service_id.id if req.service_id else None,
            'name': req.name,
            'note': req.note,
            
            'image_attachment_ids': [{'id': att.id, 'name': att.name, 'url': att.public_url if hasattr(att, 'public_url') else ''} for att in req.image_attachment_ids],
            'request_date': format_datetime_local(req.request_date),

            'request_user_id': req.request_user_id.id if req.request_user_id else None,
            'request_user_name': req.request_user_id.name if req.request_user_id else '',

            'step_ids': [{
                'id': step.id,
                'name': step.base_step_id.name if step.base_step_id else '',
                'state': step.state,
                'sequence': step.base_step_id.sequence if step.base_step_id else 0,
                'approve_content': step.approve_content,
                'approve_date': format_datetime_local(step.approve_date),
                'file_ids': [{'id': f.id, 'name': f.name, 'description': f.description} for f in step.file_ids],
                'file_checkbox_ids': [{'id': f.id, 'name': f.name, 'description': f.description} for f in step.file_checkbox_ids],
                'history_ids': [{
                    'id': h.id,
                    'state': h.state,
                    'user_id': h.user_id.id if h.user_id else None,
                    'user_name': h.user_id.name if h.user_id else '',
                    'note': h.note,
                    'date': format_datetime_local(h.date),
                } for h in step.history_ids],
            } for step in req.step_ids],
            'users': [{'id': u.id, 'name': u.name} for u in req.users],
            'role_ids': [{'id': r.id, 'name': r.name} for r in req.role_ids],

            'final_state': req.final_state,
            'final_data': req.final_data,
            'approve_content': req.approve_content,
            'approve_date': format_datetime_local(req.approve_date),
            'histories': sumhistories,
            'is_new': req.is_new
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

       # Lấy danh sách thông báo của user
    @http.route('/api/service/request/approve', type='http', auth='public', methods=['POST'], csrf=False)
    def approve_service_request(self, **post):
        params = request.httprequest.get_json(force=True, silent=True) or {}
        request_id = params.get('request_id')
        user_id = params.get('user_id')
        asign_user_id = params.get('asign_user_id', 0)
        department_id = params.get('department_id', 0)
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

        if asign_user_id == 0 and department_id == 0:
            return Response(
                json.dumps({'success': False, 'message': 'Phải có 1 trong 2 asign_user_id hoặc department_id'}),
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

        try:
            # Cập nhật bước duyệt
            vals = update_request_step(request.env, request_id, step_id, user_id, note, state, asign_user_id, checked_ids, final, department_id)
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


    # API: Lấy danh sách đánh giá cho yêu cầu dịch vụ
    @http.route('/api/service/request/review/list', type='http', auth='public', methods=['GET'], csrf=False)
    def list_service_request_reviews(self, **kwargs):
        try:
            params = request.httprequest.args or request.params
            request_id = params.get('request_id')
            
            domain = []
            if request_id:
                domain.append(('request_id', '=', int(request_id)))
            
            reviews = request.env['student.service.request.review'].sudo().search(domain)
            result = []
            for review in reviews:
                result.append({
                    'id': review.id,
                    'request_id': review.request_id.id if review.request_id else None,
                    'user_id': review.user_id.id if review.user_id else None,
                    'name': review.name if review.name else '',
                    'rating': review.rating,
                    'comments': review.comments,
                    'review_date': format_datetime_local(review.review_date, review.user_id.id)

                })
            return Response(
                json.dumps({'success': True, 'message': 'Thành công', 'data': result}),
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

    # API: Tạo đánh giá cho yêu cầu dịch vụ
    @http.route('/api/service/request/review/create', type='http', auth='public', methods=['POST'], csrf=False)
    def create_service_request_review(self, **post):
        try:
            params = request.httprequest.get_json(force=True, silent=True) or {}
            request_id = params.get('request_id')
            user_id = params.get('user_id')
            rating = params.get('rating')
            comments = params.get('comments', '')

            if not request_id or not user_id or rating is None:
                return Response(
                    json.dumps({'success': False, 'message': 'Thiếu request_id, user_id hoặc rating'}),
                    content_type='application/json',
                    status=400,
                    headers=[
                        ('Access-Control-Allow-Origin', '*'),
                        ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                        ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ]
                )

            # Kiểm tra đã đánh giá chưa (1 user chỉ được đánh giá 1 lần cho 1 request)
            existed = request.env['student.service.request.review'].sudo().search([
                ('request_id', '=', int(request_id)),
                ('user_id', '=', int(user_id))
            ], limit=1)
            if existed:
                return Response(
                    json.dumps({'success': False, 'message': 'Bạn đã đánh giá yêu cầu này rồi'}),
                    content_type='application/json',
                    status=409,
                    headers=[
                        ('Access-Control-Allow-Origin', '*'),
                        ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                        ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ]
                )

            review = request.env['student.service.request.review'].sudo().create({
                'request_id': int(request_id),
                'user_id': int(user_id),
                'rating': rating,
                'comments': comments,
            })
            try:
                send_fcm_request(
                    request.env,
                    review.request_id,
                    send_type=4 # Gửi thông báo đánh giá
                )
            except Exception as e:
                pass

            return Response(
                json.dumps({'success': True, 'message': 'Đánh giá thành công', 'data': {
                    'id': review.id,
                    'request_id': review.request_id.id,
                    'user_id': review.user_id.id,
                    'rating': review.rating,
                    'comments': review.comments,
                    'review_date': format_datetime_local(review.review_date, review.user_id.id)

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
                status=500,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )

    
    # API: Lấy danh sách khiếu nại cho yêu cầu dịch vụ
    @http.route('/api/service/request/complaint/list', type='http', auth='public', methods=['GET'], csrf=False)
    def list_service_request_complaints(self, **kwargs):
        try:
            params = request.httprequest.args or request.params
            request_id = params.get('request_id')
            user_id = params.get('user_id')
            domain = []
            if request_id:
                domain.append(('request_id', '=', int(request_id)))

            complaints = request.env['student.service.request.complaint'].sudo().search(domain)
            result = []
            for complaint in complaints:
                result.append({
                    'id': complaint.id,
                    'request_id': complaint.request_id.id if complaint.request_id else None,
                    'user_id': complaint.user_id.id if complaint.user_id else None,
                    'name': complaint.name if complaint.name else '',
                    'description': complaint.description if complaint.description else '',
                    'image_ids': [
                        {
                            'id': img.id,
                            'name': img.name,
                            'url': getattr(img, 'public_url', '') or ''
                        } for img in complaint.image_ids
                    ],
                    'complaint_date': format_datetime_local(complaint.complaint_date, complaint.user_id.id)

                })
     
            return Response(
                json.dumps({'success': True, 'message': 'Thành công', 'data': result}),
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

    # API: Tạo khiếu nại cho yêu cầu dịch vụ
    @http.route('/api/service/request/complaint/create', type='http', auth='public', methods=['POST'], csrf=False)
    def create_service_request_complaint(self, **post):
        try:
            httprequest = request.httprequest

            # Lấy dữ liệu từ form
            form = httprequest.form
            request_id = form.get('request_id')
            user_id = form.get('user_id')
            content = form.get('content', '')

            if not request_id or not user_id or not content:
                return Response(
                    json.dumps({'success': False, 'message': 'Thiếu request_id, user_id hoặc content'}),
                    content_type='application/json',
                    status=400,
                    headers=[
                        ('Access-Control-Allow-Origin', '*'),
                        ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                        ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ]
                )

            complaint = request.env['student.service.request.complaint'].sudo().create({
                'request_id': int(request_id),
                'user_id': int(user_id),
                'description': content,
            })
            
          
            files = httprequest.files.getlist('attachment')
            attachment_ids = []
            for file_storage in files:
                file_data = file_storage.read()
                base64_data = base64.b64encode(file_data).decode('utf-8')
                attachment = request.env['ir.attachment'].sudo().create({
                    'name': file_storage.filename,
                    'datas': base64_data,
                    'res_model': 'student.service.request.complaint',
                    'res_id': complaint.id,
                    'type': 'binary',
                    'mimetype': file_storage.mimetype or 'application/octet-stream',
                })
                attachment_ids.append(attachment.id)
            if attachment_ids:
                complaint.sudo().write({'image_ids': [(6, 0, attachment_ids)]})
                try:
                    send_fcm_request(
                        request.env,
                        complaint.request_id,
                        send_type=5  # Gửi thông báo khiếu nại
                    )
                except Exception as e:
                    pass  # Nếu không tìm thấy user_id thì bỏ qua
            return Response(
                json.dumps({'success': True, 'message': 'Gửi khiếu nại thành công', 'data': {
                    'id': complaint.id,
                    'request_id': complaint.request_id.id,
                    'user_id': complaint.user_id.id,

                    'name': complaint.name,
                    'description': complaint.description,
                    'image_ids': complaint.image_ids.ids,
                    'complaint_date': format_datetime_local(complaint.complaint_date, complaint.user_id.id)

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
                status=500,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                ]
            )