from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        """Two flags the browser needs before it renders anything.

        `mwd_is_home_action` exists because Odoo 19's web client ignores the
        user's Home Action when the URL names no action: `_loadDefaultApp`
        simply opens the first app in the menu. We patch that method, but only
        for users who actually opted in -- hence the flag, so the patch stays
        out of everyone else's way.

        `mwd_can_use` says whether to put the dashboard shortcut in the
        systray. Both ride along on the session rather than costing a request
        of their own on every page load.
        """
        result = super().session_info()
        if not result.get('uid'):
            return result
        action = self.env.ref(
            'my_work_day.action_my_work_day_dashboard', raise_if_not_found=False)
        result['mwd_is_home_action'] = bool(
            action and self.env.user.action_id.id == action.id)
        result['mwd_can_use'] = bool(action) and self.env.user.has_group(
            'my_work_day.group_my_work_day_reader')
        return result
