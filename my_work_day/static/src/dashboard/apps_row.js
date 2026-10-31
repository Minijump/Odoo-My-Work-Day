import { Component } from "@odoo/owl";

import { useService } from "@web/core/utils/hooks";

import { MwdAppsDialog } from "@my_work_day/dashboard/apps_dialog";

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
        this.dialog = useService("dialog");
    }

    get apps() {
        const wanted = new Set(this.props.menuIds);
        return this.menu.getApps().filter((app) => wanted.has(app.id));
    }

    onOpenApp(app) {
        this.menu.selectMenu(app);
    }

    onEditFavorites() {
        this.dialog.add(MwdAppsDialog, {
            menuIds: this.props.menuIds,
            onConfirmed: () => this.props.onChanged(),
        });
    }
}
