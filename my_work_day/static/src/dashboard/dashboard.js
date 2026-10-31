import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

import { MwdAppsRow } from "./apps_row";
import { MwdTile } from "./tile";

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

        this.state = useState({
            data: null,
            loading: true,
            error: null,
            refreshedAt: null,
        });

        this.refreshTimer = null;

        onWillStart(() => this.load());
        onWillUnmount(() => this.stopAutoRefresh());

        // Pausing while the tab is hidden is what makes auto-refresh safe to
        // leave on: a dashboard forgotten overnight stops querying.
        this.onVisibilityChange = () => {
            if (document.visibilityState === "visible") {
                this.startAutoRefresh();
                this.load({ silent: true });
            } else {
                this.stopAutoRefresh();
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

    get gridStyle() {
        const columns = this.state.data?.column_count || 4;
        return `--mwd-columns: ${columns};`;
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
            this.startAutoRefresh();
        } catch (error) {
            // A dashboard that cannot load should say so rather than showing a
            // blank page, so the user knows to tell someone.
            this.state.error = error?.data?.message || error?.message || _t("Unknown error");
            throw error;
        } finally {
            this.state.loading = false;
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
        this.notification.add(_t("Dashboard refreshed"), { type: "success" });
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

    async onOpenTileRecords(tile) {
        const action = await this.orm.call("mwd.tile", "action_open_tile", [tile.id]);
        this.action.doAction(action);
    }

    async onOpenLine(tile, line) {
        const action = await this.orm.call("mwd.tile", "action_open_line", [tile.id, line.id]);
        this.action.doAction(action);
    }

    async onOpenGroup(tile, bar) {
        const action = await this.orm.call("mwd.tile", "action_open_group", [tile.id, bar.domain]);
        this.action.doAction(action);
    }

    async onOpenRecord(tile, entry) {
        const action = await this.orm.call("mwd.tile", "action_open_record", [tile.id, entry.id]);
        this.action.doAction(action);
    }
}

registry.category("actions").add("my_work_day_dashboard", MwdDashboard);
