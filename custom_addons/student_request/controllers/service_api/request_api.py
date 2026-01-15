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


def normalize_date_input(date_str):
    if not date_str:
        return False
    try:
        # Try parsing DD/MM/YYYY
        return datetime.strptime(date_str, '%d/%m/%Y').strftime('%Y-%m-%d')
    except ValueError:
        return date_str # Assume it's already YYYY-MM-DD or let Odoo handle the error


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
    if cluster_id and cluster_id.exists():
        domain = [('dormitory_clusters', 'in', [cluster_id.id]), ('role_ids', 'in', service.role_ids.ids)]
        dormitory_admins = env['student.admin.profile'].sudo().search(domain)

        if dormitory_admins:  # Nếu có quản lý KTX thì lấy user_id của họ
            received_users += dormitory_admins.mapped('user_id.id')

    return received_users


def create_request(env, serviceid, requestid, userid, note, attachments, input_data=None):
    """
    Tạo hoặc cập nhật yêu cầu dịch vụ
            :param env: Odoo environment
            :param serviceid: ID của dịch vụ
            :param requestid: ID của yêu cầu (nếu có)
            :param userid: ID của người dùng yêu cầu
            :param note: Ghi chú của yêu cầu
            :param attachments: Danh sách ID của các file đính kèm
            :param input_data: Dict chứa dữ liệu dynamic form {field_name: value}
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
    
    sysuser = env['res.users'].sudo().browse(1)  # User hệ thống để tạo request

    attachments = attachments or []
    vals = {}
    # Nếu có request_id => cập nhật (chô này nếu tạo trên Web sẽ luôn có request_id và không có step_ids)
    if requestid and str(requestid).isdigit() and int(requestid) > 0:
        vals = env['student.service.request'].sudo().with_user(sysuser).browse(int(requestid))
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
            
            # Gán thông tin profile sinh viên ngay khi tạo
            'request_user_phone': user_profile.phone or user.phone or user.mobile or '',
            'request_user_dormitory_full': user_profile.dormitory_full_name or '',
            'request_user_dormitory_house': user_profile.dormitory_house_name or '',
            'request_user_dormitory_room': user_profile.dormitory_room_id or '',
        }

    # Tạo mới yêu cầu các bước xử lý
    received_users = [] # Danh sách user sẽ nhận yêu cầu
    step_ids = [] # Danh sách các bước duyệt
    for step_selection in service.step_selection_ids.sorted('sequence'):
        step = step_selection.step_id
        step_vals = {
            'request_id': False,
            'base_step_id': step.id,
            'state': 'pending',
        }
        step_request = env['student.service.request.step'].sudo().create(step_vals)
        if step_selection == service.step_selection_ids.sorted('sequence')[0] and service.files:
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
    print(f"=== DEBUG USER_PROCESSING_ID ===")
    print(f"Service role_ids: {service.role_ids.ids}")
    print(f"Cluster_id: {cluster_id}")
    
    qlsv_profiles = env['student.admin.profile'].sudo().search([
        ('role_ids', 'in', service.role_ids.ids),
        ('dormitory_clusters.qlsv_cluster_id', '=', cluster_id)
    ])
    print(f"Found qlsv_profiles: {len(qlsv_profiles)} profiles")
    for profile in qlsv_profiles:
        print(f"Profile: user_id={profile.user_id.id}, name={profile.user_id.name}, roles={profile.role_ids.mapped('name')}")
    
    if qlsv_profiles:
        user_processing_id = qlsv_profiles[0].user_id.id
        received_users += qlsv_profiles.mapped('user_id.id')
        print(f"Selected user_processing_id: {user_processing_id}")
    else:
        print("No qlsv_profiles found - user_processing_id will be 0")

    if user_processing_id > 0:
        vals['user_processing_id'] = user_processing_id
        received_users.append(user_processing_id)
        print(f"Set user_processing_id in vals: {user_processing_id}")
    else:
        print("user_processing_id is 0 - not setting in vals")
    print(f"=== END DEBUG USER_PROCESSING_ID ===")
    print(f"Final received_users: {received_users}")

    if len(received_users) > 0:
        vals['users'] = [(6, 0, received_users)]

    try:
        if vals.id > 0:
            return vals
    
        raise ValueError("Thiếu ID yêu cầu")
    except Exception as e:
        vals = env['student.service.request'].sudo().with_user(sysuser).create(vals)
        
        # Cập nhật lại thông tin profile để đảm bảo dữ liệu được lưu (do field compute có thể ghi đè bằng giá trị rỗng)
        vals.sudo().write({
            'request_user_phone': user_profile.phone or user.phone or user.mobile or '',
            'request_user_dormitory_full': user_profile.dormitory_full_name or '',
            'request_user_dormitory_house': user_profile.dormitory_house_name or '',
            'request_user_dormitory_room': user_profile.dormitory_room_id or '',
        })
        
        send_fcm_request(env, vals, 0)
        pass
    
    # Xử lý input_data để tạo input_ids
    if input_data and isinstance(input_data, dict):
        input_ids_commands = []
        
        # Lấy danh sách form fields của service
        form_fields = service.form_field_ids
        
        for field in form_fields:
            field_name = field.name
            if field_name not in input_data:
                continue  # Bỏ qua nếu không có dữ liệu
            
            value = input_data[field_name]
            
            # Chuẩn bị dữ liệu cho input record
            input_vals = {
                'service_form_field_id': field.id,
                'sequence': field.sequence,
                'name': field.name,
                'label': field.label,
                'field_type': field.field_type,
                'required': field.required,
                'placeholder': field.placeholder,
            }
            
            # Gán giá trị tùy theo loại field
            if field.field_type == 'text':
                input_vals['value_char'] = value
            elif field.field_type == 'textarea':
                input_vals['value_text'] = value
            elif field.field_type == 'number':
                input_vals['value_float'] = float(value) if value else 0.0
            elif field.field_type == 'date':
                input_vals['value_date'] = normalize_date_input(value)
            elif field.field_type == 'checkbox':
                input_vals['value_boolean'] = bool(value)
            elif field.field_type == 'select':
                # value là list các option IDs
                option_ids = value if isinstance(value, list) else [value] if isinstance(value, int) else []
                if option_ids:
                    input_vals['selected_option_ids'] = [(6, 0, option_ids)]
            elif field.field_type == 'date_multi':
                # value là list các ngày ['2025-11-27', '2025-11-28', ...]
                # Tạo input record trước, sau đó tạo date_ids
                input_record = env['student.service.request.input'].sudo().create(input_vals)
                
                # Tạo các bản ghi date
                if isinstance(value, list):
                    for date_str in value:
                        env['student.service.request.input.date'].sudo().create({
                            'input_id': input_record.id,
                            'date': normalize_date_input(date_str)
                        })
                
                # Thêm vào danh sách input_ids
                input_ids_commands.append((4, input_record.id))
                continue  # Đã xử lý xong, bỏ qua phần create bên dưới
            
            # Tạo input record (trừ date_multi đã xử lý ở trên)
            input_ids_commands.append((0, 0, input_vals))
        
        # Cập nhật input_ids cho request
        if input_ids_commands:
            vals.sudo().write({'input_ids': input_ids_commands})
    
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
    sysuser = env['res.users'].sudo().browse(1)

    request = env['student.service.request'].sudo().with_user(sysuser).browse(int(requestid))
    if not request.exists():
        raise ValueError(f"Yêu cầu không tồn tại: {requestid}")

    user = env['res.users'].sudo().with_user(sysuser).browse(int(userid))
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
    request.sudo().with_user(sysuser).write(vals)

    # Gửi FCM thông báo cập nhật yêu cầu
    send_fcm_request(env, request, 1)

    return request


#Duyệt 1 bước (env, dịch vụ, bước, người duyệt, ghi chú, action duyệt, user được giao, file đính kèm, kết luận)
def update_request_step(env, requestid, stepid, userid, note, act, nextuserid, docs, final_data, department_id=0, status_id=None):
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
        status_id (int, optional): ID của trạng thái chi tiết (dynamic status). Mặc định là None.
    Returns:
        dict or bool: Trả về dict chứa thông tin cập nhật nếu thành công, False nếu không tìm thấy bước (Returns a dict with updated information if successful, False if the step is not found).
    """
    # Tạo system user để có quyền truy cập
    system_user = env['res.users'].sudo().browse(1)
    
    request = env['student.service.request'].sudo().with_user(system_user).browse(requestid)
    step = request.step_ids.sudo().browse(stepid)
    # Lấy bước theo thứ tự sequence, lấy bước đầu tiên chưa ignored, approved hoặc rejected
    # step = service.step_ids.filtered(lambda s: s.state not in ('ignored', 'approved', 'rejected')).sorted('sequence')
    # step = step[0] if step else service.step_ids.browse(stepid)
    if not step.exists():
        return False

    if step.sudo().base_secquence == 99:
        if act == 'closed':
            # Kiểm tra lại đã có đánh giá nghiệm thu từ SV và người nghiệm thu, chưa có thì báo lỗi
            acceptance_result = env['student.service.request.result'].sudo().with_user(system_user).search([
                ('request_id', '=', requestid),
                ('action_user_id', '=', userid)
            ], limit=1)
            if not acceptance_result:
                raise ValueError("Chưa có đánh giá nghiệm thu từ sinh viên hoặc người nghiệm thu.")
                #return False

            # Lấy nghiệm thu của Admin cho yêu cầu này
            admin_acceptance = env['student.service.request.result'].sudo().with_user(system_user).search([
                ('request_id', '=', requestid),
                ('action_user_id', '!=', userid)
            ], limit=1)
            if not admin_acceptance:
                raise ValueError("Chưa có đánh giá nghiệm thu từ Admin.")
                return False

    # nếu act khác pending thì tìm các bước trước đó còn pending cập nhật nó thanh ignored
    if act != 'pending':
        prev_steps = request.step_ids.sudo().filtered(lambda s: s.base_secquence < step.sudo().base_secquence and (s.state == 'pending' or s.state == 'assigned' or s.state == 'rejected'))
        for s in prev_steps:
            s.sudo().state = 'ignored'
            # Tạo bản ghi history cho các bước đã ignored
            h = env['student.service.request.step.history'].sudo().create({
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
        next_steps = request.step_ids.sudo().filtered(lambda s: s.base_secquence > step.sudo().base_secquence and (s.state != 'pending'))
        for s in next_steps:
            s.sudo().state = 'pending'
            s.sudo().write({
                'state': 'pending',
                'approve_content': 'Chuyển lại trạng thái chờ duyệt do thay đổi trạng thái bước trước',
                'approve_date': Datetime.now(),
                'assign_user_id': nextuserid if nextuserid else 0,
            })


    # Tạo bản ghi history cho bước đang duyệt
    history_vals = {
        'request_id': requestid,
        'step_id': step.id,
        'state': act,
        'user_id': userid,
        'note': note,
        'date': Datetime.now(),
    }
    if status_id:
        history_vals['status_id'] = status_id
        
    hh = env['student.service.request.step.history'].sudo().with_user(system_user).create(history_vals)

    vals = {
        'request_id': requestid,
        'base_step_id': step.sudo().base_step_id.id if step.sudo().base_step_id else False,
        'approve_content': note,
        'state': act,
        'approve_date': Datetime.now(),
        'assign_user_id': nextuserid if nextuserid else 0,
        'history_ids': [(4, hh.id)],
    }
    if status_id:
        vals['status_id'] = status_id
    
    if step.base_secquence == 1:
        vals['file_ids'] = [(6, 0, step.file_ids.ids)]
        if docs:
            # Nếu có danh sách docs (checked_ids) gửi lên thì cập nhật
            vals['file_checkbox_ids'] = [(6, 0, docs)]
        else:
            # Nếu không có thì giữ nguyên
            vals['file_checkbox_ids'] = [(6, 0, step.file_checkbox_ids.ids)]

    next_step_users = []
    department_user_id = 0
    # Chỗ này tìm người tiếp theo được phân công theo nextuserid hoặc department_id gán vào mảng next_step_users
    if nextuserid and nextuserid > 0:
        next_step_users.append(nextuserid)
    if department_id and department_id > 0:
        department_users = env['student.admin.profile'].sudo().search([('department_id', '=', department_id), ('role_ids.level', 'in', [9])])
        department_user_id = department_users and department_users[0].id or 0
        next_step_users.extend(department_users.ids)

    #Nếu chưa phải bước cuối cùng và duyệt đã hoàn thành
    if step.base_secquence != 99 and act == 'approved':
        #Tìm bước tiếp theo trong request.step_ids theo sequence
        next_step = request.step_ids.sudo().filtered(lambda s: s.base_secquence > step.base_secquence).sorted('base_secquence')
        if next_step:
            next_step = next_step[0]
            # Xác định phòng ban sẽ tự động điền cho bước kế tiếp
            prefill_dep_id = False
            try:
                # Ưu tiên lấy phòng ban đã phân công ở bước hiện tại
                if step.department_id:
                    prefill_dep_id = step.department_id.id
                # Nếu bước hiện tại chưa có phòng ban nhưng đã có người được phân công cho bước kế tiếp
                elif nextuserid:
                    admin_profile = env['student.admin.profile'].sudo().search([
                        ('user_id', '=', nextuserid),
                        ('activated', '=', True)
                    ], limit=1)
                    if admin_profile and admin_profile.department_id:
                        prefill_dep_id = admin_profile.department_id.id
            except Exception:
                prefill_dep_id = False
            next_step.sudo().with_user(system_user).write({
                'state': 'assigned',
                'assign_user_id': nextuserid if nextuserid else 0,
                'department_id': prefill_dep_id or False,
                'approve_date': Datetime.now(),
                'approve_content': f'Đang chờ duyệt bước {next_step.base_step_id.name}',
            })
            note = f'Đã duyệt bước {step.base_step_id.name}, đang chờ duyệt bước {next_step.base_step_id.name}'
            act = 'assigned' # Update bước tiếp theo thành đã phân công
            # Cập nhật danh sách người đã xử lý yêu cầu
            received_users = get_user_received_requests(env, request.dormitory_cluster_id, request.service_id, next_step)
            if received_users:
                next_step_users += received_users

    #Update database: request các field: approve_content approve_date final_state final_data
    request.sudo().with_user(system_user).write({
        'users': [(4, uid) for uid in next_step_users],
        'approve_content': note,
        'approve_date': Datetime.now(),
        'approve_user_id': userid,
        'is_new': False,
        'user_processing_id': nextuserid if nextuserid else department_user_id if department_user_id else None, # Phân công
        'final_state': act,
        'final_data': final_data if step.base_secquence == 99 else '',
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
            ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
            ('Access-Control-Allow-Credentials', 'true'),
            ('Access-Control-Max-Age', '86400'),  # Cache preflight for 24 hours
        ]
        
    def _handle_options_request(self):
        return Response(
            status=200,
            headers=self._get_cors_headers()
        )

       # Tạo yêu cầu dịch vụ mới
    # Fromdata: { service_id, request_user_id, note, files: [file1, file2, ...] }
    @http.route('/api/service/request/create', type='http', auth='public', methods=['POST', 'OPTIONS'], csrf=False)
    def create_service_request(self, **post):
        if request.httprequest.method == 'OPTIONS':
            return Response(
                status=200,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true'),
                    ('Access-Control-Max-Age', '86400'),
                ]
            )
            
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
            
            # --- SỬA Ở ĐÂY: Đổi input_data thành dynamic_data ---
            input_data_str = form.get('dynamic_data', '{}') 
            _logger.info(f"DEBUG: Received dynamic_data: {input_data_str}") # Thêm log để kiểm tra

            # Parse input_data
            try:
                input_data = json.loads(input_data_str) if input_data_str else {}
            except json.JSONDecodeError:
                _logger.error(f"JSON Decode Error: {input_data_str}")
                input_data = {}

            # Gọi hàm tạo yêu cầu
            request_rec = create_request(request.env, service_id, request_id, request_user_id, note, attachment_ids, input_data)

            return Response(
                json.dumps({
                    'success': True,
                    'message': 'Tạo yêu cầu dịch vụ thành công',
                    'data': {
                        'id': request_rec.id,
                        'service_id': request_rec.service_id.id,
                        'service_name': request_rec.service_id.name,
                        'content': request_rec.note,
                        'request_date': format_datetime_local(request_rec.create_date, request_user_id),
                        'inputs': [{
                            'name': inp.name,
                            'label': inp.label,
                            'type': inp.field_type,
                            'value_display': inp.value_display,
                        } for inp in request_rec.input_ids]
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
            _logger.exception("Error creating service request") # Log lỗi chi tiết
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
    # Formdata: { request_id, request_user_id, note, files: [file1, file2, ...], dynamic_data: "{...}" }
    @http.route('/api/service/request/update', type='http', auth='public', methods=['POST', 'OPTIONS'], csrf=False)
    def update_service_request(self, **kw):
        if request.httprequest.method == 'OPTIONS':
            return Response(
                status=200,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true'),
                    ('Access-Control-Max-Age', '86400')  # Cache preflight for 24 hours
                ]
            )

        try:
            httprequest = request.httprequest
            files = httprequest.files.getlist('attachment')
            sysuser = request.env['res.users'].sudo().browse(1)
            
            # Lấy dữ liệu từ form
            form = httprequest.form
            request_id = form.get('request_id')
            request_user_id = form.get('request_user_id')
            note = form.get('note', '')
            removed_image_ids = form.get('removed_image_ids', '[]')  # Danh sách ID ảnh cần xóa
            
            # --- SỬA Ở ĐÂY: Đổi input_data thành dynamic_data ---
            input_data_str = form.get('dynamic_data', '{}') 
            _logger.info(f"DEBUG UPDATE: Received dynamic_data: {input_data_str}")

            # Parse input_data
            try:
                input_data = json.loads(input_data_str) if input_data_str else {}
            except json.JSONDecodeError:
                _logger.error(f"JSON Decode Error in Update: {input_data_str}")
                input_data = {}

            if not request_id:
                raise ValueError("Thiếu request_id")
            if not request_user_id:
                raise ValueError("Thiếu request_user_id")

            # Lấy request hiện tại
            service_request = request.env['student.service.request'].sudo().with_user(sysuser).browse(int(request_id))
            if not service_request.exists():
                raise ValueError("Yêu cầu không tồn tại")

            # Xử lý danh sách ảnh cần xóa
            try:
                removed_ids = json.loads(removed_image_ids)
                if removed_ids and isinstance(removed_ids, list):
                    attachments_to_remove = request.env['ir.attachment'].sudo().with_user(sysuser).browse(removed_ids)
                    # Chỉ xóa những ảnh thực sự thuộc về request này
                    valid_attachments = attachments_to_remove.filtered(
                        lambda a: a.res_model == 'student.service.request' and a.res_id == int(request_id)
                    )
                    if valid_attachments:
                        valid_attachments.sudo().with_user(sysuser).unlink()
            except json.JSONDecodeError:
                _logger.warning("Invalid removed_image_ids format")

            # Upload và tạo attachments mới
            attachment_ids = []
            for file_storage in files:
                file_data = file_storage.read()
                base64_data = base64.b64encode(file_data).decode('utf-8')
                attachment = request.env['ir.attachment'].sudo().with_user(sysuser).create({
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

            # Kiểm tra xem có bước nào đang ở trạng thái 'adjust_profile' không
            current_step = service_request.step_ids.sudo().filtered(lambda s: s.state == 'adjust_profile')
            
            # Cập nhật request với tất cả ảnh
            request_rec = update_request(
                env=request.env,
                requestid=request_id,
                userid=request_user_id,
                note=note,
                attachments=all_attachment_ids
            )

            # Xử lý cập nhật input_data (dynamic form)
            if input_data and isinstance(input_data, dict):
                _logger.info(f"Updating dynamic inputs for request {request_id}")
                
                # Xóa các input cũ
                service_request.input_ids.sudo().unlink()
                
                # Tạo lại input_ids mới
                input_ids_commands = []
                form_fields = service_request.service_id.form_field_ids
                
                for field in form_fields:
                    field_name = field.name
                    if field_name not in input_data:
                        continue
                    
                    value = input_data[field_name]
                    
                    input_vals = {
                        'service_form_field_id': field.id,
                        'sequence': field.sequence,
                        'name': field.name,
                        'label': field.label,
                        'field_type': field.field_type,
                        'required': field.required,
                        'placeholder': field.placeholder,
                    }
                    
                    if field.field_type == 'text':
                        input_vals['value_char'] = value
                    elif field.field_type == 'textarea':
                        input_vals['value_text'] = value
                    elif field.field_type == 'number':
                        input_vals['value_float'] = float(value) if value else 0.0
                    elif field.field_type == 'date':
                        input_vals['value_date'] = normalize_date_input(value)
                    elif field.field_type == 'checkbox':
                        input_vals['value_boolean'] = bool(value)
                    elif field.field_type == 'select':
                        option_ids = value if isinstance(value, list) else [value] if isinstance(value, int) else []
                        if option_ids:
                            input_vals['selected_option_ids'] = [(6, 0, option_ids)]
                    elif field.field_type == 'date_multi':
                        input_record = request.env['student.service.request.input'].sudo().create(input_vals)
                        if isinstance(value, list):
                            for date_str in value:
                                request.env['student.service.request.input.date'].sudo().create({
                                    'input_id': input_record.id,
                                    'date': normalize_date_input(date_str)
                                })
                        input_ids_commands.append((4, input_record.id))
                        continue
                    
                    input_ids_commands.append((0, 0, input_vals))
                
                if input_ids_commands:
                    service_request.sudo().write({'input_ids': input_ids_commands})

            # Nếu có bước đang ở trạng thái 'adjust_profile', chuyển về 'pending' và gửi thông báo
            if current_step:
                current_step = current_step[0]  # Lấy bước đầu tiên
                
                # Sử dụng hàm update_request_step để chuyển trạng thái
                step_vals = update_request_step(
                    request.env, 
                    service_request.id, 
                    current_step.id, 
                    int(request_user_id), 
                    f"Sinh viên đã hoàn thành điều chỉnh hồ sơ: {note}", 
                    'pending',  # Chuyển về trạng thái chờ duyệt
                    None,  # Không gán user cụ thể
                    [], 
                    False,  # Chưa hoàn thành
                    0
                )

                # Áp dụng các giá trị trả về để cập nhật step hiện tại
                if step_vals:
                    current_step.sudo().write(step_vals)

                # Cập nhật trạng thái tổng thể của yêu cầu về 'pending'
                service_request.sudo().write({
                    'final_state': 'pending'
                })

                # Gửi thông báo đến hành chính về việc sinh viên đã hoàn thành điều chỉnh
                admin_profiles = request.env['student.admin.profile'].sudo().search([
                    ('activated', '=', True),
                    ('department_id', '=', current_step.department_id.id if current_step.department_id else False)
                ])
                
                if admin_profiles:
                    admin_user_ids = admin_profiles.mapped('user_id').ids
                    request.env['student.notify'].sudo().create({
                        'title': 'Sinh viên đã hoàn thành điều chỉnh hồ sơ',
                        'body': f'Sinh viên đã hoàn thành điều chỉnh hồ sơ cho yêu cầu "{service_request.name}". Yêu cầu đã trở lại trạng thái chờ duyệt.',
                        'notify_type': 'users',
                        'user_ids': [(6, 0, admin_user_ids)],
                        'data': f'{{"request_id": {service_request.id}, "step_id": {current_step.id}}}'
                    })

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
                    } for att in request_rec.image_attachment_ids],
                    'inputs': [{
                        'name': inp.name,
                        'label': inp.label,
                        'type': inp.field_type,
                        'value_display': inp.value_display,
                    } for inp in service_request.input_ids],
                    'adjustment_completed': bool(current_step),
                    'final_state': service_request.final_state
                }),
                content_type='application/json',
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true')
                ]
            )

        except Exception as e:
            _logger.error(f"Error updating service request: {str(e)}")
            return Response(
                json.dumps({
                    'success': False,
                    'error': str(e),
                }),
                content_type='application/json',
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true')
                ]
            )
    # TODO Lấy các yêu cầu dịch vụ của 1 User có kèm lịch sử duyệt
    @http.route('/api/service/request/user', type='http', auth='public', methods=['GET','OPTIONS'], csrf=False)
    def list_requests_by_user(self):
        if request.httprequest.method == 'OPTIONS':
            return Response(
                status=200,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true'),
                    ('Access-Control-Max-Age', '86400')  # Cache preflight for 24 hours
                ]
            )
        try:
            system_user = request.env['res.users'].sudo().browse(1)
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

            total = request.env['student.service.request'].sudo().with_user(system_user).search_count(domain)
            requests_data = request.env['student.service.request'].sudo().with_user(system_user).search(domain, offset=offset, limit=limit, order='request_date desc')
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
    @http.route('/api/service/request/list', type='http', auth='public', methods=['GET','OPTIONS'], csrf=False)
    def list_service_requests(self, **post):
        if request.httprequest.method == 'OPTIONS':
            return Response(
                status=200,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true'),
                    ('Access-Control-Max-Age', '86400')  # Cache preflight for 24 hours
                ]
            )

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
                # Lấy thông tin số điện thoại của sinh viên từ nhiều nguồn
                student_phone = 'Không có thông tin'
                
                # Debug: Log thông tin user
                import logging
                _logger = logging.getLogger(__name__)
                _logger.info(f"=== DEBUG PHONE FOR USER API - USER ID: {req.request_user_id.id} ===")
                
                # Thử lấy từ student.user.profile trước
                student_profile = request.env['student.user.profile'].sudo().search([('user_id', '=', req.request_user_id.id)], limit=1)
                _logger.info(f"Student profile found: {bool(student_profile)}")
                if student_profile:
                    _logger.info(f"Student profile phone: '{student_profile.phone}'")
                    if student_profile.phone and student_profile.phone != 'None' and student_profile.phone.strip():
                        student_phone = student_profile.phone
                        _logger.info(f"Using student profile phone: {student_phone}")
                
                if student_phone == 'Không có thông tin':
                    # Nếu không có trong profile, thử lấy từ res.users
                    if req.request_user_id and req.request_user_id.phone and req.request_user_id.phone != 'None' and req.request_user_id.phone.strip():
                        student_phone = req.request_user_id.phone
                        _logger.info(f"Using user phone: {student_phone}")
                    elif req.request_user_id and req.request_user_id.mobile and req.request_user_id.mobile != 'None' and req.request_user_id.mobile.strip():
                        student_phone = req.request_user_id.mobile
                        _logger.info(f"Using user mobile: {student_phone}")
                    else:
                        # Thử lấy từ partner
                        if req.request_user_id and req.request_user_id.partner_id:
                            _logger.info(f"Partner phone: '{req.request_user_id.partner_id.phone}', Partner mobile: '{req.request_user_id.partner_id.mobile}'")
                            if req.request_user_id.partner_id.phone and req.request_user_id.partner_id.phone != 'None' and req.request_user_id.partner_id.phone.strip():
                                student_phone = req.request_user_id.partner_id.phone
                                _logger.info(f"Using partner phone: {student_phone}")
                            elif req.request_user_id.partner_id.mobile and req.request_user_id.partner_id.mobile != 'None' and req.request_user_id.partner_id.mobile.strip():
                                student_phone = req.request_user_id.partner_id.mobile
                                _logger.info(f"Using partner mobile: {student_phone}")
                
                _logger.info(f"Final phone result: '{student_phone}'")
                _logger.info("=== END DEBUG PHONE USER API ===")
                
                steps = []
                for step in req.step_ids:
                    steps.append({
                        'id': step.id,
                        'sequence': step.base_secquence or 0,  # Dùng base_secquence làm sequence chính
                        'step_id': step.base_step_id.id if step.base_step_id else None,
                        'step_name': step.display_step_name or '',
                        'step_description': step.base_step_id.description if step.base_step_id else '',
                        'name': step.display_step_name or (step.base_step_id.name if step.base_step_id else ''),
                        
                        # Thông tin từ ServiceStep (base_step_id)
                        'base_step_name': step.base_step_id.name if step.base_step_id else '',
                        'base_step_sequence': step.base_step_id.sequence if step.base_step_id else 0,
                        'base_step_nextstep': step.base_step_id.nextstep if step.base_step_id else 99,
                        'base_step_state': step.base_step_id.state if step.base_step_id else 1,
                        
                        # Thông tin phân công từ ServiceStep
                        'step_user_ids': [{'id': u.id, 'name': u.name} for u in step.base_step_id.user_ids] if step.base_step_id else [],
                        'step_role_ids': [{'id': r.id, 'name': r.name} for r in step.base_step_id.role_ids] if step.base_step_id else [],
                        'step_department_id': step.base_step_id.department_id.id if step.base_step_id and step.base_step_id.department_id else None,
                        'step_department_name': step.base_step_id.department_id.name if step.base_step_id and step.base_step_id.department_id else '',
                        
                        # Trạng thái thực tế của request step
                        'state': step.state,
                        'activated': not step.disabled,  # Ngược lại với disabled
                        'disabled': step.disabled,
                        'approve_content': step.approve_content or '',
                        'approve_date': step.approve_date and step.approve_date.strftime('%Y-%m-%d %H:%M:%S') or '',
                        'final_data': step.final_data or '',
                        
                        # Thông tin phân công thực tế
                        'assign_user_id': step.assign_user_id.id if step.assign_user_id else None,
                        'assign_user_name': step.assign_user_id.name if step.assign_user_id else '',
                        'assigned_department_id': step.department_id.id if step.department_id else None,
                        'assigned_department_name': step.department_id.name if step.department_id else '',
                        
                        # Thông tin selection
                        'selection_id': step.selection_id.id if step.selection_id else None,
                        'selection_name': step.selection_id.name if step.selection_id else '',
                        
                        # File và history
                        'file_ids': [{'id': f.id, 'name': f.name, 'description': f.description} for f in step.file_ids],
                        'file_checkbox_ids': [{'id': f.id, 'name': f.name, 'description': f.description} for f in step.file_checkbox_ids],
                        'history_ids': [
                            {
                                'id': h.id,
                                'state': h.state,
                                'user_id': h.user_id.id if h.user_id else None,
                                'user_name': h.user_id.name if h.user_id else '',
                                'note': h.note,
                                'date': h.date and h.date.strftime('%Y-%m-%d %H:%M:%S') or '',
                            } for h in step.history_ids
                        ],
                    })
                # Sắp xếp các bước theo sequence tăng dần
                steps = sorted(steps, key=lambda x: x['sequence'])
                
                # Debug log để kiểm tra giá trị student_phone
                _logger.info(f"DEBUG RESPONSE: req.id={req.id}, student_phone='{student_phone}', request_user_name='{req.request_user_name}'")
                
                result_item = {
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

                    # Thông tin sinh viên
                    'request_user_name': req.request_user_name,
                    'request_user_phone': student_phone,

                    'service': {
                        'id': req.service_id.id,
                        'name': req.service_id.name,
                        'description': req.service_id.description,
                    } if req.service_id else {},

                    # Thông tin các bước duyệt theo cấu hình dịch vụ
                    'service_step_selection_ids': [{
                        'id': selection.id,
                        'sequence': selection.sequence,
                        'step_id': selection.step_id.id if selection.step_id else None,
                        'step_name': selection.step_name or '',
                        'step_description': selection.step_description or '',
                        'name': selection.name or '',
                        
                        # Thông tin từ ServiceStep (step_id)
                        'base_step_name': selection.step_id.name if selection.step_id else '',
                        'base_step_sequence': selection.step_id.sequence if selection.step_id else 0,
                        'base_step_nextstep': selection.step_id.nextstep if selection.step_id else 99,
                        'base_step_state': selection.step_id.state if selection.step_id else 1,
                        
                        # Thông tin phân công từ ServiceStep
                        'step_user_ids': [{'id': u.id, 'name': u.name} for u in selection.step_id.user_ids] if selection.step_id else [],
                        'step_role_ids': [{'id': r.id, 'name': r.name} for r in selection.step_id.role_ids] if selection.step_id else [],
                        'step_department_id': selection.step_id.department_id.id if selection.step_id and selection.step_id.department_id else None,
                        'step_department_name': selection.step_id.department_id.name if selection.step_id and selection.step_id.department_id else '',
                        
                        # Trạng thái mặc định cho selection (chưa có request step tương ứng)
                        'state': 'pending',  # Trạng thái mặc định
                        'activated': False,  # Chưa kích hoạt
                        'disabled': True,    # Mặc định khóa
                        'approve_content': '',
                        'approve_date': '',
                        'final_data': '',
                        
                        # Thông tin phân công (trống vì chưa có request step)
                        'assign_user_id': None,
                        'assign_user_name': '',
                        'assigned_department_id': None,
                        'assigned_department_name': '',
                        
                        # File và history (trống vì chưa có request step)
                        'file_ids': [],
                        'file_checkbox_ids': [],
                        'history_ids': [],
                    } for selection in req.service_id.step_selection_ids.sorted('sequence')] if req.service_id and req.service_id.step_selection_ids else [],

                    'steps': steps,
                    'is_new': req.is_new
                }
                
                _logger.info(f"DEBUG RESULT ITEM: {result_item}")
                results.append(result_item)
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
    @http.route('/api/service/request/myasigned', type='http', auth='public', methods=['GET','OPTIONS'], csrf=False)
    def get_service_requests_asigned(self, **post):
        if request.httprequest.method == 'OPTIONS':
                return Response(
                    status=200,
                    headers=[
                        ('Access-Control-Allow-Origin', '*'),
                        ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                        ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                        ('Access-Control-Allow-Credentials', 'true'),
                        ('Access-Control-Max-Age', '86400')  # Cache preflight for 24 hours
                    ]
                )
        domain = []
        params = request.httprequest.get_json(force=True, silent=True) or {}
        try:
            user_id = int(request.params.get('user_id') or 0)
            aprofile = request.env['student.admin.profile'].sudo().search([('user_id', '=', user_id)], limit=1) if user_id else None

            domain.append(('user_processing_id', '=', user_id))
            user = request.env['res.users'].sudo().browse(user_id)

            requests = request.env['student.service.request'].sudo().with_user(user).search(domain)

            results = []
            for req in requests:
                # Lấy thông tin số điện thoại của sinh viên từ nhiều nguồn với debug log
                student_phone = 'Không có thông tin'
                
                # Debug: Log thông tin user
                import logging
                _logger = logging.getLogger(__name__)
                _logger.info(f"=== DEBUG PHONE FOR USER ID: {req.request_user_id.id} ===")
                
                # 1. Tìm trong student.user.profile
                student_profile = request.env['student.user.profile'].sudo().search([('user_id', '=', req.request_user_id.id)], limit=1)
                _logger.info(f"Student profile found: {bool(student_profile)}")
                if student_profile:
                    _logger.info(f"Student profile phone: '{student_profile.phone}'")
                    if student_profile.phone and student_profile.phone != 'None' and student_profile.phone.strip():
                        student_phone = student_profile.phone
                        _logger.info(f"Using student profile phone: {student_phone}")
                
                if student_phone == 'Không có thông tin':
                    # 2. Tìm trong res.users -> partner_id -> phone (dùng sudo để tránh lỗi quyền truy cập res.partner)
                    req_user = req.request_user_id.sudo()
                    partner = req_user.partner_id.sudo() if req_user and req_user.partner_id else False
                    _logger.info(f"User found: {bool(req_user)}, Partner found: {bool(partner)}")
                    if partner:
                        _logger.info(f"Partner phone: '{partner.phone}', Partner mobile: '{partner.mobile}'")
                        if partner.phone and partner.phone != 'None' and partner.phone.strip():
                            student_phone = partner.phone
                            _logger.info(f"Using partner phone: {student_phone}")
                        elif partner.mobile and partner.mobile != 'None' and partner.mobile.strip():
                            student_phone = partner.mobile
                            _logger.info(f"Using partner mobile: {student_phone}")
                
                _logger.info(f"Final phone result: '{student_phone}'")
                _logger.info("=== END DEBUG PHONE ===")
                
                # Sắp xếp steps theo base_secquence trước khi xử lý
                sorted_steps = req.step_ids.sorted('base_secquence')
                
                steps = []
                for step in sorted_steps:
                    steps.append({
                        'id': step.id,
                        'sequence': step.base_secquence or 0,  # Dùng base_secquence làm sequence chính
                        'step_id': step.base_step_id.id if step.base_step_id else None,
                        'step_name': step.display_step_name or '',
                        'step_description': step.base_step_id.description if step.base_step_id else '',
                        'name': step.display_step_name or (step.base_step_id.name if step.base_step_id else ''),
                        
                        # Thông tin từ ServiceStep (base_step_id)
                        'base_step_name': step.base_step_id.name if step.base_step_id else '',
                        'base_step_sequence': step.base_step_id.sequence if step.base_step_id else 0,
                        'base_step_nextstep': step.base_step_id.nextstep if step.base_step_id else 99,
                        'base_step_state': step.base_step_id.state if step.base_step_id else 1,
                        
                        # Thông tin phân công từ ServiceStep
                        'step_user_ids': [{'id': u.id, 'name': u.name} for u in step.base_step_id.user_ids] if step.base_step_id else [],
                        'step_role_ids': [{'id': r.id, 'name': r.name} for r in step.base_step_id.role_ids] if step.base_step_id else [],
                        'step_department_id': step.base_step_id.department_id.id if step.base_step_id and step.base_step_id.department_id else None,
                        'step_department_name': step.base_step_id.department_id.name if step.base_step_id and step.base_step_id.department_id else '',
                        
                        # Trạng thái thực tế của request step
                        'state': step.state,
                        'activated': not step.disabled,  # Ngược lại với disabled
                        'disabled': step.disabled,
                        'approve_content': step.approve_content or '',
                        'approve_date': format_datetime_local(step.approve_date, user_id) if step.approve_date else '',
                        'final_data': step.final_data or '',
                        
                        # Thông tin phân công thực tế
                        'assign_user_id': step.assign_user_id.id if step.assign_user_id else None,
                        'assign_user_name': step.assign_user_id.name if step.assign_user_id else '',
                        'assigned_department_id': step.department_id.id if step.department_id else None,
                        'assigned_department_name': step.department_id.name if step.department_id else '',
                        
                        # Thông tin selection
                        'selection_id': step.selection_id.id if step.selection_id else None,
                        'selection_name': step.selection_id.name if step.selection_id else '',
                        
                        # File và history
                        'file_ids': [{'id': f.id, 'name': f.name, 'description': f.description} for f in step.file_ids],
                        'file_checkbox_ids': [{'id': f.id, 'name': f.name, 'description': f.description} for f in step.file_checkbox_ids],
                        'history_ids': [{
                            'id': h.id,
                            'state': h.state,
                            'user_id': h.user_id.id if h.user_id else None,
                            'user_name': h.user_id.name if h.user_id else '',
                            'note': h.note,
                            'date': format_datetime_local(h.date, user_id),
                        } for h in step.history_ids],
                    })
                # Lấy thông tin ký túc xá của sinh viên
                dormitory_info = {
                    'dormitory_full_name': 'Không có thông tin',
                    'dormitory_area': 'Không có thông tin',
                    'dormitory_cluster': 'Không có thông tin',
                    'dormitory_room_id': 'Không có thông tin',
                    'dormitory_room_type': 'Không có thông tin'
                }
                
                # Tìm thông tin ký túc xá từ student.user.profile
                student_profile = request.env['student.user.profile'].sudo().search([('user_id', '=', req.request_user_id.id)], limit=1)
                if student_profile:
                    dormitory_info['dormitory_full_name'] = student_profile.dormitory_full_name or 'Không có thông tin'
                    dormitory_info['dormitory_room_id'] = student_profile.dormitory_room_id or 'Không có thông tin'
                    dormitory_info['dormitory_room_type'] = student_profile.dormitory_room_type_name or 'Không có thông tin'
                    
                    # Lấy thông tin khu và cụm KTX
                    if student_profile.dormitory_cluster_id:
                        cluster = request.env['student.dormitory.cluster'].sudo().browse(student_profile.dormitory_cluster_id)
                        if cluster.exists():
                            dormitory_info['dormitory_cluster'] = cluster.name or 'Không có thông tin'
                            if cluster.area_id:
                                dormitory_info['dormitory_area'] = cluster.area_id.name or 'Không có thông tin'
                # Lấy thông tin input dynamic
                inputs = []
                for input_item in req.input_ids.sorted('sequence'):
                     inputs.append({
                        'name': input_item.name,
                        'label': input_item.label,
                        'value': input_item.value_display or '',
                        'type': input_item.field_type,
                    })

                # Lấy danh sách file đính kèm
                attachments = []
                # 1. Từ field image_attachment_ids
                for att in req.image_attachment_ids:
                    attachments.append({
                        'id': att.id,
                        'name': att.name,
                        'url': f"/web/content/{att.id}",
                        'mimetype': att.mimetype
                    })
                
                # 2. Từ ir.attachment (linked via res_model/res_id) - tránh trùng lặp
                linked_atts = request.env['ir.attachment'].sudo().search([
                    ('res_model', '=', 'student.service.request'),
                    ('res_id', '=', req.id),
                    ('id', 'not in', req.image_attachment_ids.ids)
                ])
                for att in linked_atts:
                    attachments.append({
                        'id': att.id,
                        'name': att.name,
                        'url': f"/web/content/{att.id}",
                        'mimetype': att.mimetype
                    })

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

                    # Thông tin sinh viên
                    'request_user_name': req.request_user_name,
                    'request_user_phone': student_phone,
                    
                    # Thông tin ký túc xá
                    'dormitory': dormitory_info,

                    'service': {
                        'id': req.service_id.id,
                        'name': req.service_id.name,
                        'description': req.service_id.description,
                    } if req.service_id else {},
                    'inputs': inputs,
                    'attachments': attachments,

                 
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
    @http.route('/api/service/request/detail/<int:request_id>', type='http', auth='public', methods=['GET','OPTIONS'], csrf=False)
    def get_service_request_detail(self, request_id):
        if request.httprequest.method == 'OPTIONS':
            return Response(
                status=200,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true'),
                    ('Access-Control-Max-Age', '86400')
                ]
            )

        try:
            sysuser = request.env['res.users'].sudo().browse(1)
            req = request.env['student.service.request'].sudo().with_user(sysuser).browse(request_id)
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

            # Sắp xếp steps theo base_secquence
            sorted_steps = req.step_ids.sorted(lambda s: s.base_secquence or 0)
            
            sumhistories = []
            for step in sorted_steps:
                for h in step.history_ids:
                    sumhistories.append({
                        'id': h.id,
                        'step_id': step.id,
                        'step_name': step.display_step_name or (step.base_step_id.name if step.base_step_id else ''),
                        'state': h.state,
                        'user_id': h.user_id.id if h.user_id else None,
                        'user_name': h.user_id.name if h.user_id else '',
                        'note': h.note,
                        'date': format_datetime_local(h.date),
                    })
            
            # Populate inputs correctly
            inputs = []
            if req.input_ids:
                for inp in req.input_ids.sorted('sequence'):
                    inputs.append({
                        'name': inp.name,
                        'label': inp.label,
                        'type': inp.field_type,
                        'value_display': inp.value_display,
                        'required': inp.required,
                    })

            # Populate attachments
            attachments = []
            if req.image_attachment_ids:
                attachments = req.image_attachment_ids.ids

            req_data = {
                'id': req.id,
                
                # Thông tin service đầy đủ
                'service_id': req.service_id.id if req.service_id else None,
                'service_name': req.service_id.name if req.service_id else '',
                'service_description': req.service_id.description if req.service_id else '',
                
                'name': req.name,
                'note': req.note,
                'inputs': inputs,
                'attachments': attachments,
                
                'image_attachment_ids': [{'id': att.id, 'name': att.name, 'url': att.public_url if hasattr(att, 'public_url') else ''} for att in req.image_attachment_ids],
                'request_date': format_datetime_local(req.request_date),
                'expired_date': format_datetime_local(req.expired_date) if hasattr(req, 'expired_date') and req.expired_date else None,

                'request_user_id': req.request_user_id.id if req.request_user_id else None,
                'request_user_name': req.request_user_id.name if req.request_user_id else '',
                'request_user_phone': req.request_user_phone or '',
                'request_user_dormitory_full': req.request_user_dormitory_full or '',
                'request_user_dormitory_house': req.request_user_dormitory_house or '',
                'request_user_dormitory_room': req.request_user_dormitory_room or '',
                
                # Thông tin người đang xử lý
                'user_processing_id': req.user_processing_id.id if hasattr(req, 'user_processing_id') and req.user_processing_id else None,
                'user_processing_name': req.user_processing_id.name if hasattr(req, 'user_processing_id') and req.user_processing_id else '',
                
                # Thông tin hủy yêu cầu
                'cancel_reason': req.cancel_reason or '',
                'cancel_date': format_datetime_local(req.cancel_date) if req.cancel_date else None,
                'cancel_user_id': req.cancel_user_id.id if req.cancel_user_id else None,
                'cancel_user_name': req.cancel_user_id.name if req.cancel_user_id else '',

                # Service step selections được sắp xếp theo sequence
                'service_step_selection_ids': [{
                    'id': selection.id,
                    'sequence': selection.sequence,
                    'step_id': selection.step_id.id if selection.step_id else None,
                    'step_name': selection.step_name or '',
                    'step_description': selection.step_description or '',
                    'name': selection.name or '',
                    
                    # Thông tin từ ServiceStep (step_id)
                    'base_step_name': selection.step_id.name if selection.step_id else '',
                    'base_step_sequence': selection.step_id.sequence if selection.step_id else 0,
                    'base_step_nextstep': selection.step_id.nextstep if selection.step_id else 99,
                    'base_step_state': selection.step_id.state if selection.step_id else 1,
                    
                    # Thông tin phân công từ ServiceStep
                    'step_user_ids': [{'id': u.id, 'name': u.name} for u in selection.step_id.user_ids] if selection.step_id else [],
                    'step_role_ids': [{'id': r.id, 'name': r.name} for r in selection.step_id.role_ids] if selection.step_id else [],
                    'step_department_id': selection.step_id.department_id.id if selection.step_id and selection.step_id.department_id else None,
                    'step_department_name': selection.step_id.department_id.name if selection.step_id and selection.step_id.department_id else '',
                    
                    # Trạng thái mặc định
                    'state': 'pending', 
                    'activated': False,
                    'disabled': True,
                    'approve_content': '',
                    'approve_date': '',
                    'final_data': '',
                    
                    # Thông tin phân công (trống)
                    'assign_user_id': None,
                    'assign_user_name': '',
                    'assigned_department_id': None,
                    'assigned_department_name': '',
                    
                    # File và history (trống)
                    'file_ids': [],
                    'file_checkbox_ids': [],
                    'history_ids': [],
                } for selection in req.service_id.step_selection_ids.sorted('sequence')] if req.service_id and req.service_id.step_selection_ids else [],

                # Steps được sắp xếp theo base_secquence
                'step_ids': [{
                    'id': step.id,
                    'sequence': step.base_secquence or 0,
                    'step_id': step.base_step_id.id if step.base_step_id else None,
                    'step_name': step.display_step_name or '',
                    'step_description': step.base_step_id.description if step.base_step_id else '',
                    'name': step.display_step_name or (step.base_step_id.name if step.base_step_id else ''),
                    
                    # Thông tin từ ServiceStep
                    'base_step_name': step.base_step_id.name if step.base_step_id else '',
                    'base_step_sequence': step.base_step_id.sequence if step.base_step_id else 0,
                    'base_step_nextstep': step.base_step_id.nextstep if step.base_step_id else 99,
                    'base_step_state': step.base_step_id.state if step.base_step_id else 1,
                    
                    # Thông tin phân công từ ServiceStep
                    'step_user_ids': [{'id': u.id, 'name': u.name} for u in step.base_step_id.user_ids] if step.base_step_id else [],
                    'step_role_ids': [{'id': r.id, 'name': r.name} for r in step.base_step_id.role_ids] if step.base_step_id else [],
                    'step_department_id': step.base_step_id.department_id.id if step.base_step_id and step.base_step_id.department_id else None,
                    'step_department_name': step.base_step_id.department_id.name if step.base_step_id and step.base_step_id.department_id else '',
                    
                    # Trạng thái thực tế
                    'state': step.state,
                    'activated': not step.disabled,
                    'disabled': step.disabled,
                    'approve_content': step.approve_content or '',
                    'approve_date': format_datetime_local(step.approve_date) if step.approve_date else '',
                    'final_data': step.final_data or '',
                    
                    # Thông tin phân công thực tế
                    'assign_user_id': step.assign_user_id.id if step.assign_user_id else None,
                    'assign_user_name': step.assign_user_id.name if step.assign_user_id else '',
                    'assigned_department_id': step.department_id.id if step.department_id else None,
                    'assigned_department_name': step.department_id.name if step.department_id else '',
                    
                    # Thông tin selection
                    'selection_id': step.selection_id.id if step.selection_id else None,
                    'selection_name': step.selection_id.name if step.selection_id else '',
                    
                    # File và history
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
                } for step in sorted_steps],
                
                'users': [{'id': u.id, 'name': u.name} for u in req.users],
                'role_ids': [{'id': r.id, 'name': r.name} for r in req.role_ids],

                'final_state': req.final_state,
                'final_data': req.final_data,
                'final_star': req.final_star or 0,
                'approve_content': req.approve_content,
                'approve_date': format_datetime_local(req.approve_date),
                'approve_user_id': req.approve_user_id.id if req.approve_user_id else None,
                'approve_user_name': req.approve_user_id.name if req.approve_user_id else '',
                
                # Thông tin thống kê và trạng thái
                'is_new': req.is_new,
                'is_expired': req.is_expired if hasattr(req, 'is_expired') else False,
                'send_expired_warning': req.send_expired_warning,
                'expiry_warning_sent': req.expiry_warning_sent,
                'extension_count': req.extension_count if hasattr(req, 'extension_count') else 0,
                'total_extended_hours': req.total_extended_hours if hasattr(req, 'total_extended_hours') else 0,
                
                # Thông tin phản hồi
                'acceptance': req.acceptance or '',
                
                'histories': sumhistories
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
        except Exception as e:
            return Response(
                json.dumps({'success': False, 'message': f'Server Error: {str(e)}', 'data': {}}),
                content_type='application/json',
                status=500,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true')
                ]
            )

    # Lấy danh sách thông báo của user
    @http.route('/api/service/request/approve', type='http', auth='public', methods=['POST','OPTIONS'], csrf=False)
    def approve_service_request(self, **post):
        if request.httprequest.method == 'OPTIONS':
                    return Response(
                        status=200,
                        headers=[
                            ('Access-Control-Allow-Origin', '*'),
                            ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                            ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                            ('Access-Control-Allow-Credentials', 'true'),
                            ('Access-Control-Max-Age', '86400')  # Cache preflight for 24 hours
                        ]
                    )
        
        # Hỗ trợ cả JSON và Form Data (multipart/form-data)
        # Lưu ý: Không dùng force=True cho get_json để tránh lỗi đọc stream khi upload file
        params = request.httprequest.get_json(silent=True) or request.httprequest.form or {}
        
        # Log params để debug
        _logger.info(f"Approve Request Params: {params}")

        try:
            request_id = params.get('request_id')
            user_id = params.get('user_id')
            asign_user_id = int(params.get('asign_user_id', 0) or 0)
            department_id = int(params.get('department_id', 0) or 0)
            step_id = params.get('step_id')
            checked_ids = params.get('checked_ids')
            state = params.get('state', '')
            note = params.get('note', '')
            final = params.get('final', '')
        except Exception as e:
            _logger.error(f"Error parsing params: {e}")
            return Response(
                json.dumps({'success': False, 'message': 'Invalid parameters'}),
                content_type='application/json',
                status=400
            )

        # Xử lý checked_ids nếu là string (do gửi qua Form Data)
        if checked_ids:
            if isinstance(checked_ids, str):
                try:
                    checked_ids = json.loads(checked_ids)
                except:
                    checked_ids = []
            elif isinstance(checked_ids, bool):
                 checked_ids = []
            
            # Ensure list of ints
            if isinstance(checked_ids, list):
                try:
                    checked_ids = [int(x) for x in checked_ids]
                except:
                    checked_ids = []
            else:
                checked_ids = []
        else:
            checked_ids = []

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
                            ('Access-Control-Max-Age', '86400')  # Cache preflight for 24 hours
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
                            ('Access-Control-Max-Age', '86400')  # Cache preflight for 24 hours
                        ]
          )
        sysuser = request.env['res.users'].sudo().browse(1)

        req = request.env['student.service.request'].sudo().with_user(sysuser).browse(int(request_id))
        user = request.env['res.users'].sudo().with_user(sysuser).browse(int(user_id))
        step = request.env['student.service.request.step'].sudo().with_user(sysuser).browse(int(step_id))

        if not req.exists() or not user.exists() or not step.exists():
            return Response(
                json.dumps({'success': False, 'message': 'Request, user, or step not found'}),
                content_type='application/json',
                status=404,
                  headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true')
                ]

            )

        try:
            # Xử lý upload ảnh (nếu có)
            files = request.httprequest.files.getlist('attachment')
            attachment_ids = []
            if files:
                for file_storage in files:
                    file_data = file_storage.read()
                    base64_data = base64.b64encode(file_data).decode('utf-8')
                    attachment = request.env['ir.attachment'].sudo().create({
                        'name': file_storage.filename,
                        'datas': base64_data,
                        'res_model': 'student.service.request',
                        'res_id': req.id,
                        'type': 'binary',
                        'mimetype': file_storage.mimetype or 'application/octet-stream',
                    })
                    attachment_ids.append(attachment.id)
                
                # Cập nhật ảnh vào yêu cầu
                if attachment_ids:
                    req.sudo().with_user(sysuser).write({
                        'image_attachment_ids': [(4, att_id) for att_id in attachment_ids]
                    })

            # Cập nhật bước duyệt
            vals = update_request_step(request.env, int(request_id), int(step_id), int(user_id), note, state, asign_user_id, checked_ids, final, department_id)
            step.sudo().with_user(sysuser).write(vals)
            return Response(
                json.dumps({'success': True, 'message': 'Yêu cầu đã được duyệt', 'data': {'request_id': req.id, 'step_id': step.id, 'user_id': user.id, 'state': state, 'note': note}}),
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
                json.dumps({'success': False, 'message': str(e)}),
                content_type='application/json',
                status=500,
                  headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true')
                ]

            )


    # API: Thống kê yêu cầu dịch vụ
    @http.route('/api/service/request/statistics', type='http', auth='public', methods=['GET','OPT'], csrf=False)
    def get_request_statistics(self, **post):
        if request.httprequest.method == 'OPTIONS':
                return self._handle_options_request()   
        try:
            params = request.params
            user_id = params.get('user_id')
            # Số ngày cảnh báo sắp đến hạn (mặc định 2 ngày)
            warning_days = int(params.get('warning_days', 2))
            
            if not user_id:
                raise ValueError("Thiếu user_id")
            
            # System user
            system_user = request.env['res.users'].sudo().browse(1)

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
            new_requests_count = request.env['student.service.request'].sudo().with_user(system_user).search_count(new_requests_domain)
            new_requests = request.env['student.service.request'].sudo().with_user(system_user).search(new_requests_domain)

            # 2. Thống kê yêu cầu đang xử lý
            processing_domain = base_domain + [
                ('final_state', 'in', ['pending', 'assigned'])
            ]
            processing_count = request.env['student.service.request'].sudo().with_user(system_user).search_count(processing_domain)
            processing_requests = request.env['student.service.request'].sudo().with_user(system_user).search(processing_domain)

            # 3. Thống kê yêu cầu quá hạn
            overdue_domain = base_domain + [
                ('expired_date', '<', now),
                ('final_state', 'in', ['pending', 'assigned'])
            ]
            overdue_count = request.env['student.service.request'].sudo().with_user(system_user).search_count(overdue_domain)
            overdue_requests = request.env['student.service.request'].sudo().with_user(system_user).search(overdue_domain)

            # 4. Thống kê yêu cầu sắp đến hạn (còn lại <= 10% tổng thời gian từ lúc tạo đến hạn)
            warnings_base_domain = base_domain + [
                ('expired_date', '>=', now),
                ('final_state', 'in', ['pending', 'assigned'])
            ]
            candidate_requests = request.env['student.service.request'].sudo().with_user(system_user).search(warnings_base_domain)

            def is_warning(req):
                try:
                    if not req.expired_date:
                        return False
                    start_dt = req.create_date or now
                    total_seconds = (req.expired_date - start_dt).total_seconds()
                    if total_seconds <= 0:
                        return False
                    remaining_seconds = (req.expired_date - now).total_seconds()
                    return 0 < remaining_seconds <= total_seconds * 0.1
                except Exception:
                    return False

            warning_requests = candidate_requests.filtered(is_warning)
            warning_count = len(warning_requests)

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
                    ('Access-Control-Allow-Credentials', 'true')
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
                    ('Access-Control-Allow-Credentials', 'true')
                ]

            )
 # API: Lấy danh sách đánh giá cho yêu cầu dịch vụ
    @http.route('/api/service/request/review/list', type='http', auth='public', methods=['GET'], csrf=False)
    def list_service_request_reviews(self, **kwargs):
        if request.httprequest.method == 'OPTIONS':
                return self._handle_options_request()   
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

    # API: Hủy yêu cầu dịch vụ
    @http.route('/api/service/request/cancel', type='http', auth='public', methods=['POST', 'OPTIONS'], csrf=False)
    def cancel_service_request(self, **post):
        if request.httprequest.method == 'OPTIONS':
            return self._handle_options_request()

        try:
            system_user = request.env['res.users'].sudo().browse(1)
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
                      headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true')
                ]
                )

            # Kiểm tra yêu cầu tồn tại và thuộc về user
            service_request = request.env['student.service.request'].sudo().with_user(system_user).browse(int(request_id))
            if not service_request.exists():
                return Response(
                    json.dumps({
                        'success': False,
                        'message': 'Không tìm thấy yêu cầu'
                    }),
                    content_type='application/json',
                    status=404,
                      headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true')
                ]
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
                      headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true')
                ]
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
                      headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true')
                ]
                )

            # Cập nhật trạng thái yêu cầu thành "cancelled"
            service_request.sudo().with_user(system_user).write({
                'final_state': 'cancelled',
                'cancel_reason': cancel_reason,
                'cancel_date': fields.Datetime.now(),
                'cancel_user_id': int(user_id)
            })

            # Tạo history cho việc hủy yêu cầu
            current_step = service_request.step_ids.filtered(lambda s: s.state in ['pending', 'assigned'])
            if current_step:
                current_step[0].history_ids.sudo().with_user(system_user).create({
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
                  headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true')
                ]
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
                  headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true')
                ]
            )

    # API: Tạo đánh giá cho yêu cầu dịch vụ
    @http.route('/api/service/request/review/create', type='http', auth='public', methods=['POST', 'OPTIONS'], csrf=False)
    def create_service_request_review(self, **post):
        if request.httprequest.method == 'OPTIONS':
              return self._handle_options_request()    
                       
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
                    headers=self._get_cors_headers()
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
            
            # Sau khi đánh giá thành công, tìm step hiện tại đang ở trạng thái 'assigned' và chuyển sang 'approved'
            service_request = review.request_id
            current_step = service_request.step_ids.filtered(lambda s: s.state == 'assigned')
            if current_step:
                current_step = current_step[0]  # Lấy bước hiện tại đang assigned
                # Giữ nguyên người xử lý hiện tại để không mất yêu cầu xử lý
                current_assign_user_id = current_step.assign_user_id.id if current_step.assign_user_id else 0
                # Sử dụng hàm update_request_step để chuyển bước hiện tại từ 'assigned' sang 'approved'
                step_vals = update_request_step(
                    request.env, 
                    service_request.id, 
                    current_step.id, 
                    int(user_id), 
                    f'Đánh giá đã hoàn thành - {comments}', 
                    'approved', 
                    current_assign_user_id,  # nextuserid - giữ nguyên người xử lý hiện tại
                    [],  # docs
                    '',  # final_data
                    0   # department_id
                )
                # Cập nhật step hiện tại với kết quả từ update_request_step
                if step_vals:
                    current_step.sudo().write(step_vals)
            
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
        if request.httprequest.method == 'OPTIONS':
                return self._handle_options_request()
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
    @http.route('/api/service/request/complaint/create', type='http', auth='public', methods=['POST','OPTIONS'], csrf=False)
    def create_service_request_complaint(self, **post):
        if request.httprequest.method == 'OPTIONS':
                        return self._handle_options_request()    
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
            
            # Lấy service request để xử lý trạng thái
            service_request = request.env['student.service.request'].sudo().browse(int(request_id))
            
            # Tìm bước hiện tại đang ở trạng thái 'assigned' để xử lý khiếu nại
            current_step = service_request.step_ids.filtered(lambda s: s.state == 'assigned').sorted('base_secquence', reverse=True)
            if current_step:
                current_step = current_step[0]  # Lấy bước hiện tại đang assigned
                # Giữ nguyên người xử lý hiện tại để không mất yêu cầu xử lý
                current_assign_user_id = current_step.assign_user_id.id if current_step.assign_user_id else 0
                # Sử dụng hàm update_request_step để chuyển bước hiện tại từ 'assigned' sang 'approved'
                step_vals = update_request_step(
                    request.env, 
                    service_request.id, 
                    current_step.id, 
                    int(user_id), 
                    f'Khiếu nại đã được gửi - {content}', 
                    'approved', 
                    current_assign_user_id,  # nextuserid - giữ nguyên người xử lý hiện tại
                    [],  # docs
                    '',  # final_data
                    0   # department_id
                )
                # Cập nhật step hiện tại với kết quả từ update_request_step
                if step_vals:
                    current_step.sudo().write(step_vals)
                # Cập nhật trạng thái yêu cầu thành 'repairing' khi có khiếu nại
                service_request.sudo().write({'final_state': 'approved'})
          
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
            system_user = request.env['res.users'].sudo().browse(1)
            # Lấy dữ liệu từ form
            form = httprequest.form
            request_id = form.get('request_id') 
            accept_user_id = form.get('accept_user_id')
            content = form.get('content', '')       # Nội dung đánh giá
            action = form.get('action', 'issue')    # Hành động 
            stars = int(form.get('star', 0))            # Số sao đánh giá

            service_request = request.env['student.service.request'].sudo().with_user(system_user).browse(int(request_id))
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

            acceptance = request.env['student.service.request.result'].sudo().with_user(system_user).create({
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
                    acceptance.sudo().with_user(system_user).write({'image_ids': [(6, 0, attachment_ids)]})
            except Exception as e:
                pass  # Nếu không tìm thấy user_id thì bỏ qua

            # Cập nhật trạng thái cuối cho yêu cầu dịch vụ
            if action == 'accept':
                service_request.sudo().with_user(system_user).write({'final_state': 'approved', 'final_star': stars })
                send_fcm_request(request.env, service_request, 10)  # Gửi thông báo nghiệm thu từ SV 
                
                # Ưu tiên phê duyệt lại bước bị từ chối gần nhất, nếu có; nếu không sẽ phê duyệt bước đang assigned
                rejected_steps = service_request.step_ids.filtered(lambda s: s.state == 'rejected').sorted('base_secquence', reverse=True)
                assigned_steps = service_request.step_ids.filtered(lambda s: s.state == 'assigned').sorted('base_secquence', reverse=True)
                target_step = False
                if rejected_steps:
                    target_step = rejected_steps[0]
                elif assigned_steps:
                    target_step = assigned_steps[0]
                
                if target_step:
                    # Giữ nguyên người xử lý hiện tại để không mất yêu cầu xử lý
                    current_assign_user_id = target_step.assign_user_id.id if target_step.assign_user_id else 0
                    # Nếu thiếu accept_user_id thì dùng system_user để bảo đảm có người duyệt
                    _accept_uid = int(accept_user_id) if accept_user_id else int(system_user.id)
                    # Sử dụng hàm update_request_step để chuyển bước mục tiêu sang 'approved'
                    step_vals = update_request_step(
                        request.env, 
                        service_request.id, 
                        target_step.id, 
                        _accept_uid, 
                        f'Nghiệm thu đã được chấp nhận - {content}', 
                        'approved', 
                        current_assign_user_id,  # nextuserid - giữ nguyên người xử lý hiện tại
                        [],  # docs
                        '',  # final_data
                        0   # department_id
                    )
                    # Cập nhật step mục tiêu với kết quả từ update_request_step
                    if step_vals:
                        target_step.sudo().write(step_vals)
                
                # Kiểm tra đã có nghiệm thu accept của Admin thì duyệt yêu cầu
                # Lấy nghiệm thu của User khác
                other_acceptance = request.env['student.service.request.result'].sudo().with_user(system_user).search([
                    ('request_id', '=', service_request.id),
                    ('action_user', '!=', service_request.request_user_id.id)
                ], order='timestamp desc', limit=1)
                if other_acceptance and other_acceptance.action == 'accept':
                    service_request.sudo().with_user(system_user).write({'final_state': 'approved', 'final_star': stars})
                    send_fcm_request(request.env, service_request, 10)  # Gửi thông báo nghiệm thu từ Admin

            elif action == 'reject' or action == 'issue':
                # Tìm bước trước đó để quay lại
                current_step = service_request.step_ids.filtered(lambda s: s.state == 'assigned').sorted('base_secquence', reverse=True)
                if current_step:
                    current_step = current_step[0]  # Lấy bước hiện tại đang assigned
                    
                    # Tìm bước trước đó
                    previous_step = service_request.step_ids.filtered(
                        lambda s: s.base_secquence < current_step.base_secquence and s.state in ['approved', 'ignored']
                    ).sorted('base_secquence', reverse=True)
                    
                    if previous_step:
                        previous_step = previous_step[0]  # Lấy bước trước đó gần nhất
                        
                        # Đặt lại bước trước đó thành trạng thái assigned để xử lý lại
                        previous_step.sudo().with_user(system_user).write({
                            'state': 'assigned',
                            'approve_content': f'Quay lại xử lý do nghiệm thu từ chối - {content}',
                            'approve_date': Datetime.now(),
                        })
                        
                        # Đặt bước hiện tại thành rejected
                        current_step.sudo().with_user(system_user).write({
                            'state': 'rejected',
                            'approve_content': f'Nghiệm thu từ chối - {content}',
                            'approve_date': Datetime.now(),
                        })
                        
                        # Cập nhật trạng thái tổng thể
                        service_request.sudo().with_user(system_user).write({
                            'final_state': 'assigned',  # Quay lại trạng thái đang xử lý
                            'final_star': stars
                        })
                    else:
                        # Nếu không có bước trước đó, đặt bước đầu tiên thành pending
                        first_step = service_request.step_ids.filtered(lambda s: s.base_secquence == 1)
                        if first_step:
                            first_step.sudo().with_user(system_user).write({
                                'state': 'pending',
                                'approve_content': f'Quay lại bước đầu do nghiệm thu từ chối - {content}',
                                'approve_date': Datetime.now(),
                            })
                        
                        service_request.sudo().with_user(system_user).write({
                            'final_state': 'pending',
                            'final_star': stars
                        })
                else:
                    # Fallback: nếu không tìm thấy bước hiện tại, giữ nguyên logic cũ
                    service_request.sudo().with_user(system_user).write({'final_state': 'repairing', 'final_star': stars})
                
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
 
    @http.route('/api/service/request/acceptance/list', type='http', auth='public', methods=['GET','OPTIONS'], csrf=False)
    def list_service_request_acceptances(self, **kwargs):    
        if request.httprequest.method == 'OPTIONS':
                    return Response(
                        status=200,
                        headers=[
                            ('Access-Control-Allow-Origin', '*'),
                            ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                            ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                            ('Access-Control-Allow-Credentials', 'true'),
                            ('Access-Control-Max-Age', '86400'),  # Cache preflight for 24 hours
                        ]
                    )
        try:
             # Lấy tham số lọc và phân trang
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

            system_user = request.env['res.users'].sudo().browse(1)
            # Tính total và offset
            total = request.env['student.service.request.result'].sudo().with_user(system_user).search_count(domain)
            offset = (page - 1) * limit

            # Lấy danh sách nghiệm thu
            acceptances = request.env['student.service.request.result'].sudo().with_user(system_user).search(
                domain, 
                offset=offset, 
                limit=limit, 
                order='timestamp desc'
            )

            result = []
            for acceptance in acceptances:
                # Ensure all related field access uses sudo()
                request_record = acceptance.request_id.sudo() if acceptance.request_id else None
                service_record = request_record.service_id.sudo() if request_record and request_record.service_id else None
                user_record = acceptance.user_id.sudo() if acceptance.user_id else None
                action_user_record = acceptance.action_user.sudo() if acceptance.action_user else None
                
                result.append({
                    'id': acceptance.id,
                    'request_id': request_record.id if request_record else None,
                    'request_name': request_record.name if request_record else '',
                    'service_name': service_record.name if service_record else '',
                    
                    'user_id': user_record.id if user_record else None,
                    'user_name': user_record.name if user_record else '',
                    
                    'action_user': action_user_record.id if action_user_record else None,
                    'action_user_name': action_user_record.name if action_user_record else '',
                    
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
                        'final_state': request_record.final_state if request_record else '',
                        'final_star': request_record.final_star if request_record else 0,
                        'request_date': format_datetime_local(request_record.request_date) if request_record else '',
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
            
    @http.route('/api/service/request/images', type='http', auth='public', methods=['GET','OPTIONS'], csrf=False)
    def get_request_images(self):
        try:
            if request.httprequest.method == 'OPTIONS':
                    return Response(
                        status=200,
                        headers=[
                            ('Access-Control-Allow-Origin', '*'),
                            ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                            ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                            ('Access-Control-Allow-Credentials', 'true'),
                            ('Access-Control-Max-Age', '86400'),  # Cache preflight for 24 hours
                        ]
                    )
             # Lấy request_id từ tham số
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

    @http.route('/api/download/image/<int:attachment_id>', type='http', auth='public', methods=['GET','OPTIONS'], csrf=False)
    def download_image(self, attachment_id):
        try:
            if request.httprequest.method == 'OPTIONS':
                    return Response(
                        status=200,
                        headers=[
                            ('Access-Control-Allow-Origin', '*'),
                            ('Access-Control-Allow-Methods', 'GET, OPTIONS'),
                            ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                            ('Access-Control-Allow-Credentials', 'true'),
                            ('Access-Control-Max-Age', '86400'),  # Cache preflight for 24 hours
                        ]
                    )
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

    # API: Xử lý khi sinh viên hoàn thành điều chỉnh hồ sơ
    @http.route('/api/service/request/profile_adjustment_complete', type='http', auth='public', methods=['POST', 'OPTIONS'], csrf=False)
    def complete_profile_adjustment(self, **post):
        if request.httprequest.method == 'OPTIONS':
            return Response(
                status=200,
                headers=[
                    ('Access-Control-Allow-Origin', '*'),
                    ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                    ('Access-Control-Allow-Headers', 'Content-Type, Authorization'),
                    ('Access-Control-Allow-Credentials', 'true'),
                    ('Access-Control-Max-Age', '86400')  # Cache preflight for 24 hours
                ]
            )

        try:
            params = request.httprequest.get_json(force=True, silent=True) or {}
            request_id = params.get('request_id')
            user_id = params.get('user_id')
            note = params.get('note', 'Sinh viên đã hoàn thành điều chỉnh hồ sơ')

            if not request_id:
                return Response(
                    json.dumps({
                        'success': False,
                        'message': 'Thiếu request_id'
                    }),
                    content_type='application/json',
                    status=400,
                    headers=self._get_cors_headers()
                )

            if not user_id:
                return Response(
                    json.dumps({
                        'success': False,
                        'message': 'Thiếu user_id'
                    }),
                    content_type='application/json',
                    status=400,
                    headers=self._get_cors_headers()
                )

            # Tìm yêu cầu dịch vụ với sudo() để tránh lỗi quyền
            service_request = request.env['student.service.request'].sudo().browse(int(request_id))
            if not service_request.exists():
                return Response(
                    json.dumps({
                        'success': False,
                        'message': 'Yêu cầu không tồn tại'
                    }),
                    content_type='application/json',
                    status=404,
                    headers=self._get_cors_headers()
                )

            # Kiểm tra quyền: chỉ sinh viên tạo yêu cầu mới được thực hiện
            # Sử dụng sudo() để truy cập request_user_id
            if service_request.sudo().request_user_id.id != int(user_id):
                return Response(
                    json.dumps({
                        'success': False,
                        'message': 'Không có quyền thực hiện thao tác này'
                    }),
                    content_type='application/json',
                    status=403,
                    headers=self._get_cors_headers()
                )

            # Tìm step hiện tại đang ở trạng thái 'adjust_profile' với sudo()
            current_step = service_request.step_ids.sudo().filtered(lambda s: s.state == 'adjust_profile')
            if not current_step:
                return Response(
                    json.dumps({
                        'success': False,
                        'message': 'Không tìm thấy bước điều chỉnh hồ sơ'
                    }),
                    content_type='application/json',
                    status=400,
                    headers=self._get_cors_headers()
                )

            current_step = current_step[0]  # Lấy bước hiện tại

            # Sử dụng hàm update_request_step để chuyển bước hiện tại từ 'adjust_profile' sang 'pending'
            step_vals = update_request_step(
                request.env, 
                service_request.id, 
                current_step.id, 
                int(user_id), 
                note, 
                'pending',  # Chuyển về trạng thái chờ duyệt
                None,  # Không gán user cụ thể
                [], 
                False,  # Chưa hoàn thành
                0
            )

            # Áp dụng các giá trị trả về để cập nhật step hiện tại
            if step_vals:
                current_step.sudo().write(step_vals)

            # Cập nhật trạng thái tổng thể của yêu cầu về 'pending'
            service_request.sudo().write({
                'final_state': 'pending'
            })

            # Gửi thông báo đến hành chính về việc sinh viên đã hoàn thành điều chỉnh
            # Tìm các admin có quyền duyệt yêu cầu này
            admin_profiles = request.env['student.admin.profile'].sudo().search([
                ('activated', '=', True),
                ('department_id', '=', current_step.department_id.id if current_step.department_id else False)
            ])
            
            if admin_profiles:
                admin_user_ids = admin_profiles.mapped('user_id').ids
                request.env['student.notify'].sudo().create({
                    'title': 'Sinh viên đã hoàn thành điều chỉnh hồ sơ',
                    'body': f'Sinh viên đã hoàn thành điều chỉnh hồ sơ cho yêu cầu "{service_request.name}". Yêu cầu đã trở lại trạng thái chờ duyệt.',
                    'notify_type': 'users',
                    'user_ids': [(6, 0, admin_user_ids)],
                    'data': f'{{"request_id": {service_request.id}, "step_id": {current_step.id}}}'
                })

            return Response(
                json.dumps({
                    'success': True,
                    'message': 'Đã hoàn thành điều chỉnh hồ sơ. Yêu cầu đã trở lại trạng thái chờ duyệt.',
                    'data': {
                        'request_id': service_request.id,
                        'final_state': 'pending'
                    }
                }),
                content_type='application/json',
                status=200,
                headers=self._get_cors_headers()
            )

        except Exception as e:
            _logger.error(f"Error completing profile adjustment: {str(e)}")
            return Response(
                json.dumps({
                    'success': False,
                    'message': f'Lỗi hệ thống: {str(e)}'
                }),
                content_type='application/json',
                status=500,
                headers=self._get_cors_headers()
            )
        
    @http.route('/api/service/request/extension/create', type='http', auth='public', methods=['POST', 'OPTIONS'], csrf=False)
    def create_request_extension(self, **post):
        """API gửi yêu cầu gia hạn"""
        if request.httprequest.method == 'OPTIONS':
            return self._handle_options_request()

        try:
            # Lấy dữ liệu
            data = json.loads(request.httprequest.data.decode('utf-8'))
            request_id = data.get('request_id')
            hours = data.get('hours', 0)
            reason = data.get('reason', '').strip()
            user_id = data.get('user_id')  # Thêm user_id từ request body

            # Validate dữ liệu cơ bản
            if not request_id or hours <= 0 or hours > 720 or not reason:
                return Response(json.dumps({'success': False, 'message': 'Dữ liệu không hợp lệ'}),
                              content_type='application/json', status=400, headers=self._get_cors_headers())

            # Xác định user_id để sử dụng
            if user_id:
                # Kiểm tra user_id có tồn tại không
                user = request.env['res.users'].sudo().browse(user_id)
                if not user.exists():
                    return Response(json.dumps({'success': False, 'message': f'Không tìm thấy user với ID: {user_id}'}),
                                  content_type='application/json', status=404, headers=self._get_cors_headers())
                requested_by_id = user_id
            else:
                # Sử dụng user hiện tại nếu không có user_id trong request
                requested_by_id = request.env.user.id

            # Kiểm tra yêu cầu tồn tại (sử dụng sudo để bypass record rules)
            # service_request = request.env['student.service.request'].sudo().browse(request_id)
            # if not service_request.sudo().exists():
            #     return Response(json.dumps({'success': False, 'message': 'Yêu cầu không tồn tại'}),
            #                   content_type='application/json', status=404, headers=self._get_cors_headers())

            # Tạo gia hạn với trạng thái 'submitted' ngay từ đầu để tránh lỗi quyền truy cập
            extension = request.env['request.extension'].sudo().with_context(
                mail_create_nolog=True,
                mail_create_nosubscribe=True,
                tracking_disable=True
            ).create({
                'request_id': request_id,
                'hours': hours,
                'reason': reason,
                'requested_by': requested_by_id,
                'state': 'submitted',  # Tạo trực tiếp với trạng thái submitted
            })

            # Lấy thông tin người gửi yêu cầu
            requester_info = {
                'id': extension.requested_by.id,
                'name': extension.requested_by.name,
                'email': extension.requested_by.email or '',
                'phone': extension.requested_by.phone or '',
                'login': extension.requested_by.login or ''
            }

            # Gửi FCM notification
            try:
                # Lấy thông tin yêu cầu gốc để gửi thông báo
                service_request = request.env['student.service.request'].sudo().browse(request_id)
                
                if service_request.exists():
                    # Data cho FCM notification
                    fcm_data = {
                        'type': 'extension',
                        'extension_id': str(extension.id),
                        'request_id': str(request_id),
                        'hours': str(hours)
                    }
                    
                    # 1. Gửi thông báo cho người gửi yêu cầu gia hạn (xác nhận đã gửi)
                    send_fcm_users(
                        request.env,
                        [extension.requested_by.id],
                        f'Đã gửi yêu cầu gia hạn {hours} giờ',
                        f'Yêu cầu gia hạn {hours} giờ cho dịch vụ "{service_request.service_id.name}" đã được gửi thành công. Lý do: {reason}',
                        fcm_data
                    )
                    
                    # 2. Gửi thông báo cho người tạo yêu cầu gốc (nếu khác người gửi gia hạn)
                    if service_request.request_user_id.id != extension.requested_by.id:
                        send_fcm_users(
                            request.env,
                            [service_request.request_user_id.id],
                            f'Có yêu cầu gia hạn {hours} giờ',
                            f'Yêu cầu dịch vụ "{service_request.service_id.name}" của bạn có yêu cầu gia hạn {hours} giờ. Lý do: {reason}',
                            fcm_data
                        )
                    
                    # 3. Gửi thông báo cho các admin/người được giao xử lý yêu cầu
                    # Lấy danh sách user được giao xử lý từ service và các bước
                    admin_user_ids = []
                    
                    # Từ service configuration
                    if service_request.service_id and service_request.service_id.users:
                        admin_user_ids.extend(service_request.service_id.users.ids)
                    
                    # Từ các bước đang xử lý
                    current_steps = service_request.step_ids.filtered(lambda s: s.state in ['pending', 'processing'])
                    for step in current_steps:
                        if step.assign_user_id:
                            admin_user_ids.append(step.assign_user_id.id)
                    
                    # Loại bỏ trùng lặp và gửi thông báo
                    admin_user_ids = list(set(admin_user_ids))
                    if admin_user_ids:
                        send_fcm_users(
                            request.env,
                            admin_user_ids,
                            f'Yêu cầu gia hạn dịch vụ {service_request.service_id.name}',
                            f'Có yêu cầu gia hạn {hours} giờ từ {extension.requested_by.name} cho dịch vụ "{service_request.service_id.name}". Lý do: {reason}',
                            fcm_data
                        )
                        
            except Exception as fcm_error:
                # Log lỗi FCM nhưng không làm fail API
                _logger.warning(f'Lỗi gửi FCM notification cho extension {extension.id}: {str(fcm_error)}')

            return Response(json.dumps({
                'success': True,
                'message': f'Đã gửi yêu cầu gia hạn {hours} giờ',
                'data': {
                    'extension_id': extension.id, 
                    'hours': hours,
                    'user_id': extension.requested_by.id,  # Thêm user_id riêng biệt
                    'requester': requester_info,
                    'request_date': extension.request_date.strftime('%Y-%m-%d %H:%M:%S') if extension.request_date else None
                }
            }), content_type='application/json', status=201, headers=self._get_cors_headers())

        except Exception as e:
            return Response(json.dumps({'success': False, 'message': f'Lỗi: {str(e)}'}),
                          content_type='application/json', status=500, headers=self._get_cors_headers())

    @http.route('/api/service/request/extension/<int:extension_id>', type='http', auth='public', methods=['GET', 'OPTIONS'], csrf=False)
    def get_request_extension(self, extension_id, **kwargs):
        """API lấy thông tin chi tiết yêu cầu gia hạn theo ID"""
        if request.httprequest.method == 'OPTIONS':
            return self._handle_options_request()

        try:
            # Tìm yêu cầu gia hạn
            extension = request.env['request.extension'].sudo().browse(extension_id)
            if not extension.exists():
                return Response(json.dumps({'success': False, 'message': 'Không tìm thấy yêu cầu gia hạn'}),
                              content_type='application/json', status=404, headers=self._get_cors_headers())

            # Thông tin người gửi yêu cầu
            requester_info = {
                'id': extension.requested_by.id,
                'name': extension.requested_by.name,
                'email': extension.requested_by.email or '',
                'phone': extension.requested_by.phone or '',
                'login': extension.requested_by.login or ''
            }

            # Thông tin người duyệt (nếu có)
            approver_info = None
            if extension.approved_by:
                approver_info = {
                    'id': extension.approved_by.id,
                    'name': extension.approved_by.name,
                    'email': extension.approved_by.email or '',
                    'login': extension.approved_by.login or ''
                }

            # Thông tin yêu cầu dịch vụ
            service_request_info = {
                'id': extension.request_id.id,
                'name': extension.request_id.name,
                'service_name': extension.request_id.service_id.name if extension.request_id.service_id else '',
                'current_deadline': extension.request_id.expired_date.strftime('%Y-%m-%d %H:%M:%S') if extension.request_id.expired_date else None,
                'state': extension.request_id.state
            }

            extension_data = {
                'id': extension.id,
                'name': extension.name,
                'hours': extension.hours,
                'reason': extension.reason,
                'state': extension.state,
                'user_id': extension.requested_by.id,  # Thêm user_id riêng biệt
                'request_date': extension.request_date.strftime('%Y-%m-%d %H:%M:%S') if extension.request_date else None,
                'approval_date': extension.approval_date.strftime('%Y-%m-%d %H:%M:%S') if extension.approval_date else None,
                'rejection_date': extension.rejection_date.strftime('%Y-%m-%d %H:%M:%S') if extension.rejection_date else None,
                'rejection_reason': extension.rejection_reason or '',
                'original_deadline': extension.original_deadline.strftime('%Y-%m-%d %H:%M:%S') if extension.original_deadline else None,
                'new_deadline': extension.new_deadline.strftime('%Y-%m-%d %H:%M:%S') if extension.new_deadline else None,
                'requester': requester_info,
                'approver': approver_info,
                'service_request': service_request_info
            }

            return Response(json.dumps({
                'success': True,
                'data': extension_data
            }), content_type='application/json', headers=self._get_cors_headers())

        except Exception as e:
            return Response(json.dumps({'success': False, 'message': f'Lỗi: {str(e)}'}),
                          content_type='application/json', status=500, headers=self._get_cors_headers())

    @http.route('/api/service/request/extension/list', type='http', auth='public', methods=['GET', 'OPTIONS'], csrf=False)
    def list_request_extensions(self, **kwargs):
        """API lấy danh sách yêu cầu gia hạn với thông tin người gửi"""
        if request.httprequest.method == 'OPTIONS':
            return self._handle_options_request()

        try:
            # Lấy parameters
            request_id = kwargs.get('request_id')
            state = kwargs.get('state')  # draft, submitted, approved, rejected
            limit = int(kwargs.get('limit', 50))
            offset = int(kwargs.get('offset', 0))

            # Tạo domain filter
            domain = []
            if request_id:
                domain.append(('request_id', '=', int(request_id)))
            if state:
                domain.append(('state', '=', state))

            # Lấy danh sách yêu cầu gia hạn
            extensions = request.env['request.extension'].sudo().search(
                domain, 
                limit=limit, 
                offset=offset, 
                order='create_date desc'
            )

            # Chuẩn bị dữ liệu response
            extension_list = []
            for ext in extensions:
                # Thông tin người gửi yêu cầu
                requester_info = {
                    'id': ext.requested_by.id,
                    'name': ext.requested_by.name,
                    'email': ext.requested_by.email or '',
                    'phone': ext.requested_by.phone or '',
                    'login': ext.requested_by.login or ''
                }

                # Thông tin người duyệt (nếu có)
                approver_info = None
                if ext.approved_by:
                    approver_info = {
                        'id': ext.approved_by.id,
                        'name': ext.approved_by.name,
                        'email': ext.approved_by.email or '',
                        'login': ext.approved_by.login or ''
                    }

                # Thông tin yêu cầu dịch vụ
                service_request_info = {
                    'id': ext.request_id.id,
                    'name': ext.request_id.name,
                    'service_name': ext.request_id.service_id.name if ext.request_id.service_id else '',
                    'current_deadline': ext.request_id.expired_date.strftime('%Y-%m-%d %H:%M:%S') if ext.request_id.expired_date else None
                }

                extension_data = {
                    'id': ext.id,
                    'name': ext.name,
                    'hours': ext.hours,
                    'reason': ext.reason,
                    'state': ext.state,
                    'user_id': ext.requested_by.id,  # Thêm user_id riêng biệt
                    'request_date': ext.request_date.strftime('%Y-%m-%d %H:%M:%S') if ext.request_date else None,
                    'approval_date': ext.approval_date.strftime('%Y-%m-%d %H:%M:%S') if ext.approval_date else None,
                    'rejection_date': ext.rejection_date.strftime('%Y-%m-%d %H:%M:%S') if ext.rejection_date else None,
                    'rejection_reason': ext.rejection_reason or '',
                    'original_deadline': ext.original_deadline.strftime('%Y-%m-%d %H:%M:%S') if ext.original_deadline else None,
                    'new_deadline': ext.new_deadline.strftime('%Y-%m-%d %H:%M:%S') if ext.new_deadline else None,
                    'requester': requester_info,
                    'approver': approver_info,
                    'service_request': service_request_info
                }
                extension_list.append(extension_data)

            # Đếm tổng số records
            total_count = request.env['request.extension'].sudo().search_count(domain)

            return Response(json.dumps({
                'success': True,
                'data': extension_list,
                'total': total_count,
                'limit': limit,
                'offset': offset
            }), content_type='application/json', headers=self._get_cors_headers())

        except Exception as e:
            return Response(json.dumps({'success': False, 'message': f'Lỗi: {str(e)}'}),
                          content_type='application/json', status=500, headers=self._get_cors_headers())
