from odoo import models
from odoo.http import request


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _handle_debug(cls):
        super()._handle_debug()
        if not request.session.debug or not request.session.uid:
            return
        try:
            # some routes (e.g. /odoo) are auth='none': use the session user explicitly
            env = request.env(user=request.session.uid)
            rules = env['access.profile']._get_rules()
        except Exception:  # noqa: BLE001 - never block a request because of this check
            return
        if rules and rules['disable_debug']:
            request.session.debug = ''

    def session_info(self):
        result = super().session_info()
        if request.session.uid:
            result['access_suite'] = self.env['access.profile']._get_client_rules()
            rules = self.env['access.profile']._get_rules()
            if rules and rules['global']['no_export']:
                result.setdefault('groups', {})['base.group_allow_export'] = False
        return result
