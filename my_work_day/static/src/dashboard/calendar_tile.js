import { Component, onWillStart, onWillUpdateProps, useSubEnv } from "@odoo/owl";

import { useService } from "@web/core/utils/hooks";
import { View } from "@web/views/view";

/**
 * A real calendar inside a tile.
 *
 * This renders Odoo's own calendar view rather than a home-made grid, which is
 * why it is worth having at all: the month and week layouts, the hour grid, the
 * popovers and the time-zone handling are all the ones used everywhere else.
 *
 * The arch comes from the server, built around the date field the tile's owner
 * chose. The model's own calendar view is deliberately not used: it may not
 * exist, and Odoo's generated fallback insists on an end date that most models
 * do not have.
 */
export class MwdCalendarTile extends Component {
    static template = "my_work_day.CalendarTile";
    static components = { View };
    static props = { tile: Object };

    setup() {
        this.viewService = useService("view");
        // Read by calendar_scale_patch.js, so this tile remembers its own scale
        // instead of sharing one with every other calendar tile.
        const { tile } = this.props;
        useSubEnv({ config: { ...this.env.config, mwdScaleKey: `${tile.id}-${tile.mode}` } });
        onWillStart(() => this.buildViewProps(this.props));
        onWillUpdateProps((nextProps) => this.buildViewProps(nextProps));
    }

    async buildViewProps(props) {
        const { tile } = props;
        // Only for the field descriptions and related models: the calendar
        // arch parser needs them, and `View` will not fetch them itself once
        // an arch is handed to it. A list view is asked for because every
        // model has one, generated if need be, while a calendar view often
        // cannot be generated at all. The view service caches the result, so
        // several tiles on one model cost one request.
        const loaded = await this.viewService.loadViews({
            resModel: tile.model,
            views: [[false, "list"]],
            context: {},
        });
        // The list view only describes its own columns; the server adds the
        // fields this calendar needs, the event title among them.
        const fields = { ...loaded.fields, ...tile.fields };
        const relatedModels = {
            ...loaded.relatedModels,
            [tile.model]: { ...loaded.relatedModels[tile.model], fields },
        };
        this.viewProps = {
            type: "calendar",
            resModel: tile.model,
            arch: tile.arch,
            fields,
            relatedModels,
            domain: tile.domain,
            // No control panel: the tile header is the title, and the calendar
            // keeps its own date navigation, which lives in the view itself
            // rather than in the control panel.
            display: { controlPanel: false },
            searchMenuTypes: [],
        };
    }
}
