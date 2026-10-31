import { Component, useState } from "@odoo/owl";

import { registry } from "@web/core/registry";
import { session } from "@web/session";
import { useService } from "@web/core/utils/hooks";

/**
 * A way back to the dashboard from anywhere.
 *
 * Once My Work Day is not your landing page there is nothing quick that gets
 * you back to it, and the apps menu is three clicks. The systray is the right
 * place for that: it is Community `web`, it needs no patching of the navbar,
 * and it sits beside the activities and messaging icons, which are the same
 * kind of thing.
 *
 * Whether to show it at all is decided by `mwd_can_use` in the session, so
 * an administrator who takes the Reader group away from someone does not
 * leave them an icon that only produces an access error -- and finding that
 * out costs no extra request.
 */
export class MwdSystrayItem extends Component {
    static template = "my_work_day.SystrayItem";
    static props = {};

    setup() {
        this.action = useService("action");
        this.menu = useService("menu");
        this.state = useState({ busy: false });
    }

    async onClick() {
        if (this.state.busy) {
            return;
        }
        this.state.busy = true;
        try {
            // Go through the menu rather than straight to the action, so the
            // navbar ends up saying My Work Day. Opening the action alone
            // leaves whatever app you came from named in the navbar, which
            // reads like a bug even though nothing is wrong.
            const app = this.menu
                .getApps()
                .find((entry) => entry.xmlid === "my_work_day.menu_my_work_day_root");
            if (app) {
                await this.menu.selectMenu(app);
            } else {
                await this.action.doAction("my_work_day.action_my_work_day_dashboard", {
                    clearBreadcrumbs: true,
                });
            }
        } finally {
            this.state.busy = false;
        }
    }
}

registry.category("systray").add(
    "my_work_day.dashboard",
    { Component: MwdSystrayItem, isDisplayed: () => !!session.mwd_can_use },
    { sequence: 40 }
);
