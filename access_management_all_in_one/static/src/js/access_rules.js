import { session } from "@web/session";

/**
 * Client side view of the access profile rules of the current user.
 * The server sends them in session_info["access_suite"]; the server keeps
 * enforcing everything that matters (export, import, archive, CRUD...).
 */
const rules = session.access_suite || { global: {}, models: {} };

/**
 * @param {string} flag e.g. "no_export", "hide_send_message"
 * @param {string} [resModel]
 * @returns {boolean}
 */
export function isRestricted(flag, resModel) {
    if (rules.global?.[flag]) {
        return true;
    }
    return Boolean(resModel && rules.models?.[resModel]?.[flag]);
}
