from odoo import api, fields, models

HOME_ACTION_PARAM = 'my_work_day.default_home_action'


class ResUsers(models.Model):
    _inherit = 'res.users'

    mwd_dashboard_ids = fields.One2many('mwd.dashboard', 'user_id', string='My Work Day Dashboards')
    mwd_favorite_menu_ids = fields.Many2many(
        'ir.ui.menu', 'mwd_user_favorite_menu_rel', 'user_id', 'menu_id',
        string='Favourite Apps',
        domain=[('parent_id', '=', False)],
        help="Apps to show as shortcuts at the top of your My Work Day dashboard.",
    )

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + ['mwd_favorite_menu_ids']

    @property
    def SELF_WRITEABLE_FIELDS(self):
        return super().SELF_WRITEABLE_FIELDS + ['mwd_favorite_menu_ids']

    @api.model_create_multi
    def create(self, vals_list):
        """Give new internal users the dashboard as their landing page.

        Only when an administrator asked for it, and never over a home action
        the user was created with.
        """
        users = super().create(vals_list)
        enabled = self.env['ir.config_parameter'].sudo().get_param(HOME_ACTION_PARAM)
        if not enabled or enabled == 'False':
            return users
        action = self.env.ref(
            'my_work_day.action_my_work_day_dashboard', raise_if_not_found=False)
        if not action:
            return users
        for user in users:
            if not user.action_id and not user.share:
                user.sudo().action_id = action.id
        return users
