from odoo import models, _
from odoo.exceptions import AccessError


class IrModuleModule(models.Model):
    _inherit = 'ir.module.module'

    def _access_suite_check_module_ops(self):
        if self.env.su:
            return
        rules = self.env['access.profile']._get_rules()
        if rules and rules['block_module_ops']:
            raise AccessError(_("You are not allowed to install, upgrade or uninstall applications."))

    def button_install(self):
        self._access_suite_check_module_ops()
        return super().button_install()

    def button_immediate_install(self):
        self._access_suite_check_module_ops()
        return super().button_immediate_install()

    def button_uninstall(self):
        self._access_suite_check_module_ops()
        return super().button_uninstall()

    def button_immediate_uninstall(self):
        self._access_suite_check_module_ops()
        return super().button_immediate_uninstall()

    def button_uninstall_wizard(self):
        self._access_suite_check_module_ops()
        return super().button_uninstall_wizard()

    def button_upgrade(self):
        self._access_suite_check_module_ops()
        return super().button_upgrade()

    def button_immediate_upgrade(self):
        self._access_suite_check_module_ops()
        return super().button_immediate_upgrade()
