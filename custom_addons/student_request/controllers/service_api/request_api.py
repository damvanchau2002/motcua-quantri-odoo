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
import logging

_logger = logging.getLogger(__name__)
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
    cluster = env['student.dormitory.cluster'].sudo().search([('qlsv_cluster_id', '=', cluster_id)], limit=1)
    if not cluster:
        raise ValueError(f"Cluster không tồn tại: {cluster_id}")
    cluster_id = cluster.id

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
                'expired_date': Datetime.now() + timedelta(hours=service.duration or 168),  # Mặc định là 168 giờ nếu không có expired_duration
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
            'expired_date': Datetime.now() + timedelta(hours=service.duration or 168),  # Mặc định là 168 giờ nếu không có expired_duration
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
        step_request = env['student.service.request.step'].sudo().create(step_vals)
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
    Cập nhật yêu cầu dịch vụ đã có, dùng trong Sửa yêu cầu từ SV
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
    Duyệt 1 bước nào đó: Cập nhật bước yêu cầu dịch vụ (Update a service request step).
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

    if step.base_secquence == 99:
        if act == 'closed':
            # Kiểm tra lại đã có đánh giá nghiệm thu từ SV và người nghiệm thu, chưa có thì báo lỗi
            acceptance_result = env['student.service.request.result'].sudo().search([
                ('request_id', '=', requestid),
                ('action_user_id', '=', userid)
            ], limit=1)
            if not acceptance_result:
                raise ValueError("Chưa có đánh giá nghiệm thu từ sinh viên hoặc người nghiệm thu.")
                #return False

            # Lấy nghiệm thu của Admin cho yêu cầu này
            admin_acceptance = env['student.service.request.result'].sudo().search([
                ('request_id', '=', requestid),
                ('action_user_id', '!=', userid)
            ], limit=1)
            if not admin_acceptance:
                raise ValueError("Chưa có đánh giá nghiệm thu từ Admin.")
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
        # Mở lại các bước tiếp theo nếu sửa lại duyệt    
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
            act = 'assigned' # Update bước tiếp theo thành đã phân công
            # Cập nhật danh sách người đã xử lý yêu cầu
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
        'user_processing_id': nextuserid if nextuserid else department_user_id if department_user_id else None, # Phân công
        'final_state': act,
        'final_data': final_data if step.base_step_id.sequence == 99 else '',
        'department_ids': [(4, department_id)] if department_id else [],
    })

    if step.base_secquence == 99:
        vals['final_data'] = final_data
        # Nếu là approve bước cuối: THông báo đến Acc nghiệm thu và Người gửi yêu cầu
        if act == 'approved':
            send_fcm_request(env, request, 3) # Thông báo hoàn thành
            send_fcm_request(env, request, 7) # Thông báo đến Acc nghiệm thu
        if act == 'rejected':
            send_fcm_request(env, request, 8) # Thông báo đến Người gửi yêu cầu
        if act == 'repairing':
            send_fcm_request(env, request, 12) # Thông báo đến Người gửi yêu cầu
        if act == 'closed':
            # Kiểm tra lại đã có đánh giá nghiệm thu từ SV và người nghiệm thu
            send_fcm_request(env, request, 10) # Thông báo đóng yêu cầu
    else:
        send_fcm_request(env, request, 2) # Thông báo có cập nhật

    return vals

# Controller cho API dịch vụ
class ServiceApiController(http.Controller):

    def _get_cors_headers(self):
        return [
            ('Access-Control-Allow-Origin', '*'),
            ('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS'),
            ('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        ]

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
                    ('Access-Control-Allow-Credentials', 'true')
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
                    ('Access-Control-Allow-Credentials', 'true')
                ]
            )

        
    # Cập nhật yêu cầu dịch vụ
    # todo: cần kiểm tra trạng thái của yêu cầu trước khi cập nhật (chỉ cho cập nhật nếu là pending hoặc repairing )
    # Formdata: { request_id, request_user_id, note, files: [file1, file2, ...] }
    @http.route('/api/service/request/update', type='http', auth='public', methods=['POST'], csrf=False)
    def update_service_request(self, **kw):
        try:
            httprequest = request.httprequest
            files = httprequest.files.getlist('attachment')

            # Lấy dữ liệu từ form
            form = httprequest.form
            request_id = form.get('request_id')
            request_user_id = form.get('request_user_id')
            note = form.get('note', '')
            removed_image_ids = form.get('removed_image_ids', '[]')  # Danh sách ID ảnh cần xóa

            if not request_id:
                raise ValueError("Thiếu request_id")
            if not request_user_id:
                raise ValueError("Thiếu request_user_id")

            # Lấy request hiện tại
            service_request = request.env['student.service.request'].sudo().browse(int(request_id))
            if not service_request.exists():
                raise ValueError("Yêu cầu không tồn tại")

            # Xử lý danh sách ảnh cần xóa
            try:
                removed_ids = json.loads(removed_image_ids)
                if removed_ids and isinstance(removed_ids, list):
                    attachments_to_remove = request.env['ir.attachment'].sudo().browse(removed_ids)
                    # Chỉ xóa những ảnh thực sự thuộc về request này
                    valid_attachments = attachments_to_remove.filtered(
                        lambda a: a.res_model == 'student.service.request' and a.res_id == int(request_id)
                    )
                    if valid_attachments:
                        valid_attachments.sudo().unlink()
            except json.JSONDecodeError:
                _logger.warning("Invalid removed_image_ids format")

            # Upload và tạo attachments mới
            attachment_ids = []
            for file_storage in files:
                file_data = file_storage.read()
                base64_data = base64.b64encode(file_data).decode('utf-8')
                attachment = request.env['ir.attachment'].sudo().create({
                    'name': file_storage.filename,
                    'datas': base64_data,
                    'res_model': 'student.service.request',
                    'res_id': int(request_id),
                    'type': 'binary',
                    'mimetype': file_storage.mimetype or 'application/octet-stream',
                })
                attachment_ids.append(attachment.id)

            # Lấy danh sách ảnh hiện tại (không bao gồm ảnh đã xóa)
            current_attachments = service_request.image_attachment_ids - valid_attachments if 'valid_attachments' in locals() else service_request.image_attachment_ids

            # Gộp với ảnh mới
            all_attachment_ids = current_attachments.ids + attachment_ids

            # Cập nhật request với tất cả ảnh
            request_rec = update_request(
                env=request.env,
                requestid=request_id,
                userid=request_user_id,
                note=note,
                attachments=all_attachment_ids
            )

            return Response(
                json.dumps({
                    'success': True,
                    'service_id': request_rec.service_id.id,
                    'service_name': request_rec.service_id.name,
                    'content': request_rec.note,
                    'request_date': format_datetime_local(request_rec.write_date or request_rec.create_date, request_user_id),
                    'attachments': [{
                        'id': att.id,
                        'name': att.name,
                        'url': f'/api/download/image/{att.id}'
                    } for att in request_rec.image_attachment_ids]
                }),
                content_type='application/json',
            )

        except Exception as e:
            _logger.error(f"Error updating service request: {str(e)}")
            return Response(
                json.dumps({
                    'success': False,
                    'error': str(e),
                }),
                content_type='application/json',
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
                    'final_data': req.final_data,
                    'expired_date': format_datetime_local(req.expired_date, user_id),
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
                    ('Access-Control-Allow-Credentials', 'true'),
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
                    ('Access-Control-Allow-Credentials', 'true'),
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
            # domain = ['|',
            #     ('approve_user_id', '=', user_id),
            #     ('users', 'in', [user_id])
            # ]
            # if aprofile and aprofile.department_id and aprofile.dormitory_clusters:
            #     if aprofile.role_ids:
            #         domain = ['|'] + domain + [
            #             '&',
            #             ('service_id.role_ids', 'in', aprofile.role_ids.ids),
            #             ('dormitory_cluster_id', 'in', aprofile.dormitory_clusters.ids)
            #         ]
            user = request.env['res.users'].sudo().browse(user_id)
            if not user.exists():
                return Response(
                    json.dumps({'success': False, 'message': 'User không tồn tại'}),
                    content_type='application/json',
                    status=400,
                    headers=[
                        ('Access-Control-Allow-Origin', '*'),
                        ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                        ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                        ('Access-Control-Allow-Credentials', 'true')
                    ]
                )

            requests = request.env['student.service.request'].sudo().with_user(user).search([])

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
                    'final_data': True if req.final_data else False,  # Chuyển đổi rõ ràng
                    'expired_date': format_datetime_local(req.expired_date, user_id),

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
                    ('Access-Control-Allow-Credentials', 'true')
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
                    ('Access-Control-Allow-Credentials', 'true')
                ]
            )

     # Lấy danh sách các yêu cầu dịch vụ của user_id được giao
    @http.route('/api/service/request/myasigned', type='http', auth='public', methods=['GET'], csrf=False)
    def get_service_requests_asigned(self, **post):

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
                    'final_data': True if req.final_data else False,  # Chuyển đổi rõ ràng
                    'expired_date': format_datetime_local(req.expired_date, user_id),

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
                    ('Access-Control-Allow-Credentials', 'true')
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
                    ('Access-Control-Allow-Credentials', 'true')
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
                    ('Access-Control-Allow-Credentials', 'true')
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
                ('Access-Control-Allow-Credentials', 'true')
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
                    ('Access-Control-Allow-Credentials', 'true'),
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
                    ('Access-Control-Allow-Credentials', 'true'),
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
                    ('Access-Control-Allow-Credentials', 'true'),
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
                    ('Access-Control-Allow-Credentials', 'true'),
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
                    ('Access-Control-Allow-Credentials', 'true'),
                ]
            )


    # API: Thống kê yêu cầu dịch vụ
    @http.route('/api/service/request/statistics', type='http', auth='public', methods=['GET'], csrf=False)
    def get_request_statistics(self, **post):
        try:
            params = request.params
            user_id = params.get('user_id')
            # Số ngày cảnh báo sắp đến hạn (mặc định 2 ngày)
            warning_days = int(params.get('warning_days', 2))
            
            if not user_id:
                raise ValueError("Thiếu user_id")
            
            # Thời điểm hiện tại
            now = fields.Datetime.now()
            warning_date = now + timedelta(days=warning_days)

            # Base domain cho yêu cầu
            base_domain = []
            if user_id:
                base_domain += ['|', ('request_user_id', '=', int(user_id)), 
                              '|', ('user_processing_id', '=', int(user_id)),
                              ('users', 'in', [int(user_id)])]

            # 1. Thống kê yêu cầu mới (created trong 24h qua)
            new_requests_domain = base_domain + [
                ('create_date', '>=', now - timedelta(days=1))
            ]
            new_requests_count = request.env['student.service.request'].sudo().search_count(new_requests_domain)
            new_requests = request.env['student.service.request'].sudo().search(new_requests_domain)

            # 2. Thống kê yêu cầu đang xử lý
            processing_domain = base_domain + [
                ('final_state', 'in', ['pending', 'assigned'])
            ]
            processing_count = request.env['student.service.request'].sudo().search_count(processing_domain)
            processing_requests = request.env['student.service.request'].sudo().search(processing_domain)

            # 3. Thống kê yêu cầu quá hạn
            overdue_domain = base_domain + [
                ('expired_date', '<', now),
                ('final_state', 'in', ['pending', 'assigned'])
            ]
            overdue_count = request.env['student.service.request'].sudo().search_count(overdue_domain)
            overdue_requests = request.env['student.service.request'].sudo().search(overdue_domain)

            # 4. Thống kê yêu cầu sắp đến hạn
            warning_domain = base_domain + [
                ('expired_date', '>=', now),
                ('expired_date', '<=', warning_date),
                ('final_state', 'in', ['pending', 'assigned'])
            ]
            warning_count = request.env['student.service.request'].sudo().search_count(warning_domain)
            warning_requests = request.env['student.service.request'].sudo().search(warning_domain)

            # Format dữ liệu chi tiết cho từng yêu cầu
            def format_request_data(reqs):
                return [{
                    'id': req.id,
                    'name': req.name,
                    'service_name': req.service_id.name if req.service_id else '',
                    'request_date': format_datetime_local(req.create_date, user_id),
                    'expired_date': format_datetime_local(req.expired_date, user_id),
                    'final_state': req.final_state,
                    'request_user_name': req.request_user_id.name if req.request_user_id else '',
                    'processing_user_name': req.user_processing_id.name if req.user_processing_id else ''
                } for req in reqs]

            return Response(
                json.dumps({
                    'success': True,
                    'data': {
                        'summary': {
                            'new_requests': new_requests_count,
                            'processing_requests': processing_count,
                            'overdue_requests': overdue_count,
                            'warning_requests': warning_count,
                        },
                        'details': {
                            'new_requests': format_request_data(new_requests),
                            'processing_requests': format_request_data(processing_requests),
                            'overdue_requests': format_request_data(overdue_requests),
                            'warning_requests': format_request_data(warning_requests)
                        }
                    },
                    'message': 'Thống kê thành công'
                }),
                content_type='application/json',
                status=200,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true'),
                ]
            )

        except Exception as e:
            return Response(
                json.dumps({
                    'success': False,
                    'message': str(e),
                    'data': {}
                }),
                content_type='application/json',
                status=500,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true'),
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
                    ('Access-Control-Allow-Credentials', 'true'),
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
                    ('Access-Control-Allow-Credentials', 'true'),
                ]
            )

    # API: Hủy yêu cầu dịch vụ
    @http.route('/api/service/request/cancel', type='http', auth='public', methods=['POST', 'OPTIONS'], csrf=False)
    def cancel_service_request(self, **post):
        if request.httprequest.method == 'OPTIONS':
            return self._handle_options_request()

        try:
            params = request.httprequest.get_json(force=True, silent=True) or {}
            request_id = params.get('request_id')
            user_id = params.get('user_id')
            cancel_reason = params.get('cancel_reason', '')

            if not request_id or not user_id:
                return Response(
                    json.dumps({
                        'success': False,
                        'message': 'Thiếu request_id hoặc user_id'
                    }),
                    content_type='application/json',
                    status=400,
                    headers=self._get_cors_headers()
                )

            # Kiểm tra yêu cầu tồn tại và thuộc về user
            service_request = request.env['student.service.request'].sudo().browse(int(request_id))
            if not service_request.exists():
                return Response(
                    json.dumps({
                        'success': False,
                        'message': 'Không tìm thấy yêu cầu'
                    }),
                    content_type='application/json',
                    status=404,
                    headers=self._get_cors_headers()
                )

            # Kiểm tra quyền hủy yêu cầu
            if service_request.request_user_id.id != int(user_id):
                return Response(
                    json.dumps({
                        'success': False,
                        'message': 'Bạn không có quyền hủy yêu cầu này'
                    }),
                    content_type='application/json',
                    status=403,
                    headers=self._get_cors_headers()
                )

            # Kiểm tra trạng thái yêu cầu - chỉ cho phép hủy khi ở trạng thái pending
            if service_request.final_state != 'pending':
                return Response(
                    json.dumps({
                        'success': False,
                        'message': 'Chỉ có thể hủy yêu cầu ở trạng thái chờ duyệt'
                    }),
                    content_type='application/json',
                    status=400,
                    headers=self._get_cors_headers()
                )

            # Cập nhật trạng thái yêu cầu thành "cancelled"
            service_request.write({
                'final_state': 'cancelled',
                'cancel_reason': cancel_reason,
                'cancel_date': fields.Datetime.now(),
                'cancel_user_id': int(user_id)
            })

            # Tạo history cho việc hủy yêu cầu
            current_step = service_request.step_ids.filtered(lambda s: s.state in ['pending', 'assigned'])
            if current_step:
                current_step[0].history_ids.sudo().create({
                    'step_id': current_step[0].id,
                    'user_id': int(user_id),
                    'state': 'cancelled',
                    'note': cancel_reason or 'Yêu cầu đã bị hủy bởi người dùng',
                    'date': fields.Datetime.now()
                })

            # Gửi thông báo cho admin/staff nếu cần
            try:
                send_fcm_request(
                    request.env,
                    service_request,
                    send_type=8  # Định nghĩa type cho thông báo hủy yêu cầu
                )
            except Exception as e:
                _logger.error(f"Error sending FCM notification: {str(e)}")

            return Response(
                json.dumps({
                    'success': True,
                    'message': 'Yêu cầu đã được hủy thành công',
                    'data': {
                        'request_id': service_request.id,
                        'final_state': 'cancelled',
                        'cancel_date': fields.Datetime.to_string(service_request.cancel_date),
                        'cancel_reason': service_request.cancel_reason
                    }
                }),
                content_type='application/json',
                status=200,
                headers=self._get_cors_headers()
            )

        except Exception as e:
            _logger.error(f"Error cancelling service request: {str(e)}")
            return Response(
                json.dumps({
                    'success': False,
                    'message': str(e)
                }),
                content_type='application/json',
                status=500,
                headers=self._get_cors_headers()
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
                        ('Access-Control-Allow-Credentials', 'true'),
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
                        ('Access-Control-Allow-Credentials', 'true'),
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
                    ('Access-Control-Allow-Credentials', 'true'),
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
                    ('Access-Control-Allow-Credentials', 'true'),
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
                    ('Access-Control-Allow-Credentials', 'true'),
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
                    ('Access-Control-Allow-Credentials', 'true'),
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
                        ('Access-Control-Allow-Credentials', 'true'),
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
                    ('Access-Control-Allow-Credentials', 'true'),
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
                    ('Access-Control-Allow-Credentials', 'true'),
                ]
            )

    # Đánh giá nghiệm thu của SV
    @http.route('/api/service/request/acceptance/create', type='http', auth='public', methods=['POST'], csrf=False)
    def create_service_request_acceptance(self, **post):
        """
            Tạo đánh giá nghiệm thu cho yêu cầu dịch vụ
            
        """
        try:
            httprequest = request.httprequest

            # Lấy dữ liệu từ form
            form = httprequest.form
            request_id = form.get('request_id') 
            accept_user_id = form.get('accept_user_id')
            content = form.get('content', '')       # Nội dung đánh giá
            action = form.get('action', 'issue')    # Hành động 
            stars = int(form.get('star', 0))            # Số sao đánh giá

            service_request = request.env['student.service.request'].sudo().browse(int(request_id))
            if not service_request.exists():
                return Response(
                    json.dumps({'success': False, 'message': 'Yêu cầu dịch vụ không tồn tại'}),
                    content_type='application/json',
                    status=404,
                    headers=[
                        ('Access-Control-Allow-Origin', '*'),
                        ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                        ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                        ('Access-Control-Allow-Credentials', 'true'),
                    ]
                )

            acceptance = request.env['student.service.request.result'].sudo().create({
                'request_id': int(request_id),
                'user_id': int(service_request.request_user_id.id),
                'note': content,
                'action': action,
                'star': stars,
                'action_user': int(accept_user_id),
                'acceptance_ids': [(6, 0, service_request.users.ids)]  # Gán tất cả người dùng liên quan đến yêu cầu dịch vụ này
            })

            # Xử lý file đính kèm
            attachment_ids = []
            try:
                files = httprequest.files.getlist('attachment')
                for file_storage in files:
                    file_data = file_storage.read()
                    base64_data = base64.b64encode(file_data).decode('utf-8')
                    attachment = request.env['ir.attachment'].sudo().create({
                        'name': file_storage.filename,
                        'datas': base64_data,
                        'res_model': 'student.service.request.result',
                        'res_id': acceptance.id,
                        'type': 'binary',
                        'mimetype': file_storage.mimetype or 'application/octet-stream',
                    })
                    attachment_ids.append(attachment.id)
                if attachment_ids:
                    acceptance.sudo().write({'image_ids': [(6, 0, attachment_ids)]})
            except Exception as e:
                pass  # Nếu không tìm thấy user_id thì bỏ qua

            # Cập nhật trạng thái cuối cho yêu cầu dịch vụ
            if action == 'accept':
                service_request.sudo().write({'final_state': 'closed', 'final_star': stars })
                send_fcm_request(request.env, service_request, 10)  # Gửi thông báo nghiệm thu từ SV 
                # Kiểm tra đã có nghiệm thu accept của Admin thì đóng yêu cầu
                # Lấy nghiệm thu của User khác
                other_acceptance = request.env['student.service.request.result'].sudo().search([
                    ('request_id', '=', service_request.id),
                    ('user_id', '!=', service_request.request_user_id.id)
                ], order='timestamp desc', limit=1)
                if other_acceptance and other_acceptance.action == 'accept':
                    service_request.sudo().write({'final_state': 'closed', 'final_star': stars})
                    send_fcm_request(request.env, service_request, 10)  # Gửi thông báo nghiệm thu từ Admin

            elif action == 'reject' or action == 'issue':
                service_request.sudo().write({'final_state': 'repairing', 'final_star': stars})
                send_fcm_request(
                    request.env,
                    service_request,
                    9  # Cần xử lý lại yêu cầu
                )
                
            return Response(
                json.dumps({'success': True, 'message': 'Gửi nghiệm thu thành công', 'data': {
                    'id': acceptance.id,
                    'request_id': acceptance.request_id.id,
                    'user_id': acceptance.user_id.id,
                    'note': acceptance.note,
                    'action': acceptance.action,
                    'star': acceptance.star,
                    'action_user': acceptance.action_user.id,
                    'image_ids': acceptance.image_ids.ids if acceptance.image_ids else [],
                    'timestamp': format_datetime_local(acceptance.timestamp)

                }}),
                content_type='application/json',
                status=200,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true'),
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
                    ('Access-Control-Allow-Credentials', 'true'),
                ]
            )
    @http.route('/api/service/request/acceptance/list', type='http', auth='public', methods=['GET'], csrf=False)
    def list_service_request_acceptances(self, **kwargs):
        try:
            params = request.httprequest.args or request.params
            request_id = params.get('request_id')
            user_id = params.get('user_id')
            page = int(params.get('page', 1))
            limit = int(params.get('limit', 10))
            
            domain = []
            if request_id:
                domain.append(('request_id', '=', int(request_id)))
            if user_id:
                domain.append(('user_id', '=', int(user_id)))

            # Tính total và offset
            total = request.env['student.service.request.result'].sudo().search_count(domain)
            offset = (page - 1) * limit

            # Lấy danh sách nghiệm thu
            acceptances = request.env['student.service.request.result'].sudo().search(
                domain, 
                offset=offset, 
                limit=limit, 
                order='timestamp desc'
            )

            result = []
            for acceptance in acceptances:
                result.append({
                    'id': acceptance.id,
                    'request_id': acceptance.request_id.id if acceptance.request_id else None,
                    'request_name': acceptance.request_id.name if acceptance.request_id else '',
                    'service_name': acceptance.request_id.service_id.name if acceptance.request_id.service_id else '',
                    
                    'user_id': acceptance.user_id.id if acceptance.user_id else None,
                    'user_name': acceptance.user_id.name if acceptance.user_id else '',
                    
                    'action_user': acceptance.action_user.id if acceptance.action_user else None,
                    'action_user_name': acceptance.action_user.name if acceptance.action_user else '',
                    
                    'note': acceptance.note,
                    'action': acceptance.action,
                    'star': acceptance.star,
                    
                    'image_ids': [{
                        'id': img.id,
                        'name': img.name,
                        'url': f'/api/download/image/{img.id}'
                    } for img in acceptance.image_ids] if acceptance.image_ids else [],
                    
                    'timestamp': format_datetime_local(acceptance.timestamp),
                    
                    # Thông tin thêm về request
                    'request_info': {
                        'final_state': acceptance.request_id.final_state if acceptance.request_id else '',
                        'final_star': acceptance.request_id.final_star if acceptance.request_id else 0,
                        'request_date': format_datetime_local(acceptance.request_id.request_date) if acceptance.request_id else '',
                    }
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
                    'data': result
                }),
                content_type='application/json',
                status=200,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true'),
                ]
            )

        except Exception as e:
            _logger.error(f"Error getting acceptances list: {str(e)}")
            return Response(
                json.dumps({
                    'success': False,
                    'message': str(e),
                    'data': []
                }),
                content_type='application/json',
                status=500,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true'),
                ]
            )
    @http.route('/api/service/request/images', type='http', auth='public', methods=['GET'], csrf=False)
    def get_request_images(self):
        try:
            params = request.params
            request_id = params.get('request_id')

            if not request_id:
                return Response(
                    json.dumps({
                        'success': False,
                        'message': 'Missing request_id'
                    }),
                    content_type='application/json',
                    status=400,
                    headers=[
                        ('Access-Control-Allow-Origin', '*'),
                        ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                        ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                        ('Access-Control-Allow-Credentials', 'true'),
                    ]
                )

            service_request = request.env['student.service.request'].sudo().browse(int(request_id))
            if not service_request.exists():
                return Response(
                    json.dumps({
                        'success': False,
                        'message': 'Request not found'
                    }),
                    content_type='application/json',
                    status=404,
                    headers=[
                        ('Access-Control-Allow-Origin', '*'),
                        ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                        ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                        ('Access-Control-Allow-Credentials', 'true'),
                    ]
                )

            # Lấy thông tin các ảnh đính kèm
            images = []
            if service_request.image_attachment_ids:
                for attachment in service_request.image_attachment_ids:
                    if attachment.mimetype and 'image' in attachment.mimetype:
                        images.append({
                            'id': attachment.id,
                            'name': attachment.name,
                            'mimetype': attachment.mimetype,
                            'file_size': attachment.file_size,
                            'url': f'/api/download/image/{attachment.id}',
                            'create_date': attachment.create_date.strftime('%Y-%m-%d %H:%M:%S') if attachment.create_date else '',
                        })

            return Response(
                json.dumps({
                    'success': True,
                    'message': 'Success',
                    'data': images
                }),
                content_type='application/json',
                status=200,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true'),
                ]
            )

        except Exception as e:
            _logger.error(f"Error getting request images: {str(e)}")
            return Response(
                json.dumps({
                    'success': False,
                    'message': str(e)
                }),
                content_type='application/json',
                status=500,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true'),
                ]
            )

    @http.route('/api/download/image/<int:attachment_id>', type='http', auth='public', methods=['GET'], csrf=False)
    def download_image(self, attachment_id):
        try:
            # Tìm attachment
            attachment = request.env['ir.attachment'].sudo().browse(int(attachment_id))
            if not attachment.exists():
                return Response(
                    json.dumps({
                        'success': False,
                        'message': 'Attachment not found'
                    }),
                    content_type='application/json',
                    status=404,
                    headers=[
                        ('Access-Control-Allow-Origin', '*'),
                        ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                        ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                        ('Access-Control-Allow-Credentials', 'true'),
                    ]
                )

            # Kiểm tra mimetype có phải là ảnh không
            if not attachment.mimetype or 'image' not in attachment.mimetype:
                return Response(
                    json.dumps({
                        'success': False,
                        'message': 'File is not an image'
                    }),
                    content_type='application/json',
                    status=400,
                    headers=[
                        ('Access-Control-Allow-Origin', '*'),
                        ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                        ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                        ('Access-Control-Allow-Credentials', 'true'),
                    ]
                )

            # Lấy dữ liệu ảnh
            image_data = base64.b64decode(attachment.datas) if attachment.datas else None
            if not image_data:
                return Response(
                    json.dumps({
                        'success': False,
                        'message': 'Image data not found'
                    }),
                    content_type='application/json',
                    status=404,
                    headers=[
                        ('Access-Control-Allow-Origin', '*'),
                        ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                        ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                        ('Access-Control-Allow-Credentials', 'true'),
                    ]
                )

            # Trả về file ảnh
            return request.make_response(
                image_data,
                headers=[
                    ('Content-Type', attachment.mimetype),
                    ('Content-Disposition', f'inline; filename="{attachment.name}"'),
                    ('Content-Length', len(image_data)),
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true'),
                ]
            )

        except Exception as e:
            _logger.error(f"Error downloading image: {str(e)}")
            return Response(
                json.dumps({
                    'success': False,
                    'message': str(e)
                }),
                content_type='application/json',
                status=500,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true'),
                ]
            )