from collections import defaultdict

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import frozendict

# Models a read-only user may still write to, so that the web client keeps working
# (presence, settings, login logs, discuss membership...).
READONLY_ALWAYS_ALLOWED = frozenset({
    'res.users.settings', 'res.users.settings.volumes', 'res.users.log',
    'res.device', 'res.device.log', 'bus.presence', 'mail.presence',
    'discuss.channel.member', 'mail.notification', 'mail.link.preview',
    'web_tour.tour',
})

# Models never restricted by this module, to avoid locking anybody out of it.
NEVER_RESTRICTED = frozenset({
    'access.profile', 'access.profile.model', 'access.profile.field',
    'access.profile.domain', 'access.profile.element', 'access.ui.element',
    'access.view.type', 'ir.ui.menu', 'ir.ui.view', 'ir.model', 'ir.model.fields',
    'res.users.settings', 'res.users.log', 'res.device', 'res.device.log',
    'bus.presence', 'mail.presence',
})

EMPTY_RULES = frozendict()


class AccessProfile(models.Model):
    _name = 'access.profile'
    _description = 'Access Management: Access Profile'
    _inherit = ['mail.thread']
    _order = 'sequence, name, id'

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    sequence = fields.Integer(default=10)
    note = fields.Html('Internal Notes')
    user_ids = fields.Many2many(
        'res.users', 'access_profile_res_users_rel', 'profile_id', 'user_id',
        string='Users', domain=[('share', '=', False)], tracking=True,
        help="Users this profile applies to.")
    company_ids = fields.Many2many(
        'res.company', 'access_profile_res_company_rel', 'profile_id', 'company_id',
        string='Companies',
        help="Apply the profile only when one of these companies is the active company. "
             "Leave empty to apply it in every company.")

    # --- User level -------------------------------------------------------
    readonly_user = fields.Boolean(
        'Read-only User', tracking=True,
        help="The users can open and search records but cannot create, edit, delete or archive anything.")
    readonly_allowed_model_ids = fields.Many2many(
        'ir.model', 'access_profile_readonly_model_rel', 'profile_id', 'model_id',
        string='Still Editable Models',
        help="Exceptions to the read-only mode.")
    disable_debug = fields.Boolean('Disable Developer Mode', tracking=True)
    disable_login = fields.Boolean(
        'Disable Login', tracking=True,
        help="The users cannot log in anymore (web and API). Running sessions end at their next login.")
    block_rpc = fields.Boolean(
        'Block External API', tracking=True,
        help="Refuse XML-RPC / JSON-RPC logins and API keys for these users.")
    block_module_ops = fields.Boolean(
        'Block Apps Install / Upgrade / Uninstall', tracking=True)

    # --- Global UI --------------------------------------------------------
    hide_export_all = fields.Boolean('Hide Export (all models)')
    hide_import_all = fields.Boolean('Hide Import (all models)')
    hide_spreadsheet_all = fields.Boolean('Hide Spreadsheet Insert (all models)')
    hide_chatter_all = fields.Boolean('Hide Chatter (all models)')
    hide_send_message_all = fields.Boolean('Hide "Send message" (all models)')
    hide_log_note_all = fields.Boolean('Hide "Log note" (all models)')
    hide_activity_all = fields.Boolean('Hide "Activity" (all models)')

    # --- Lines --------------------------------------------------------------
    hidden_menu_ids = fields.Many2many(
        'ir.ui.menu', 'access_profile_hidden_menu_rel', 'profile_id', 'menu_id',
        string='Hidden Menus', help="Hidden menus also hide all their sub-menus.")
    model_line_ids = fields.One2many('access.profile.model', 'profile_id', string='Model Rules', copy=True)
    field_line_ids = fields.One2many('access.profile.field', 'profile_id', string='Field Rules', copy=True)
    domain_line_ids = fields.One2many('access.profile.domain', 'profile_id', string='Record Rules', copy=True)
    element_line_ids = fields.One2many('access.profile.element', 'profile_id', string='UI Element Rules', copy=True)

    user_count = fields.Integer(compute='_compute_counts')
    rule_count = fields.Integer(compute='_compute_counts')

    @api.depends('user_ids', 'model_line_ids', 'field_line_ids', 'domain_line_ids',
                 'element_line_ids', 'hidden_menu_ids')
    def _compute_counts(self):
        for rec in self:
            rec.user_count = len(rec.user_ids)
            rec.rule_count = (len(rec.model_line_ids) + len(rec.field_line_ids) + len(rec.domain_line_ids)
                              + len(rec.element_line_ids) + len(rec.hidden_menu_ids))

    @api.constrains('user_ids')
    def _check_users(self):
        protected = self.env.ref('base.user_root', raise_if_not_found=False)
        for rec in self:
            if protected and protected in rec.user_ids:
                raise ValidationError(_("The superuser (OdooBot) cannot be restricted."))

    # ------------------------------------------------------------------
    # Cache handling
    # ------------------------------------------------------------------
    @api.model
    def _access_suite_invalidate(self):
        """Drop every cache depending on the profiles (menus, access domains, bindings...)."""
        self.env.invalidate_all()
        self.env.transaction.invalidate_access_cache()
        self.env.transaction.invalidate_ormcache('stable')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self._access_suite_invalidate()
        return records

    def write(self, vals):
        res = super().write(vals)
        self._access_suite_invalidate()
        return res

    def unlink(self):
        res = super().unlink()
        self._access_suite_invalidate()
        return res

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_view_users(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Users'),
            'res_model': 'res.users',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.user_ids.ids)],
        }

    def action_scan_elements(self):
        models_to_scan = (self.model_line_ids.model_id | self.field_line_ids.model_id
                          | self.element_line_ids.model_id | self.domain_line_ids.model_id)
        self.env['access.ui.element'].scan_models(models_to_scan)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': _("%(count)s model(s) scanned.", count=len(models_to_scan)),
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    # ------------------------------------------------------------------
    # Rule compilation
    # ------------------------------------------------------------------
    @api.model
    def _get_rules(self):
        """Return the compiled rules of the current user in the current company."""
        env = self.env
        uid = env.uid
        if not uid or uid == 1 or env.context.get('access_suite_bypass'):
            return EMPTY_RULES
        return self._compiled_rules(uid, env.company.id)

    @api.model
    def _get_login_flags(self, uid):
        """Flags checked at authentication time (company independent)."""
        profiles = self.sudo().search([('user_ids', 'in', uid)])
        return {
            'disable_login': any(profiles.mapped('disable_login')),
            'block_rpc': any(profiles.mapped('block_rpc')),
        }

    @api.model
    @api.ormcache('uid', 'company_id', cache='stable')
    def _compiled_rules(self, uid, company_id):
        profiles = self.sudo().with_context(active_test=True).search([('user_ids', 'in', uid)])
        profiles = profiles.filtered(lambda p: not p.company_ids or company_id in p.company_ids.ids)
        if not profiles:
            return EMPTY_RULES

        any_of = lambda fname: any(profiles.mapped(fname))  # noqa: E731
        rules = {
            'readonly_user': any_of('readonly_user'),
            'readonly_allowed': frozenset(profiles.readonly_allowed_model_ids.mapped('model')),
            'disable_debug': any_of('disable_debug'),
            'block_module_ops': any_of('block_module_ops'),
            'global': frozendict({
                'no_export': any_of('hide_export_all'),
                'no_import': any_of('hide_import_all'),
                'no_spreadsheet': any_of('hide_spreadsheet_all'),
                'hide_chatter': any_of('hide_chatter_all'),
                'hide_send_message': any_of('hide_send_message_all'),
                'hide_log_note': any_of('hide_log_note_all'),
                'hide_activity': any_of('hide_activity_all'),
            }),
            'menus': frozenset(profiles.hidden_menu_ids.ids),
        }

        # model rules: boolean flags are OR-ed between profiles (most restrictive wins)
        model_rules = defaultdict(lambda: defaultdict(bool))
        flag_names = self.env['access.profile.model']._access_flag_names()
        for line in profiles.model_line_ids:
            mr = model_rules[line.model_id.model]
            for fname in flag_names:
                mr[fname] = mr[fname] or line[fname]
            mr['view_types'] = frozenset(mr['view_types'] or ()) | frozenset(line.view_type_ids.mapped('code'))
            mr['reports'] = frozenset(mr['reports'] or ()) | frozenset(line.report_ids.ids)
            mr['actions'] = frozenset(mr['actions'] or ()) | frozenset(line.action_ids.ids)
        rules['models'] = frozendict({
            model: frozendict(values) for model, values in model_rules.items()
        })

        # field rules: {model: {field: {attr: condition or True}}}
        field_rules = defaultdict(lambda: defaultdict(dict))
        for line in profiles.field_line_ids:
            for field in line.field_ids:
                fr = field_rules[line.model_id.model][field.name]
                for attr in ('invisible', 'readonly', 'required'):
                    if line[attr]:
                        cond = (line.condition or '').strip() or True
                        fr[attr] = _merge_conditions(fr.get(attr), cond)
                for attr in ('no_open', 'no_create'):
                    if line[attr]:
                        fr[attr] = True
        rules['fields'] = frozendict({
            model: frozendict({f: frozendict(v) for f, v in fields_.items()})
            for model, fields_ in field_rules.items()
        })

        # record rules: {model: {operation: (domain, ...)}}
        domain_rules = defaultdict(lambda: defaultdict(list))
        for line in profiles.domain_line_ids:
            for operation in ('read', 'write', 'create', 'unlink'):
                if line[f'perm_{operation}']:
                    domain_rules[line.model_id.model][operation].append(line.domain or '[]')
        rules['domains'] = frozendict({
            model: frozendict({op: tuple(doms) for op, doms in ops.items()})
            for model, ops in domain_rules.items()
        })

        # ui elements: {model: ((kind, key, condition), ...)}
        element_rules = defaultdict(list)
        for line in profiles.element_line_ids:
            cond = (line.condition or '').strip() or True
            for element in line.element_ids:
                element_rules[line.model_id.model].append((element.kind, element.key, cond))
            for key in filter(None, (k.strip() for k in (line.extra_keys or '').split(','))):
                element_rules[line.model_id.model].append(('any', key, cond))
        rules['elements'] = frozendict({m: tuple(v) for m, v in element_rules.items()})
        return frozendict(rules)

    @api.model
    def _get_client_rules(self):
        """Subset of the rules needed by the web client (sent in session_info)."""
        rules = self._get_rules()
        if not rules:
            return {}
        client_models = {}
        for model, values in rules['models'].items():
            flags = {k: True for k in ('no_export', 'no_import', 'no_spreadsheet', 'hide_send_message',
                                       'hide_log_note', 'hide_activity') if values.get(k)}
            if flags:
                client_models[model] = flags
        global_flags = dict(rules['global'])
        if rules['readonly_user']:
            # read-only users cannot post anyway: do not show the buttons
            global_flags.update(hide_send_message=True, hide_log_note=True, hide_activity=True)
        return {'global': global_flags, 'models': client_models}


def _merge_conditions(current, new):
    """Combine two "hide when" conditions with OR. ``True`` means always."""
    if current is True or new is True:
        return True
    if not current:
        return new
    return f"({current}) or ({new})"
