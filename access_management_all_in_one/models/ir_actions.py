from odoo import api, models, _
from odoo.exceptions import AccessError


class IrActionsActions(models.Model):
    _inherit = 'ir.actions.actions'

    @api.model
    def get_bindings(self, model_name):
        result = super().get_bindings(model_name)
        rules = self.env['access.profile']._get_rules() if not self.env.su else {}
        model_rule = rules and rules['models'].get(model_name)
        if not model_rule:
            return result
        hidden = {'report': model_rule.get('reports') or frozenset(),
                  'action': model_rule.get('actions') or frozenset()}
        filtered = {}
        for binding_type, actions in result.items():
            to_hide = hidden.get(binding_type)
            if to_hide:
                actions = [action for action in actions if action.get('id') not in to_hide]
            if actions:
                filtered[binding_type] = actions
        return filtered


class IrActionsActWindow(models.Model):
    _inherit = 'ir.actions.act_window'

    def _get_action_dict(self):
        result = super()._get_action_dict()
        rules = self.env['access.profile']._get_rules()
        model_rule = rules and rules['models'].get(result.get('res_model'))
        hidden_types = model_rule and model_rule.get('view_types')
        if not hidden_types:
            return result
        views = [view for view in result.get('views') or [] if view[1] not in hidden_types]
        modes = [mode for mode in (result.get('view_mode') or '').split(',') if mode and mode not in hidden_types]
        if views and modes:  # never leave an action without any view
            result['views'] = views
            result['view_mode'] = ','.join(modes)
        return result


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    @api.model
    def _render(self, report_ref, res_ids, data=None):
        if not self.env.su:
            rules = self.env['access.profile']._get_rules()
            if rules:
                report = self._get_report(report_ref)
                model_rule = rules['models'].get(report.model) or {}
                if report.id in (model_rule.get('reports') or ()):
                    raise AccessError(_("You are not allowed to print the report “%s”.", report.name))
        return super()._render(report_ref, res_ids, data=data)
