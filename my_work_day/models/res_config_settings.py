from odoo import _, api, fields, models

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
