from odoo import fields, models


class IrModel(models.Model):
    _inherit = 'ir.model'

    # Only here so a record rule can ask "is this model on the whitelist?":
    # see the ir.model.fields rules in security/my_work_day_rules.xml.
    mwd_allowed_model_ids = fields.One2many(
        'mwd.allowed.model', 'model_id', string='My Work Day Selectable Model')
