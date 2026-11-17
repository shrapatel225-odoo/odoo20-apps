import ast
import logging

from lxml import etree

from odoo import api, models, _
from odoo.exceptions import AccessError, UserError
from odoo.fields import Domain
from odoo.tools.safe_eval import safe_eval
from odoo.tools.view_validation import get_expression_field_names

from .access_profile import NEVER_RESTRICTED, READONLY_ALWAYS_ALLOWED, _merge_conditions
from .access_ui_element import element_key, element_kind

_logger = logging.getLogger(__name__)

SUB_VIEW_TAGS = ('list', 'form', 'kanban', 'graph', 'calendar', 'pivot', 'card')
WRITE_OPERATIONS = {'write': 'no_write', 'create': 'no_create', 'unlink': 'no_unlink'}


class Base(models.AbstractModel):
    _inherit = 'base'

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _access_suite_rules(self):
        """Compiled rules of the current user, or an empty mapping."""
        if self.env.su or self._name in NEVER_RESTRICTED:
            return {}
        try:
            return self.env['access.profile']._get_rules()
        except KeyError:  # registry not fully loaded (module being installed)
            return {}

    def _access_suite_model_rule(self, flag):
        rules = self._access_suite_rules()
        if not rules:
            return False
        return bool(rules['models'].get(self._name, {}).get(flag))

    # ------------------------------------------------------------------
    # Server side security: model and record access
    # ------------------------------------------------------------------
    @api.model
    def _access_domain(self, operation):
        domain = super()._access_domain(operation)
        rules = self._access_suite_rules()
        if not rules or self._transient:
            return domain

        if operation in WRITE_OPERATIONS:
            if (rules['readonly_user'] and self._name not in READONLY_ALWAYS_ALLOWED
                    and self._name not in rules['readonly_allowed']):
                return Domain.FALSE
            model_rule = rules['models'].get(self._name)
            if model_rule and (model_rule.get('readonly') or model_rule.get(WRITE_OPERATIONS[operation])):
                return Domain.FALSE

        domains = rules['domains'].get(self._name, {}).get(operation)
        if domains:
            domain &= self._access_suite_eval_domains(domains)
        return domain

    @api.model
    def _access_suite_eval_domains(self, domain_strings):
        cache = self.env.cr.cache.setdefault('access_suite_domains', {})
        key = (self.env.uid, self.env.company.id, self._name, domain_strings)
        if key not in cache:
            eval_context = self.env['ir.access']._eval_context()
            result = Domain.TRUE
            for domain_string in domain_strings:
                try:
                    result &= Domain(safe_eval(domain_string, eval_context))
                except Exception:  # noqa: BLE001 - a broken rule must deny, not crash
                    _logger.warning("Access Management: invalid domain %r on %s", domain_string, self._name)
                    result = Domain.FALSE
            cache[key] = result
        return cache[key]

    def copy(self, default=None):
        if self._access_suite_model_rule('no_duplicate'):
            raise AccessError(_("You are not allowed to duplicate %s records.", self._description))
        return super().copy(default=default)

    def action_archive(self):
        if self._access_suite_model_rule('no_archive'):
            raise AccessError(_("You are not allowed to archive %s records.", self._description))
        return super().action_archive()

    def action_unarchive(self):
        if self._access_suite_model_rule('no_archive'):
            raise AccessError(_("You are not allowed to unarchive %s records.", self._description))
        return super().action_unarchive()

    def export_data(self, fields_to_export):
        rules = self._access_suite_rules()
        if rules and (rules['global']['no_export'] or rules['models'].get(self._name, {}).get('no_export')):
            raise UserError(_("You are not allowed to export %s records.", self._description))
        return super().export_data(fields_to_export)

    @api.model
    def load(self, fields, data):
        rules = self._access_suite_rules()
        if rules and (rules['global']['no_import'] or rules['models'].get(self._name, {}).get('no_import')):
            raise UserError(_("You are not allowed to import %s records.", self._description))
        return super().load(fields, data)

    # ------------------------------------------------------------------
    # Field description
    # ------------------------------------------------------------------
    @api.model
    def fields_get(self, allfields=None, attributes=None):
        res = super().fields_get(allfields=allfields, attributes=attributes)
        rules = self._access_suite_rules()
        if not rules:
            return res
        if rules['models'].get(self._name, {}).get('no_archive') or not self.browse().has_access('write'):
            # the web client hides archive/unarchive when 'active' is readonly
            for fname in ('active', 'x_active'):
                if fname in res and (attributes is None or 'readonly' in attributes):
                    res[fname]['readonly'] = True
        for fname, frule in rules['fields'].get(self._name, {}).items():
            if fname in res and frule.get('readonly') is True and (attributes is None or 'readonly' in attributes):
                res[fname]['readonly'] = True
        return res

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------
    @api.model
    def get_view(self, view_id=None, view_type='form', **options):
        result = super().get_view(view_id, view_type, **options)
        rules = self._access_suite_rules()
        if not rules:
            return result
        try:
            root = etree.fromstring(result['arch'])
            extra_fields = {}
            self._access_suite_process_view(root, self._name, rules, extra_fields, is_root=True)
            result['arch'] = etree.tostring(root, encoding='unicode')
            if extra_fields:
                models_info = {model: tuple(names) for model, names in result['models'].items()}
                for model, names in extra_fields.items():
                    models_info[model] = tuple(set(models_info.get(model, ())) | names)
                result['models'] = models_info
        except Exception:  # noqa: BLE001 - never break a view because of an access rule
            _logger.exception("Access Management: could not apply rules on %s %s view", self._name, view_type)
        return result

    @api.model
    def _access_suite_process_view(self, root, model_name, rules, extra_fields, is_root=False):
        model_rule = rules['models'].get(model_name, {})
        global_rules = rules['global']
        field_rules = rules['fields'].get(model_name, {})
        element_rules = rules['elements'].get(model_name, ())
        view_tag = root.tag
        Model = self.env[model_name]

        # root attributes
        if view_tag in ('list', 'kanban', 'form'):
            if model_rule.get('no_duplicate'):
                root.set('duplicate', '0')
            if model_rule.get('no_import') or global_rules['no_import']:
                root.set('import', '0')
            if view_tag == 'list' and (model_rule.get('no_export') or global_rules['no_export']):
                root.set('export_xlsx', '0')

        # chatter
        if view_tag == 'form' and (model_rule.get('hide_chatter') or global_rules['hide_chatter']):
            for chatter in root.xpath('.//chatter'):
                chatter.getparent().remove(chatter)

        # search panel
        if view_tag == 'search' and model_rule.get('hide_searchpanel'):
            for panel in root.xpath('./searchpanel'):
                root.remove(panel)

        needed_fields = set()
        # record-based conditions only make sense on the main model of a record view
        cond_ok = is_root and view_tag not in ('search',)

        def walk(node):
            for child in list(node):
                if not isinstance(child.tag, str):
                    continue
                if child.tag == 'field':
                    self._access_suite_apply_field(child, view_tag, field_rules, cond_ok, needed_fields)
                    field = Model._fields.get(child.get('name'))
                    for sub in child:
                        if (isinstance(sub.tag, str) and sub.tag in SUB_VIEW_TAGS
                                and field is not None and field.relational):
                            self._access_suite_process_view(sub, field.comodel_name, rules, extra_fields)
                    continue
                if child.tag == 'groupby':
                    field = Model._fields.get(child.get('name'))
                    if field is not None and field.relational:
                        self._access_suite_process_view(child, field.comodel_name, rules, extra_fields)
                    continue
                if element_rules:
                    self._access_suite_apply_element(child, element_rules, cond_ok, needed_fields)
                walk(child)

        walk(root)

        # fields used in conditions must be present in the view
        if cond_ok and needed_fields:
            present = _root_level_field_names(root)
            missing = {f for f in needed_fields if f in Model._fields and f not in present}
            for fname in sorted(missing):
                attrs = {'name': fname, 'readonly': 'True'}
                attrs['column_invisible' if view_tag == 'list' else 'invisible'] = 'True'
                node = etree.SubElement(root, 'field', attrs)
                node.tail = '\n'
            if missing:
                extra_fields.setdefault(model_name, set()).update(missing)
        return root

    @api.model
    def _access_suite_apply_field(self, node, view_tag, field_rules, is_root, needed_fields):
        frule = field_rules.get(node.get('name'))
        if not frule:
            return
        for attr in ('invisible', 'readonly', 'required'):
            cond = frule.get(attr)
            if not cond:
                continue
            if cond is not True and not is_root:
                continue  # conditions are only evaluated on the main model
            if cond is not True:
                needed_fields.update(get_expression_field_names(cond))
            if attr == 'invisible' and view_tag == 'list' and cond is True:
                node.set('column_invisible', 'True')
            elif attr == 'invisible' and view_tag == 'search':
                node.set('invisible', 'True')
            else:
                expression = 'True' if cond is True else cond
                current = node.get(attr)
                node.set(attr, _merge_attr(current, expression))
        if frule.get('no_open') or frule.get('no_create'):
            options = _parse_options(node.get('options'))
            if options is not None:
                if frule.get('no_open'):
                    options['no_open'] = True
                if frule.get('no_create'):
                    options['no_create'] = True
                    options['no_quick_create'] = True
                    options['no_create_edit'] = True
                node.set('options', repr(options))

    @api.model
    def _access_suite_apply_element(self, node, element_rules, is_root, needed_fields):
        kind = element_kind(node)
        if not kind:
            return
        key = element_key(node)
        label = (node.get('string') or '').strip()
        hide = False
        for rule_kind, rule_key, cond in element_rules:
            if rule_kind not in ('any', kind):
                continue
            if rule_key not in (key, label):
                continue
            if cond is not True and not is_root:
                continue
            hide = _merge_conditions(hide, cond)
        if not hide:
            return
        if hide is True:
            node.set('invisible', 'True')
        else:
            needed_fields.update(get_expression_field_names(hide))
            node.set('invisible', _merge_attr(node.get('invisible'), hide))


def _root_level_field_names(root):
    """Names of the fields of the view's own model (fields inside x2many sub-views are ignored)."""
    names = set()

    def walk(node):
        for child in node:
            if not isinstance(child.tag, str):
                continue
            if child.tag == 'field':
                names.add(child.get('name'))
                continue  # do not descend into embedded sub-views
            if child.tag == 'groupby':
                continue
            walk(child)

    walk(root)
    return names


def _merge_attr(current, expression):
    current = (current or '').strip()
    if not current or current in ('0', 'False'):
        return expression
    if current in ('1', 'True') or expression == 'True':
        return 'True'
    return f"({current}) or ({expression})"


def _parse_options(options):
    if not options:
        return {}
    try:
        value = ast.literal_eval(options)
    except (ValueError, SyntaxError):
        return None  # dynamic options: leave untouched
    return dict(value) if isinstance(value, dict) else None
