from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class RequestExtensionRejectWizard(models.TransientModel):
    _name = 'request.extension.reject.wizard'
    _description = 'Wizard để từ chối yêu cầu gia hạn'

    extension_id = fields.Many2one('request.extension', string='Yêu cầu gia hạn', required=True)
    rejection_reason = fields.Text(string='Lý do từ chối', required=True)

    def action_reject_extension(self):
        """Từ chối yêu cầu gia hạn"""
        if not self.rejection_reason:
            raise ValidationError("Vui lòng nhập lý do từ chối.")
        
        # Cập nhật trạng thái yêu cầu gia hạn
        self.extension_id.write({
            'state': 'rejected',
            'rejection_reason': self.rejection_reason,
            'approved_by': self.env.user.id,
            'approval_date': fields.Datetime.now()
        })
        
        return {'type': 'ir.actions.act_window_close'}