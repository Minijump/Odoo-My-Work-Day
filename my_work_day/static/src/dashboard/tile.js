import { Component } from "@odoo/owl";

/**
 * One tile on the dashboard.
 *
 * Presentation only: every number it shows was counted on the server, and
 * every click hands off to the parent, which asks the server for the action.
 * Nothing here decides what a user may see.
 */
export class MwdTile extends Component {
    static template = "my_work_day.Tile";
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
        const tile = this.tile;
        if (tile.error) {
            return false;
        }
        if (tile.type === "count") {
            return !tile.lines?.length;
        }
        if (tile.type === "agenda") {
            return !tile.entries?.length;
        }
        if (tile.type === "breakdown") {
            return !tile.bars?.length;
        }
        return true;
    }

    colorClass(color) {
        return `mwd_color_${color || "muted"}`;
    }
}
