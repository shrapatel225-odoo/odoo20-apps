from odoo import models


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    def _filter_visible_menus(self):
        menus = super()._filter_visible_menus()
        if self.env.su:
            return menus
        rules = self.env['access.profile']._get_rules()
        hidden_ids = rules and rules['menus']
        if not hidden_ids:
            return menus
        hidden = {str(menu_id) for menu_id in hidden_ids}

        def is_hidden(menu):
            # parent_path is "1/5/42/": hide the menu when it or any ancestor is hidden
            return any(part in hidden for part in (menu.sudo().parent_path or '').split('/') if part)

        return menus.filtered(lambda menu: not is_hidden(menu))
