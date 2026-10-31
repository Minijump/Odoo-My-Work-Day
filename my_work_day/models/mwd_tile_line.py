from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .mwd_tile import COLORS

CONDITIONS = [
    ('none', 'Never'),
    ('gt', 'More than'),
    ('ge', 'At least'),
    ('lt', 'Fewer than'),
    ('eq', 'Exactly'),
]


class MwdTileLine(models.Model):
    _name = 'mwd.tile.line'
    _description = 'My Work Day Tile Line'
    _order = 'sequence, id'

    name = fields.Char(string='Label', required=True)
    sequence = fields.Integer(default=10)
    tile_id = fields.Many2one(
        'mwd.tile', string='Tile', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one(related='tile_id.user_id', string='Owner', store=True, index=True)
    domain = fields.Char(string='Filter', default='[]', required=True)

    model_name = fields.Char(
        string='Technical Model',
        default=lambda self: self.env.context.get('default_model_name'),
        help="Helper copy of the tile's model, so the filter editor knows which "
             "fields to offer. The dashboard itself always reads the model from the tile.",
    )

    color_condition = fields.Selection(
        CONDITIONS, string='Highlight When', default='none', required=True,
        help="Turn this line a colour once the count crosses a threshold, so the "
             "things that need attention stand out.")
    color_threshold = fields.Integer(string='Threshold', default=0)
    color = fields.Selection(COLORS, string='Highlight Colour', default='warning', required=True)

    @api.constrains('domain')
    def _check_domain(self):
        for line in self:
            line.tile_id._validate_domain(line.domain)

    @api.constrains('color_threshold')
    def _check_threshold(self):
        for line in self:
            if line.color_condition != 'none' and line.color_threshold < 0:
                raise ValidationError(_("A threshold cannot be negative."))

    def _line_color(self, count):
        """The colour this line should take for a given count."""
        self.ensure_one()
        condition = self.color_condition
        threshold = self.color_threshold
        triggered = (
            (condition == 'gt' and count > threshold)
            or (condition == 'ge' and count >= threshold)
            or (condition == 'lt' and count < threshold)
            or (condition == 'eq' and count == threshold)
        )
        return self.color if triggered else 'muted'
