import { Component, useState } from "@odoo/owl";

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";

import { MWD_ALL_ICONS, MWD_SUGGESTED_ICONS } from "@my_work_day/dashboard/icons";

/**
 * Pick a tile icon by looking at it.
 *
 * The field stores a Font Awesome class name, which is fine for the database
 * and useless for a person: nobody knows that a lorry is "fa-truck". So the
 * field shows the icon, and clicking it opens a grid to choose from.
 */
export class MwdIconDialog extends Component {
    static template = "my_work_day.IconDialog";
    static components = { Dialog };
    static props = {
        current: { type: String, optional: true },
        close: Function,
        onSelected: Function,
    };

    setup() {
        this.state = useState({ search: "" });
    }

    get icons() {
        const search = this.state.search.trim().toLowerCase();
        if (!search) {
            return MWD_SUGGESTED_ICONS;
        }
        // Names are "fa-shopping-cart", so a search for "cart" or for
        // "shopping cart" should both find it.
        const needle = search.replace(/\s+/g, "-");
        return MWD_ALL_ICONS.filter((icon) => icon.includes(needle)).slice(0, 180);
    }

    get totalIcons() {
        return MWD_ALL_ICONS.length;
    }

    get isSearching() {
        return Boolean(this.state.search.trim());
    }

    label(icon) {
        return icon.slice(3).replace(/-/g, " ");
    }

    onPick(icon) {
        this.props.onSelected(icon);
        this.props.close();
    }
}

export class MwdIconField extends Component {
    static template = "my_work_day.IconField";
    static props = { ...standardFieldProps };

    setup() {
        this.dialog = useService("dialog");
    }

    get icon() {
        return this.props.record.data[this.props.name] || "fa-list";
    }

    onOpen() {
        if (this.props.readonly) {
            return;
        }
        this.dialog.add(MwdIconDialog, {
            current: this.icon,
            onSelected: (icon) => this.props.record.update({ [this.props.name]: icon }),
        });
    }
}

registry.category("fields").add("mwd_icon", {
    component: MwdIconField,
    displayName: "Icon picker",
    supportedTypes: ["char"],
});
