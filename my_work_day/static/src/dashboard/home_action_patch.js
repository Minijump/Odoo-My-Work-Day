import { patch } from "@web/core/utils/patch";
import { session } from "@web/session";
import { user } from "@web/core/user";
import { WebClient } from "@web/webclient/webclient";

/**
 * Make the "Home Action" preference actually decide the landing page.
 *
 * In Odoo 19, opening /odoo with no action in the URL calls
 * `WebClient._loadDefaultApp`, which opens the first app in the menu and never
 * looks at `res.users.action_id`. The preference is only consulted as a
 * fallback when a URL names an action that no longer exists.
 *
 * The patch is deliberately narrow. `mwd_is_home_action` is only true for a
 * user who has chosen this dashboard as their home, so for everyone else --
 * including users of other modules that set a home action -- the original
 * behaviour runs untouched.
 */
patch(WebClient.prototype, {
    _loadDefaultApp() {
        if (session.mwd_is_home_action && user.homeActionId) {
            return this.actionService.doAction(user.homeActionId, {
                clearBreadcrumbs: true,
            });
        }
        return super._loadDefaultApp(...arguments);
    },
});
