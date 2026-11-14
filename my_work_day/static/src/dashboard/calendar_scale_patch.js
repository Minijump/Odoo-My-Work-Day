import { patch } from "@web/core/utils/patch";
import { CalendarModel } from "@web/views/calendar/calendar_model";

/**
 * Give each calendar tile its own remembered scale.
 *
 * Odoo's calendar remembers the last scale you picked, per view, in local
 * storage keyed on the view's id. A tile's calendar is built from an arch, not
 * a stored view, so it has no id -- and every calendar tile in the browser
 * shared one key: switching one tile to Day opened all the others on Day too,
 * whatever their own Calendar Scale said.
 *
 * The key carries the tile's configured scale as well as its id, so changing
 * that setting takes effect even for someone who once picked another scale on
 * the tile. Anything that is not a tile keeps Odoo's own key.
 */
patch(CalendarModel.prototype, {
    get storageKey() {
        const tileKey = this.env.config.mwdScaleKey;
        return tileKey ? `scaleOf-mwd-tile-${tileKey}` : super.storageKey;
    },
});
