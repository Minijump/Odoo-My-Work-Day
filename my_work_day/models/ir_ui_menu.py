from odoo import fields, models


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    # Lets the tile form offer only the menus that open the tile's own model:
    # a menu on another model could not show what the tile counted.
    mwd_res_model = fields.Char(
        string='Opens Model', compute='_compute_mwd_res_model',
        search='_search_mwd_res_model')

    def _compute_mwd_res_model(self):
        for menu in self:
            action = menu.sudo().action
            menu.mwd_res_model = (
                action.res_model if action and action._name == 'ir.actions.act_window'
                else False)

    def _search_mwd_res_model(self, operator, value):
        if operator not in ('=', 'in'):
            return NotImplemented
        models_wanted = [value] if operator == '=' else list(value)
        actions = self.env['ir.actions.act_window'].sudo().search([
            ('res_model', 'in', models_wanted),
        ])
        # `action` is a reference field, stored as "model,id".
        return [('action', 'in', ['ir.actions.act_window,%s' % action.id for action in actions])]
