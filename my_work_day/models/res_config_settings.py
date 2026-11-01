from odoo import _, api, fields, models

from .mwd_dashboard import REFRESH_INTERVAL_PARAM
from .mwd_tile import MAX_LINES_PARAM, MAX_TILES_PARAM
from .res_users import HOME_ACTION_PARAM


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    mwd_default_home_action = fields.Boolean(
        string='My Work Day as default landing page',
        config_parameter=HOME_ACTION_PARAM,
        help="New internal users will land on their My Work Day dashboard instead "
             "of the apps menu. Existing users keep whatever they have now; use the "
             "button below to change them all at once.",
    )
    mwd_user_count = fields.Integer(
        string='Users on My Work Day', compute='_compute_mwd_user_count')
    mwd_refresh_interval = fields.Selection(
        [('0', 'Off'), ('120', 'Every 2 minutes'), ('300', 'Every 5 minutes'),
         ('900', 'Every 15 minutes')],
        string='Auto Refresh', default='0',
        config_parameter=REFRESH_INTERVAL_PARAM,
        help="How often an open dashboard reloads its counters. This is set "
             "here rather than per dashboard because the number decides how "
             "much the database is queried, which is not a choice to leave to "
             "each user. Refreshing pauses while a browser tab is in the "
             "background, so a dashboard left open overnight still costs "
             "nothing.",
    )
    mwd_max_tiles = fields.Integer(
        string='Tiles per dashboard',
        config_parameter=MAX_TILES_PARAM,
        help="The most tiles one dashboard may hold. Every tile on the page is "
             "counted on each load, so this is what stops one enthusiastic user "
             "turning a page load into hundreds of queries. Leave empty, or at "
             "zero, for no limit.",
    )
    mwd_max_lines = fields.Integer(
        string='Filters per tile',
        config_parameter=MAX_LINES_PARAM,
        help="The most filters one counter tile may hold. Leave empty, or at "
             "zero, for no limit.",
    )

    @api.depends('mwd_default_home_action')
    def _compute_mwd_user_count(self):
        action = self.env.ref(
            'my_work_day.action_my_work_day_dashboard', raise_if_not_found=False)
        count = 0
        if action:
            count = self.env['res.users'].sudo().search_count([
                ('action_id', '=', action.id),
            ])
        for setting in self:
            setting.mwd_user_count = count

    def action_apply_home_to_all_users(self):
        """Point every internal user at the dashboard.

        A deliberate, explicit administrator action rather than something the
        install does quietly behind everyone's back.
        """
        self.ensure_one()
        action = self.env.ref('my_work_day.action_my_work_day_dashboard')
        users = self.env['res.users'].sudo().search([
            ('share', '=', False),
            ('active', '=', True),
        ])
        users.write({'action_id': action.id})
        return self._notify(_("%s users will now land on My Work Day.", len(users)))

    def action_reset_home_for_all_users(self):
        """Give every internal user the standard landing page back."""
        self.ensure_one()
        action = self.env.ref('my_work_day.action_my_work_day_dashboard')
        users = self.env['res.users'].sudo().search([('action_id', '=', action.id)])
        users.write({'action_id': False})
        return self._notify(_("%s users were reset to the default landing page.", len(users)))

    def _notify(self, message):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'type': 'success', 'message': message, 'next': {'type': 'ir.actions.act_window_close'}},
        }
