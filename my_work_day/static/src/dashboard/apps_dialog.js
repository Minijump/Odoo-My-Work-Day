import { Component, useState } from "@odoo/owl";

import { Dialog } from "@web/core/dialog/dialog";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";

/**
 * Pick the apps shown on the dashboard.
 *
 * This used to drop the user into their own preferences form, which is a
 * confusing place to land when all you wanted was to tick a few apps. Picking
 * them here keeps the whole thing on the dashboard.
 *
 * The list comes from the menu service, which is also what draws the navbar.
 * That gives the real app icons for free, and it only ever hands over menus
 * this user is allowed to see, so the picker cannot offer a way into an app
 * they have no access to.
 */
export class MwdAppsDialog extends Component {
    static template = "my_work_day.AppsDialog";
    static components = { Dialog };
    static props = {
        menuIds: Array,
        close: Function,
        onConfirmed: Function,
    };

    setup() {
        this.menu = useService("menu");
        this.orm = useService("orm");
        this.apps = this.menu.getApps();
        this.state = useState({
            selected: new Set(this.props.menuIds),
            saving: false,
        });
    }

    isSelected(app) {
        return this.state.selected.has(app.id);
    }

    toggle(app) {
        // Reassigned rather than mutated: a Set's own methods do not go
        // through the reactivity proxy, so mutating in place would not redraw.
        const selected = new Set(this.state.selected);
        if (selected.has(app.id)) {
            selected.delete(app.id);
        } else {
            selected.add(app.id);
        }
        this.state.selected = selected;
    }

    get selectionLabel() {
        const count = this.state.selected.size;
        if (!count) {
            return "No app selected";
        }
        return count === 1 ? "1 app selected" : `${count} apps selected`;
    }

    async onConfirm() {
        this.state.saving = true;
        try {
            await this.orm.write("res.users", [user.userId], {
                mwd_favorite_menu_ids: [[6, 0, [...this.state.selected]]],
            });
        } finally {
            this.state.saving = false;
        }
        await this.props.onConfirmed();
        this.props.close();
    }
}
