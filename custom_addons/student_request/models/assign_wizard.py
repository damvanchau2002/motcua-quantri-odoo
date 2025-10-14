from odoo import models, fields, api
from odoo.exceptions import ValidationError
from ..controllers.service_api.request_api import update_request_step


class StudentRequestBulkAssignWizard(models.TransientModel):
    _name = 'student.request.bulk.assign.wizard'
    _description = 'Phân công hàng loạt yêu cầu dịch vụ'

    # Chọn đối tượng phân công
    assign_user_id = fields.Many2one('res.users', string='Người được phân công', help='Người sẽ xử lý tiếp theo bước này')
    department_id = fields.Many2one('student.activity.department', string='Phòng ban được phân công')
    note = fields.Char(string='Ghi chú', default='Phân công hàng loạt')

    # Bộ lọc cho phần "Phân công theo dịch vụ" (giữ tối giản)
    service_id = fields.Many2one('student.service', string='Dịch vụ')
    step_state = fields.Selection([('pending', 'Chờ xử lý'), ('assigned', 'Đã phân công')], string='Trạng thái xử lý', default='pending')
    only_unassigned = fields.Boolean('Chỉ lấy yêu cầu chưa có người xử lý', default=True)

    # Danh sách yêu cầu xem trước và phân công theo dịch vụ (dạng dòng có tick chọn)
    line_ids = fields.One2many('student.request.bulk.assign.line', 'wizard_id', string='Danh sách yêu cầu')
    request_count = fields.Integer('Số lượng đã chọn', compute='_compute_request_count', store=False)

    # Danh sách yêu cầu chọn tay cho phần "Phân công theo yêu cầu"
    request_ids = fields.Many2many('student.service.request', string='Yêu cầu dịch vụ (chọn tay)')

    # Danh sách user cho phép phân công: admin đã kích hoạt + nhóm quyền xử lý
    assignable_user_ids = fields.Many2many('res.users', compute='_compute_assignable_user_ids', store=False)

    def _compute_assignable_user_ids(self):
        final_users = self._get_assignable_users()
        for w in self:
            w.assignable_user_ids = [(6, 0, final_users.ids)]

    def _get_assignable_users(self):
        # Admin đã kích hoạt
        admin_users = self.env['student.admin.profile'].sudo().search([
            ('activated', '=', True)
        ]).mapped('user_id')

        # Thu hẹp tiếp: chỉ những user thuộc nhóm quyền xử lý
        group_user = self.env.ref('student_request.group_student_request_user', raise_if_not_found=False)
        group_manager = self.env.ref('student_request.group_student_request_manager', raise_if_not_found=False)
        group_ids = [g.id for g in (group_user, group_manager) if g]
        if group_ids:
            group_users = self.env['res.users'].sudo().search([('groups_id', 'in', group_ids)])
            eligible_users = admin_users & group_users
        else:
            eligible_users = admin_users

        # Loại toàn bộ sinh viên
        student_users = self.env['student.user.profile'].sudo().search([]).mapped('user_id')
        final_users = eligible_users - student_users
        return final_users

    @api.model
    def default_get(self, fields_list):
        # Đảm bảo assignable_user_ids có giá trị ngay khi mở form
        res = super().default_get(fields_list)
        users = self._get_assignable_users()
        res['assignable_user_ids'] = [(6, 0, users.ids)]
        return res

    @api.depends('line_ids', 'line_ids.selected')
    def _compute_request_count(self):
        for w in self:
            w.request_count = len(w.line_ids.filtered(lambda l: l.selected))

    @api.model
    def _check_same_service(self, requests):
        service_ids = requests.mapped('service_id.id')
        return len(set(service_ids)) <= 1

    def action_load_requests_by_service(self):
        """Tải danh sách yêu cầu theo dịch vụ vào line_ids với tick chọn."""
        domain = []
        if self.service_id:
            domain.append(('service_id', '=', self.service_id.id))
        # Lọc theo trạng thái tổng quát của yêu cầu
        if self.step_state:
            domain.append(('final_state', '=', self.step_state))
        # Chỉ lấy yêu cầu chưa có người xử lý
        if self.only_unassigned:
            domain.append(('user_processing_id', '=', False))

        requests = self.env['student.service.request'].search(domain)
        # Xóa danh sách cũ và nạp lại các dòng mới, mặc định chọn hết
        self.line_ids.unlink()
        lines = [(0, 0, {
            'request_id': r.id,
            'selected': True,
        }) for r in requests]
        if lines:
            self.write({'line_ids': lines})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Đã tải danh sách',
                'message': f'Đã nạp {len(requests)} yêu cầu. Bạn có thể tích chọn để phân công.',
                'type': 'success',
            }
        }

    def action_clear_requests_by_service(self):
        # Xóa toàn bộ dòng xem trước (theo dịch vụ)
        self.line_ids.unlink()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Đã xóa danh sách',
                'message': 'Danh sách yêu cầu xem trước đã được xóa',
                'type': 'warning',
            }
        }

    def action_select_all(self):
        self.line_ids.write({'selected': True})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Đã chọn tất cả',
                'message': 'Toàn bộ yêu cầu đã được tích chọn.',
                'type': 'success',
            }
        }

    def action_deselect_all(self):
        self.line_ids.write({'selected': False})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Đã bỏ chọn tất cả',
                'message': 'Toàn bộ yêu cầu đã bỏ tích chọn.',
                'type': 'warning',
            }
        }

    def action_assign_by_service(self):
        active_ids = self.env.context.get('active_ids') or []
        # Nếu không có context active_ids, lấy theo các dòng được tích chọn
        selected_ids = active_ids or self.line_ids.filtered(lambda l: l.selected).mapped('request_id.id')
        if not selected_ids:
            raise ValidationError('Vui lòng tích chọn các yêu cầu dịch vụ để phân công (theo dịch vụ).')

        requests = self.env['student.service.request'].browse(selected_ids)

        # Theo dịch vụ: yêu cầu cùng dịch vụ để đảm bảo nhất quán
        if not self._check_same_service(requests):
            raise ValidationError('Chỉ phân công các yêu cầu thuộc cùng một dịch vụ (theo dịch vụ).')

        if not (self.assign_user_id or self.department_id):
            raise ValidationError('Vui lòng chọn Người được phân công hoặc Phòng ban.')

        for req in requests:
            step = req.step_ids.filtered(lambda s: s.state in ('pending', 'assigned')).sorted('base_secquence')
            if not step:
                continue
            step = step[0]

            next_user_id = self.assign_user_id.id if self.assign_user_id else 0
            department_id = self.department_id.id if self.department_id else 0

            vals = update_request_step(
                self.env,
                req.id,
                step.id,
                self.env.user.id,
                self.note or '',
                'assigned',
                next_user_id,
                step.file_checkbox_ids.ids,
                req.final_data or '',
                department_id
            )

            if isinstance(vals, dict):
                step.write(vals)

        return {'type': 'ir.actions.act_window_close'}

    def action_assign_by_requests(self):
        # Phân công theo danh sách yêu cầu chọn tay, không bắt buộc cùng dịch vụ
        selected_ids = self.request_ids.ids
        if not selected_ids:
            raise ValidationError('Vui lòng chọn các yêu cầu dịch vụ để phân công (theo yêu cầu).')

        if not (self.assign_user_id or self.department_id):
            raise ValidationError('Vui lòng chọn Người được phân công hoặc Phòng ban.')

        requests = self.env['student.service.request'].browse(selected_ids)
        for req in requests:
            step = req.step_ids.filtered(lambda s: s.state in ('pending', 'assigned')).sorted('base_secquence')
            if not step:
                continue
            step = step[0]

            next_user_id = self.assign_user_id.id if self.assign_user_id else 0
            department_id = self.department_id.id if self.department_id else 0

            vals = update_request_step(
                self.env,
                req.id,
                step.id,
                self.env.user.id,
                self.note or '',
                'assigned',
                next_user_id,
                step.file_checkbox_ids.ids,
                req.final_data or '',
                department_id
            )

            if isinstance(vals, dict):
                step.write(vals)

        return {'type': 'ir.actions.act_window_close'}


class StudentRequestBulkAssignLine(models.TransientModel):
    _name = 'student.request.bulk.assign.line'
    _description = 'Dòng chọn yêu cầu phân công'

    wizard_id = fields.Many2one('student.request.bulk.assign.wizard', string='Wizard', required=True, ondelete='cascade')
    request_id = fields.Many2one('student.service.request', string='Yêu cầu dịch vụ', required=True)
    selected = fields.Boolean('Chọn', default=True)
    # Thông tin hiển thị phục vụ xem trước
    service_id = fields.Many2one(related='request_id.service_id', string='Dịch vụ', store=False)
    final_state = fields.Selection(related='request_id.final_state', string='Trạng thái', store=False)
    user_processing_id = fields.Many2one(related='request_id.user_processing_id', string='Người xử lý', store=False)
    request_date = fields.Datetime(related='request_id.request_date', string='Ngày gửi', store=False)
    expired_date = fields.Datetime(related='request_id.expired_date', string='Hạn xử lý', store=False)