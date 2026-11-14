import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";

import { makeContext } from "@web/core/context";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { SelectCreateDialog } from "@web/views/view_dialogs/select_create_dialog";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

import { MwdAppsRow } from "./apps_row";
import { MwdTile, isTileEmpty } from "./tile";

/**
 * The My Work Day dashboard.
 *
 * Everything on screen comes from a single `get_dashboard_data` call: the
 * server does all the counting, so a dashboard with thirty filters costs one
 * request rather than thirty.
 */
export class MwdDashboard extends Component {
    static template = "my_work_day.Dashboard";
    static components = { MwdAppsRow, MwdTile };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.menu = useService("menu");

        this.state = useState({
            data: null,
            loading: true,
            error: null,
            refreshedAt: null,
            // Set when the user asks to see the tiles anyway on a clear day.
            showClearedTiles: false,
        });

        this.refreshTimer = null;

        onWillStart(() => this.load());
        onWillUnmount(() => this.stopAutoRefresh());

        // Pausing while the tab is hidden is what makes auto-refresh safe to
        // leave on: a dashboard forgotten overnight stops querying. Coming back
        // catches up at once -- but only when auto-refresh is on at all: with
        // it off, the administrator decided the dashboard reloads when someone
        // asks, and switching tabs is not asking.
        this.onVisibilityChange = () => {
            if (document.visibilityState !== "visible") {
                this.stopAutoRefresh();
            } else if (this.state.data?.refresh_interval) {
                this.load({ silent: true });
            }
        };
        document.addEventListener("visibilitychange", this.onVisibilityChange);
        onWillUnmount(() =>
            document.removeEventListener("visibilitychange", this.onVisibilityChange)
        );
    }

    get dashboardId() {
        return this.props.action.params?.dashboard_id || null;
    }

    get tiles() {
        return this.state.data?.tiles || [];
    }

    /**
     * True when there is genuinely nothing waiting: every tile loaded, and
     * every one of them came back with nothing in it.
     *
     * This is worth saying out loud rather than drawing: a screenful of tiles
     * each reading "Nothing to show" takes real attention to confirm, and the
     * one thing the reader wants to know is that they are clear.
     */
    get allClear() {
        const tiles = this.tiles;
        return tiles.length > 0 && tiles.every((tile) => isTileEmpty(tile));
    }

    get gridStyle() {
        const columns = this.state.data?.column_count || 4;
        return `--mwd-columns: ${columns};`;
    }

    get homeButtonTitle() {
        return this.state.data?.is_home
            ? _t("This is your landing page")
            : _t("Make this your landing page");
    }

    get refreshedLabel() {
        if (!this.state.refreshedAt) {
            return "";
        }
        return _t("Updated at %s", this.state.refreshedAt.toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
        }));
    }

    /**
     * Fetch everything and redraw.
     *
     * Errors are handled here rather than thrown on. A load that fails on
     * opening shows its own message in place of the tiles, instead of the
     * whole action failing to mount. A background refresh that fails -- a
     * laptop waking up, a network blip -- keeps the counts already on screen
     * and tries again next time, instead of raising an error dialog at every
     * interval.
     */
    async load({ silent = false } = {}) {
        if (!silent) {
            this.state.loading = true;
        }
        try {
            const data = await this.orm.call("mwd.dashboard", "get_dashboard_data", [], {
                dashboard_id: this.dashboardId,
            });
            this.state.data = data;
            this.state.error = null;
            this.state.refreshedAt = new Date();
        } catch (error) {
            if (!silent || !this.state.data) {
                this.state.error =
                    error?.data?.message || error?.message || _t("Unknown error");
            }
        } finally {
            this.state.loading = false;
            this.startAutoRefresh();
        }
    }

    startAutoRefresh() {
        this.stopAutoRefresh();
        const interval = this.state.data?.refresh_interval || 0;
        if (!interval || document.visibilityState !== "visible") {
            return;
        }
        this.refreshTimer = setInterval(() => {
            if (document.visibilityState === "visible") {
                this.load({ silent: true });
            }
        }, interval * 1000);
    }

    stopAutoRefresh() {
        if (this.refreshTimer) {
            clearInterval(this.refreshTimer);
            this.refreshTimer = null;
        }
    }

    async onRefresh() {
        await this.load();
        if (!this.state.error) {
            this.notification.add(_t("Dashboard refreshed"), { type: "success" });
        }
    }

    onConfigure() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("Configure Dashboard"),
            res_model: "mwd.dashboard",
            res_id: this.state.data.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    onAddTile() {
        this.action.doAction(
            {
                type: "ir.actions.act_window",
                name: _t("New Tile"),
                res_model: "mwd.tile",
                views: [[false, "form"]],
                target: "new",
                context: { default_dashboard_id: this.state.data.id },
            },
            { onClose: () => this.load() }
        );
    }

    /**
     * Pick a colleague's shared tile and copy it here, without leaving the page.
     *
     * The same thing the Shared Tiles menu does, one click away from where the
     * need arises. The copy goes through the server method that menu uses, so
     * the tile limit and ownership rules apply exactly as they do there.
     */
    onAddSharedTile() {
        this.dialog.add(SelectCreateDialog, {
            resModel: "mwd.tile",
            title: _t("Copy a Colleague's Tile"),
            domain: [
                ["is_shared", "=", true],
                ["user_id", "!=", user.userId],
            ],
            noCreate: true,
            onSelected: async (resIds) => {
                await this.orm.call("mwd.tile", "action_duplicate_to_my_dashboard", [resIds]);
                await this.load();
                this.notification.add(_t("Added to your dashboard."), { type: "success" });
            },
        });
    }

    async onToggleHome() {
        const method = this.state.data.is_home ? "action_unset_as_home" : "action_set_as_home";
        await this.orm.call("mwd.dashboard", method, []);
        this.state.data.is_home = !this.state.data.is_home;
        this.notification.add(
            this.state.data.is_home
                ? _t("My Work Day is now your landing page.")
                : _t("Your landing page is back to the default."),
            { type: "success" }
        );
    }

    /**
     * Run the action the server built for a click on a tile.
     *
     * When the tile is linked to an app menu, the action is that menu's own,
     * and two things make it land properly inside the app: the navbar switches
     * to that app, and the menu's search defaults (a "My Quotations" filter,
     * say) are dropped, because they would narrow the list below the number
     * the tile showed.
     */
    openTileAction(action, newWindow) {
        const menuId = action.mwd_menu_id;
        if (!menuId) {
            return this.action.doAction(action, { newWindow });
        }
        let context = action.context;
        try {
            context = Object.fromEntries(
                Object.entries(makeContext([user.context, action.context || {}])).filter(
                    ([key]) => !key.startsWith("search_default_")
                )
            );
        } catch {
            // A menu context that needs more than the user's own to evaluate
            // is left as it is: at worst a default filter narrows the list.
        }
        return this.action.doAction(
            { ...action, context },
            { newWindow, onActionReady: () => this.menu.setCurrentMenu(menuId) }
        );
    }

    // Each of these takes `newWindow`, true on a Ctrl+click or a middle click,
    // so a list can be opened in its own browser tab while the dashboard stays.

    async onOpenTileRecords(tile, newWindow = false) {
        const action = await this.orm.call("mwd.tile", "action_open_tile", [tile.id]);
        this.openTileAction(action, newWindow);
    }

    async onOpenLine(tile, line, newWindow = false) {
        const action = await this.orm.call("mwd.tile", "action_open_line", [tile.id, line.id]);
        this.openTileAction(action, newWindow);
    }

    async onOpenGroup(tile, bar, newWindow = false) {
        const action = await this.orm.call("mwd.tile", "action_open_group", [tile.id, bar.domain]);
        this.openTileAction(action, newWindow);
    }

    async onOpenRecord(tile, entry, newWindow = false) {
        const action = await this.orm.call("mwd.tile", "action_open_record", [tile.id, entry.id]);
        this.openTileAction(action, newWindow);
    }
}

registry.category("actions").add("my_work_day_dashboard", MwdDashboard);
