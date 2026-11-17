import { patch } from "@web/core/utils/patch";
import { ListController } from "@web/views/list/list_controller";
import { isRestricted } from "./access_rules";

patch(ListController.prototype, {
    getStaticActionMenuItems() {
        const items = super.getStaticActionMenuItems(...arguments);
        if (items.export && isRestricted("no_export", this.props.resModel)) {
            items.export = { ...items.export, isAvailable: () => false };
        }
        return items;
    },
});
