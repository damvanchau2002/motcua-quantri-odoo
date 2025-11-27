from odoo import models, fields, api

class ServiceOption(models.Model):
    _name = 'student.service.option'
    _description = 'Service Selection Options'
    _order = 'sequence, name'
    
    name = fields.Char(string='Option', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    form_field_id = fields.Many2one(
        'student.service.form.field',
        string='Form Field',
        ondelete='cascade',
        required=True
    )
    
    _sql_constraints = [
        ('unique_option_per_field',
         'UNIQUE(form_field_id, name)',
         'Option must be unique per form field!')
    ]
