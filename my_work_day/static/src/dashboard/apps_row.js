import { Component } from "@odoo/owl";

import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";

/**
 * Shortcuts to the apps the user actually uses.
 *
 * The icons come from the menu service rather than from our own server call,
 * so they match the navbar exactly and cost nothing extra to load. The menu
 * service only ever hands over menus this user may see, so a favourite that
 * later becomes off-limits simply stops appearing.
 */
export class MwdAppsRow extends Component {
    static template = "my_work_day.AppsRow";
    static props = { menuIds: Array, onChanged: Function };

    setup() {
        this.menu = useService("menu");
        this.action = useService("action");
        this.orm = useService("orm");
    }

    get apps() {
        const wanted = new Set(this.props.menuIds);
        return this.menu.getApps().filter((app) => wanted.has(app.id));
    }

    onOpenApp(app) {
        this.menu.selectMenu(app);
    }

    /** Open the user's own preferences, the same way the user menu does. */
    async onEditFavorites() {
        const actionDescription = await this.orm.call("res.users", "action_get");
        actionDescription.res_id = user.userId;
        this.action.doAction(actionDescription, {
            onClose: () => this.props.onChanged(),
        });
    }
}
