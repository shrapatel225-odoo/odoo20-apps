import logging

from lxml import etree

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

ELEMENT_KINDS = [
    ('button', 'Button'),
    ('smart_button', 'Smart Button'),
    ('page', 'Tab / Page'),
    ('link', 'Kanban / Form Link'),
    ('filter', 'Search Filter'),
    ('groupby', 'Search Group By'),
]

SCANNED_VIEW_TYPES = ('form', 'list', 'kanban', 'search')


def element_kind(node):
    """Classify an arch node. Return None for nodes we do not manage."""
    tag = node.tag
    if tag == 'button':
        for ancestor in node.iterancestors():
            if ancestor.get('name') == 'button_box' or 'oe_button_box' in (ancestor.get('class') or ''):
                return 'smart_button'
        return 'button'
    if tag == 'page':
        return 'page'
    if tag == 'a' and node.get('type'):
        return 'link'
    if tag == 'filter':
        context = node.get('context') or ''
        return 'groupby' if 'group_by' in context else 'filter'
    return None


def element_key(node):
    """Stable identifier of an arch node: its technical name, else its label."""
    return (node.get('name') or node.get('string') or '').strip()


def element_label(node):
    label = node.get('string') or node.get('title') or node.get('aria-label') or ''
    if not label:
        label = ' '.join(t.strip() for t in node.itertext() if t.strip())
    return label.strip()[:120]


class AccessUiElement(models.Model):
    """Buttons, tabs, links and search items discovered in the views of a model.

    The catalog is filled by "Scan Views" so administrators can pick elements
    from a list instead of typing technical names.
    """
    _name = 'access.ui.element'
    _description = 'Access Management: UI Element'
    _order = 'model_id, kind, label, id'

    model_id = fields.Many2one('ir.model', required=True, index=True, ondelete='cascade')
    model_name = fields.Char(related='model_id.model', string='Model Name', store=True, index=True)
    kind = fields.Selection(ELEMENT_KINDS, required=True)
    key = fields.Char('Technical Name', required=True,
                      help="The 'name' attribute of the element, or its label when it has no name.")
    label = fields.Char()
    view_types = fields.Char(help="View types where the element was found.")

    _model_kind_key_unique = models.Constraint(
        'UNIQUE(model_id, kind, key)', 'This element already exists for the model.')

    @api.depends('kind', 'label', 'key')
    def _compute_display_name(self):
        kinds = dict(ELEMENT_KINDS)
        for rec in self:
            label = rec.label or rec.key
            suffix = f" ({rec.key})" if rec.key and rec.key != label else ''
            rec.display_name = f"[{kinds.get(rec.kind, '')}] {label}{suffix}"

    @api.model
    def scan_models(self, models_to_scan):
        """(Re)build the catalog for the given ``ir.model`` records."""
        IrView = self.env['ir.ui.view'].sudo()
        for ir_model in models_to_scan:
            if ir_model.model not in self.env:
                continue
            Model = self.env[ir_model.model].sudo()
            found = {}
            views = IrView.search([
                ('model', '=', ir_model.model),
                ('type', 'in', SCANNED_VIEW_TYPES),
                ('mode', '=', 'primary'),
            ])
            targets = [(view.id, view.type) for view in views]
            # also scan default generated views when no explicit view exists
            existing_types = {vtype for _vid, vtype in targets}
            targets += [(None, vtype) for vtype in SCANNED_VIEW_TYPES if vtype not in existing_types]
            for view_id, view_type in targets:
                try:
                    arch = Model.with_context(access_suite_bypass=True).get_view(view_id, view_type)['arch']
                except Exception:  # noqa: BLE001 - some models have no default view of a type
                    _logger.debug("Access scan: no %s view for %s", view_type, ir_model.model, exc_info=True)
                    continue
                self._collect_elements(etree.fromstring(arch), view_type, found)

            existing = self.search([('model_id', '=', ir_model.id)])
            by_key = {(rec.kind, rec.key): rec for rec in existing}
            to_create = []
            for (kind, key), (label, view_types) in found.items():
                rec = by_key.get((kind, key))
                vtypes = ','.join(sorted(view_types))
                if rec:
                    rec.write({'label': label or rec.label, 'view_types': vtypes})
                else:
                    to_create.append({
                        'model_id': ir_model.id, 'kind': kind, 'key': key,
                        'label': label, 'view_types': vtypes,
                    })
            if to_create:
                self.create(to_create)
        return True

    @api.model
    def _collect_elements(self, root, view_type, found):
        # Only scan nodes belonging to the root model (skip embedded x2many sub-views)
        def walk(node):
            for child in node:
                if not isinstance(child.tag, str):
                    continue
                if child.tag == 'field':
                    continue
                kind = element_kind(child)
                if kind:
                    key = element_key(child)
                    if key:
                        label, vtypes = found.get((kind, key), ('', set()))
                        vtypes.add(view_type)
                        found[(kind, key)] = (label or element_label(child), vtypes)
                walk(child)
        walk(root)

    def action_rescan(self):
        models_to_scan = self.mapped('model_id')
        if not models_to_scan:
            raise UserError(_("Nothing to scan."))
        self.scan_models(models_to_scan)
        return True
