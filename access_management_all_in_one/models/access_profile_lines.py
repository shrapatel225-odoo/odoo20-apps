from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.tools.safe_eval import safe_eval


class AccessProfileLineMixin(models.AbstractModel):
    _name = 'access.profile.line.mixin'
    _description = 'Access Management: Rule Line Mixin'

    profile_id = fields.Many2one('access.profile', required=True, index=True, ondelete='cascade')
    model_id = fields.Many2one('ir.model', string='Model', required=True, index=True, ondelete='cascade',
                               domain=[('transient', '=', False)])
    model_name = fields.Char(related='model_id.model', store=True, string='Model Name')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self.env['access.profile']._access_suite_invalidate()
        return records

    def write(self, vals):
        res = super().write(vals)
        self.env['access.profile']._access_suite_invalidate()
        return res

    def unlink(self):
        res = super().unlink()
        self.env['access.profile']._access_suite_invalidate()
        return res

    def _check_condition_expression(self, expression):
        """Validate a client side python expression (e.g. ``state == 'draft'``)."""
        if not expression:
            return
        try:
            compile(expression.strip(), '<condition>', 'eval')
        except SyntaxError as e:
            raise ValidationError(_("Invalid condition %(cond)r: %(err)s", cond=expression, err=e)) from e


class AccessProfileModel(models.Model):
    _name = 'access.profile.model'
    _inherit = 'access.profile.line.mixin'
    _description = 'Access Management: Model Rule'
    _order = 'model_id, id'

    readonly = fields.Boolean('Read Only', help="No create, edit or delete on this model.")
    no_create = fields.Boolean('No Create')
    no_write = fields.Boolean('No Edit')
    no_unlink = fields.Boolean('No Delete')
    no_duplicate = fields.Boolean('Hide Duplicate')
    no_archive = fields.Boolean('Hide Archive / Unarchive')
    no_export = fields.Boolean('Hide Export')
    no_import = fields.Boolean('Hide Import')
    no_spreadsheet = fields.Boolean('Hide Spreadsheet')
    hide_searchpanel = fields.Boolean('Hide Search Panel')
    hide_chatter = fields.Boolean('Hide Chatter')
    hide_send_message = fields.Boolean('Hide "Send message"')
    hide_log_note = fields.Boolean('Hide "Log note"')
    hide_activity = fields.Boolean('Hide "Activity"')
    view_type_ids = fields.Many2many(
        'access.view.type', 'access_profile_model_view_type_rel', 'line_id', 'view_type_id',
        string='Hidden Views', help="View types removed from the window actions of this model.")
    report_ids = fields.Many2many(
        'ir.actions.report', 'access_profile_model_report_rel', 'line_id', 'report_id',
        string='Hidden Reports', domain="[('model', '=', model_name)]")
    action_ids = fields.Many2many(
        'ir.actions.actions', 'access_profile_model_action_rel', 'line_id', 'action_id',
        string='Hidden Actions', domain="[('binding_model_id', '=', model_id), ('type', '!=', 'ir.actions.report')]")

    @api.model
    def _access_flag_names(self):
        return [
            'readonly', 'no_create', 'no_write', 'no_unlink', 'no_duplicate', 'no_archive',
            'no_export', 'no_import', 'no_spreadsheet', 'hide_searchpanel', 'hide_chatter',
            'hide_send_message', 'hide_log_note', 'hide_activity',
        ]

    @api.onchange('readonly')
    def _onchange_readonly(self):
        if self.readonly:
            self.no_create = self.no_write = self.no_unlink = True


class AccessProfileField(models.Model):
    _name = 'access.profile.field'
    _inherit = 'access.profile.line.mixin'
    _description = 'Access Management: Field Rule'
    _order = 'model_id, id'

    field_ids = fields.Many2many(
        'ir.model.fields', 'access_profile_field_field_rel', 'line_id', 'field_id',
        string='Fields', required=True, domain="[('model_id', '=', model_id)]")
    invisible = fields.Boolean('Invisible')
    readonly = fields.Boolean('Read Only')
    required = fields.Boolean('Required')
    no_open = fields.Boolean('No Open Link', help="Relational fields: remove the internal link button.")
    no_create = fields.Boolean('No Quick Create',
                               help="Relational fields: hide 'Create' and 'Create and edit...' in dropdowns.")
    condition = fields.Char(
        'Only When',
        help="Optional python expression evaluated on the record, e.g. state == 'sale'. "
             "Leave empty to always apply.")

    @api.constrains('condition')
    def _check_condition(self):
        for rec in self:
            rec._check_condition_expression(rec.condition)

    @api.onchange('model_id')
    def _onchange_model_id(self):
        self.field_ids = False


class AccessProfileDomain(models.Model):
    _name = 'access.profile.domain'
    _inherit = 'access.profile.line.mixin'
    _description = 'Access Management: Record Rule'
    _order = 'model_id, id'

    name = fields.Char('Description')
    domain = fields.Char(default='[]', required=True,
                         help="Records the users can work on. You can use 'user' (current user), "
                              "'company_id', 'company_ids' and 'time'.")
    perm_read = fields.Boolean(
        'Read', default=True,
        help="Also hide the records outside the domain. Careful with Contacts and Users: "
             "screens such as the chatter need to read the current user's contact and the followers.")
    perm_write = fields.Boolean('Write', default=True)
    perm_create = fields.Boolean('Create', default=True)
    perm_unlink = fields.Boolean('Delete', default=True)

    @api.constrains('domain', 'model_id')
    def _check_domain(self):
        eval_context = self.env['ir.access']._eval_context()
        for rec in self:
            if not rec.model_name or rec.model_name not in self.env:
                continue
            try:
                Domain(safe_eval(rec.domain or '[]', eval_context)).validate(self.env[rec.model_name])
            except Exception as e:  # noqa: BLE001
                raise ValidationError(_("Invalid domain on %(model)s: %(err)s",
                                        model=rec.model_id.name, err=e)) from e


class AccessProfileElement(models.Model):
    _name = 'access.profile.element'
    _inherit = 'access.profile.line.mixin'
    _description = 'Access Management: UI Element Rule'
    _order = 'model_id, id'

    element_ids = fields.Many2many(
        'access.ui.element', 'access_profile_element_ui_rel', 'line_id', 'element_id',
        string='Elements to Hide', domain="[('model_id', '=', model_id)]",
        help="Use 'Scan Views' on the profile to list the buttons, tabs, links and filters of the model.")
    extra_keys = fields.Char(
        'Other Technical Names',
        help="Comma separated names or labels of elements not found by the scan.")
    condition = fields.Char(
        'Only When',
        help="Optional python expression evaluated on the record, e.g. state != 'draft'. "
             "Leave empty to always hide.")

    @api.constrains('condition')
    def _check_condition(self):
        for rec in self:
            rec._check_condition_expression(rec.condition)

    @api.constrains('element_ids', 'extra_keys')
    def _check_not_empty(self):
        for rec in self:
            if not rec.element_ids and not (rec.extra_keys or '').strip():
                raise ValidationError(_("Select at least one element to hide for %s.", rec.model_id.name))

    @api.onchange('model_id')
    def _onchange_model_id(self):
        self.element_ids = False
        if self.model_id and not self.env['access.ui.element'].search_count(
                [('model_id', '=', self.model_id.id)], limit=1):
            self.env['access.ui.element'].scan_models(self.model_id)
