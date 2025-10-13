from odoo import models, fields, api
from odoo.exceptions import ValidationError
from ..controllers.service_api.request_api import update_request_step


class StudentRequestBulkAssignWizard(models.TransientModel):
    _name = 'student.request.bulk.assign.wizard'
    _description = 'Phân công hàng loạt yêu cầu dịch vụ'

    request_ids = fields.Many2many('student.service.request', string='Yêu cầu dịch vụ')
    assign_user_id = fields.Many2one('res.users', string='Người được phân công', help='Người đã được phân công tiêp theo để xử lý bước này')
    department_id = fields.Many2one('student.activity.department', string='Phòng ban được phân công')
    note = fields.Char(string='Ghi chú', default='Phân công hàng loạt')

    @api.model
    def _check_same_service(self, requests):
        service_ids = requests.mapped('service_id.id')
        return len(set(service_ids)) <= 1

    def action_assign(self):
        active_ids = self.env.context.get('active_ids') or []
        selected_ids = active_ids or self.request_ids.ids
        if not selected_ids:
            raise ValidationError('Vui lòng chọn các yêu cầu dịch vụ để phân công (từ danh sách hoặc ngay trong wizard).')

        requests = self.env['student.service.request'].browse(selected_ids)

        # Chỉ cho phép phân công các yêu cầu cùng dịch vụ
        if not self._check_same_service(requests):
            raise ValidationError('Chỉ phân công các yêu cầu thuộc cùng một dịch vụ.')

        if not (self.assign_user_id or self.department_id):
            raise ValidationError('Vui lòng chọn Người được phân công hoặc Phòng ban.')

        for req in requests:
            # Lấy bước đầu tiên còn ở trạng thái pending hoặc assigned
            step = req.step_ids.filtered(lambda s: s.state in ('pending', 'assigned')).sorted('base_secquence')
            if not step:
                # Nếu không có bước phù hợp, bỏ qua yêu cầu này
                continue
            step = step[0]

            next_user_id = self.assign_user_id.id if self.assign_user_id else 0
            department_id = self.department_id.id if self.department_id else 0

            # Sử dụng API update_request_step để đồng bộ lịch sử, trạng thái và phân công
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