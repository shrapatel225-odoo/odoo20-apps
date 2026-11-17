import { Chatter } from "@mail/chatter/web_portal_project/chatter";
import { patch } from "@web/core/utils/patch";
import { isRestricted } from "./access_rules";

patch(Chatter.prototype, {
    /**
     * @param {"hide_send_message"|"hide_log_note"|"hide_activity"} flag
     * @returns {boolean}
     */
    accessSuiteHides(flag) {
        const model = typeof this.threadModel === "function" ? this.threadModel() : this.props.threadModel;
        return isRestricted(flag, model);
    },
});
