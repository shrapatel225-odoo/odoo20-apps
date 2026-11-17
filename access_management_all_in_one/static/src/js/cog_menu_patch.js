import { patch } from "@web/core/utils/patch";
import { CogMenu } from "@web/search/cog_menu/cog_menu";
import { isRestricted } from "./access_rules";

// Cog menu entries (by component name) and the rule flag that hides them.
const RESTRICTED_COG_ITEMS = {
    ExportAll: "no_export",
    ImportRecords: "no_import",
    SpreadsheetCogMenu: "no_spreadsheet",
};

patch(CogMenu.prototype, {
    async _registryItems() {
        const items = await super._registryItems(...arguments);
        const resModel = this.props.resModel || this.env.searchModel?.resModel;
        return items.filter((item) => {
            const flag = RESTRICTED_COG_ITEMS[item.key];
            return !(flag && isRestricted(flag, resModel));
        });
    },
});
