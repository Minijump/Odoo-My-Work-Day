from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .mwd_tile import COLORS, CONDITIONS, color_for


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

    @api.constrains('tile_id')
    def _check_tile_line_limit(self):
        """Count the filters per tile here as well as on the tile itself.

        A line can be created on its own, with only ``tile_id`` set, which
        never touches the tile's own ``line_ids`` constraint. The check lives
        on the tile; this is the second door into it.
        """
        self.mapped('tile_id')._check_line_limit()

    @api.constrains('color_threshold')
    def _check_threshold(self):
        for line in self:
            if line.color_condition != 'none' and line.color_threshold < 0:
                raise ValidationError(_("A threshold cannot be negative."))

    def _line_color(self, count):
        """The colour this line should take for a given count."""
        self.ensure_one()
        return color_for(self.color_condition, self.color_threshold, self.color, count)
