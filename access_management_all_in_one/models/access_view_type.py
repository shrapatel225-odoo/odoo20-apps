from odoo import fields, models


class AccessViewType(models.Model):
    """Catalog of view types that can be removed from window actions."""
    _name = 'access.view.type'
    _description = 'Access Management: View Type'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, help="Technical view type, e.g. list, kanban, pivot.")
    sequence = fields.Integer(default=10)

    _code_unique = models.Constraint('UNIQUE(code)', 'The view type code must be unique.')
