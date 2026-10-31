from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.translate import _


class MwdAllowedModel(models.Model):
    """Administrator-curated list of models users may build tiles on.

    This list is a governance and usability boundary, not a security one: it
    stops users pointing a tile at a model nobody meant them to think about.
    Actual data protection comes from reading through the user's own
    environment, so access rights and record rules always apply.
    """
    _name = 'mwd.allowed.model'
    _description = 'My Work Day: Selectable Model'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    model_id = fields.Many2one(
        'ir.model', string='Model', required=True, ondelete='cascade',
        domain=[('transient', '=', False)],
    )
    model_name = fields.Char(related='model_id.model', string='Technical Name', store=True, index=True)
    name = fields.Char(
        string='Label', compute='_compute_name', store=True, readonly=False,
        help="Name shown to users when they pick this model. Defaults to the model's own name.",
    )
    group_ids = fields.Many2many(
        'res.groups', string='Restricted to Groups',
        help="Leave empty to make this model available to every internal user. "
             "Otherwise only users in at least one of these groups can build tiles on it.",
    )
    allow_agenda = fields.Boolean(
        string='Allow Agenda Tiles', default=False,
        help="Let users build an agenda tile (today's records) on this model.",
    )
    date_field_id = fields.Many2one(
        'ir.model.fields', string='Default Date Field',
        domain="[('model_id', '=', model_id), ('ttype', 'in', ['date', 'datetime']), ('store', '=', True)]",
        ondelete='set null',
        help="Date field an agenda tile uses by default.",
    )

    _model_uniq = models.Constraint('UNIQUE(model_id)', "This model is already selectable.")

    @api.depends('model_id')
    def _compute_name(self):
        for record in self:
            record.name = record.model_id.name

    @api.onchange('model_id')
    def _onchange_model_id(self):
        if self.date_field_id.model_id != self.model_id:
            self.date_field_id = False

    @api.constrains('date_field_id', 'model_id')
    def _check_date_field(self):
        for record in self:
            if record.date_field_id and record.date_field_id.model_id != record.model_id:
                raise ValidationError(_(
                    "The date field %(field)s does not belong to model %(model)s.",
                    field=record.date_field_id.name, model=record.model_id.name,
                ))

    @api.model
    def _search_available(self):
        """Return the allowed models the current user may actually pick from."""
        user_groups = self.env.user.all_group_ids
        available = self.search([]).filtered(
            lambda allowed: not allowed.group_ids or (allowed.group_ids & user_groups)
        )
        # Drop anything the user cannot even read, so the list never advertises
        # a model that would fail the moment they used it.
        return available.filtered(lambda allowed: allowed._is_readable())

    def _is_readable(self):
        self.ensure_one()
        model = self.env.get(self.model_name)
        if model is None:
            return False
        return model.has_access('read')

    @api.model
    def _available_domain(self):
        return [('id', 'in', self._search_available().ids)]
