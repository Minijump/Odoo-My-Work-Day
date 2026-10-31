from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        """Tell the browser whether this user chose My Work Day as their home.

        Odoo 19's web client ignores the user's Home Action when the URL names
        no action: `WebClient._loadDefaultApp` simply opens the first app in the
        menu. We patch that method, but only for users who actually opted in --
        hence this flag, so the patch can stay out of everyone else's way
        without an extra round trip on every page load.
        """
        result = super().session_info()
        if not result.get('uid'):
            return result
        action = self.env.ref(
            'my_work_day.action_my_work_day_dashboard', raise_if_not_found=False)
        result['mwd_is_home_action'] = bool(
            action and self.env.user.action_id.id == action.id)
        return result
