import { Component } from "@odoo/owl";

import { MwdCalendarTile } from "./calendar_tile";

/**
 * Whether a tile has nothing at all to show.
 *
 * Exported because the dashboard needs the same answer for every tile at once,
 * to decide whether the whole day is clear -- and two definitions of "empty"
 * that could drift apart would be a bug waiting to happen.
 */
export function isTileEmpty(tile) {
    if (tile.error) {
        return false;
    }
    switch (tile.type) {
        case "count":
            return !tile.lines?.length;
        // A single number is never empty: zero is the answer, not the absence
        // of one, and a tile whose whole job is to show it should show it.
        case "value":
            return false;
        case "agenda":
            return !tile.entries?.length;
        case "breakdown":
            return !tile.bars?.length;
        // A calendar is never empty: an empty week is still a week, and the
        // grid is the point of the tile.
        case "calendar":
            return false;
        default:
            return true;
    }
}

/**
 * One tile on the dashboard.
 *
 * Presentation only: every number it shows was counted on the server, and
 * every click hands off to the parent, which asks the server for the action.
 * Nothing here decides what a user may see.
 */
export class MwdTile extends Component {
    static template = "my_work_day.Tile";
    static components = { MwdCalendarTile };
    static props = {
        tile: Object,
        onOpenTile: Function,
        onOpenLine: Function,
        onOpenGroup: Function,
        onOpenRecord: Function,
    };

    get tile() {
        return this.props.tile;
    }

    get style() {
        return `--mwd-tile-width: ${this.tile.width}; --mwd-tile-height: ${this.tile.height};`;
    }

    get isEmpty() {
        return isTileEmpty(this.tile);
    }

    colorClass(color) {
        return `mwd_color_${color || "muted"}`;
    }
}
