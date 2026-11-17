import logging

from odoo import fields, models
from odoo.exceptions import AccessDenied
from odoo.tools import SQL

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = 'res.users'

    access_profile_ids = fields.Many2many(
        'access.profile', 'access_profile_res_users_rel', 'user_id', 'profile_id',
        string='Access Profiles')

    def write(self, vals):
        res = super().write(vals)
        if 'access_profile_ids' in vals:
            self.env['access.profile']._access_suite_invalidate()
        return res

    def _get_session_token_query_params(self):
        # Running sessions of users whose login gets disabled are invalidated:
        # the extra column is NULL (ignored by the token hash) unless login is disabled.
        params = super()._get_session_token_query_params()
        params['select'] = SQL(
            """%s, (SELECT CASE WHEN bool_or(p.disable_login) THEN 'disabled' END
                     FROM access_profile p
                     JOIN access_profile_res_users_rel r ON r.profile_id = p.id
                    WHERE r.user_id = res_users.id AND p.active) AS access_suite_login""",
            params['select'],
        )
        return params

    def _check_credentials(self, credential, env):
        auth_info = super()._check_credentials(credential, env)
        flags = self.env['access.profile'].sudo()._get_login_flags(self.env.user.id)
        if flags['disable_login']:
            _logger.info("Access Management: login refused for user %s (login disabled)", self.env.user.id)
            raise AccessDenied()
        if flags['block_rpc'] and not env.get('interactive', True):
            _logger.info("Access Management: API login refused for user %s", self.env.user.id)
            raise AccessDenied()
        return auth_info


class ResUsersApikeys(models.Model):
    _inherit = 'res.users.apikeys'

    def _check_credentials(self, *, scope, key):
        uid = super()._check_credentials(scope=scope, key=key)
        if uid and self.env['access.profile'].sudo()._get_login_flags(uid)['block_rpc']:
            _logger.info("Access Management: API key refused for user %s", uid)
            return None
        return uid
