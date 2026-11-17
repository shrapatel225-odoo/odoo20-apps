from lxml import etree

from odoo.exceptions import AccessDenied, AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestAccessProfile(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(
            cls.env, login='restricted_user', password='restricted_user_pwd',
            groups='base.group_user,base.group_partner_manager,base.group_allow_export',
        )
        cls.other_user = new_test_user(
            cls.env, login='free_user', groups='base.group_user,base.group_partner_manager',
        )
        cls.partner_model = cls.env['ir.model']._get('res.partner')
        cls.partner_a = cls.env['res.partner'].create({'name': 'Alpha', 'is_company': True})
        cls.partner_b = cls.env['res.partner'].create({'name': 'Beta', 'is_company': False})
        cls.profile = cls.env['access.profile'].create({
            'name': 'Test profile',
            'user_ids': [(6, 0, cls.user.ids)],
        })

    def _partner(self, user=None):
        return self.env['res.partner'].with_user(user or self.user)

    def _arch(self, view_type='form', user=None):
        result = self._partner(user).get_view(view_type=view_type)
        return etree.fromstring(result['arch']), result

    # ------------------------------------------------------------------
    def test_model_crud_restriction(self):
        Partner = self._partner()
        self.assertTrue(Partner.has_access('create'))
        self.profile.model_line_ids = [(0, 0, {
            'model_id': self.partner_model.id, 'no_create': True, 'no_unlink': True,
        })]
        self.assertFalse(Partner.has_access('create'))
        self.assertFalse(Partner.has_access('unlink'))
        self.assertTrue(Partner.has_access('write'))
        with self.assertRaises(AccessError):
            Partner.create({'name': 'Gamma'})
        # other users are not affected
        self.assertTrue(self._partner(self.other_user).has_access('create'))
        # the form view reflects it
        root, _res = self._arch('form')
        self.assertEqual(root.get('create'), 'False')
        self.assertEqual(root.get('delete'), 'False')

    def test_readonly_user(self):
        self.profile.readonly_user = True
        Partner = self._partner()
        self.assertTrue(Partner.has_access('read'))
        for operation in ('create', 'write', 'unlink'):
            self.assertFalse(Partner.has_access(operation), operation)
        with self.assertRaises(AccessError):
            self.partner_a.with_user(self.user).write({'name': 'Changed'})
        # exceptions are honoured
        self.profile.readonly_allowed_model_ids = [(6, 0, self.partner_model.ids)]
        self.assertTrue(Partner.has_access('write'))

    def test_domain_rule(self):
        self.profile.domain_line_ids = [(0, 0, {
            'model_id': self.partner_model.id,
            'domain': "[('name', '=', 'Alpha')]",
            'perm_read': True, 'perm_write': False, 'perm_create': False, 'perm_unlink': False,
        })]
        found = self._partner().search([('id', 'in', (self.partner_a | self.partner_b).ids)])
        self.assertEqual(found, self.partner_a)
        found_other = self._partner(self.other_user).search([('id', 'in', (self.partner_a | self.partner_b).ids)])
        self.assertEqual(len(found_other), 2)

    def test_company_scope(self):
        other_company = self.env['res.company'].create({'name': 'Other Co'})
        self.profile.write({
            'company_ids': [(6, 0, other_company.ids)],
            'model_line_ids': [(0, 0, {'model_id': self.partner_model.id, 'no_create': True})],
        })
        # current company is not in the profile scope: no restriction
        self.assertTrue(self._partner().has_access('create'))

    def test_field_rules(self):
        fields_ = self.env['ir.model.fields'].search([
            ('model', '=', 'res.partner'), ('name', 'in', ('email', 'phone', 'website'))])
        by_name = {f.name: f for f in fields_}
        self.profile.field_line_ids = [
            (0, 0, {'model_id': self.partner_model.id, 'field_ids': [(6, 0, by_name['email'].ids)],
                    'invisible': True}),
            (0, 0, {'model_id': self.partner_model.id, 'field_ids': [(6, 0, by_name['phone'].ids)],
                    'readonly': True}),
            (0, 0, {'model_id': self.partner_model.id, 'field_ids': [(6, 0, by_name['website'].ids)],
                    'required': True, 'condition': "is_company"}),
        ]
        root, _res = self._arch('form')
        for node in root.xpath("//field[@name='email']"):
            self.assertIn('True', node.get('invisible'))
        for node in root.xpath("//field[@name='phone']"):
            self.assertIn('True', node.get('readonly'))
        website_nodes = root.xpath("//field[@name='website']")
        self.assertTrue(website_nodes)
        self.assertTrue(any('is_company' in (n.get('required') or '') for n in website_nodes))
        # list view: invisible becomes column_invisible
        root, _res = self._arch('list')
        for node in root.xpath("//field[@name='email']"):
            self.assertEqual(node.get('column_invisible'), 'True')
        # free user view untouched
        root, _res = self._arch('form', self.other_user)
        self.assertFalse(any('True' == n.get('invisible') for n in root.xpath("//field[@name='email']")))

    def test_condition_adds_missing_field(self):
        field = self.env['ir.model.fields']._get('res.partner', 'website')
        self.profile.field_line_ids = [(0, 0, {
            'model_id': self.partner_model.id, 'field_ids': [(6, 0, field.ids)],
            'readonly': True, 'condition': "write_date",
        })]
        root, result = self._arch('form')
        self.assertTrue(root.xpath("/form/field[@name='write_date']"))
        self.assertIn('write_date', result['models']['res.partner'])

    def test_condition_field_only_in_subview(self):
        # 'is_company' is used inside the contacts sub-view of the partner form:
        # it must still be added at the root level for the condition to evaluate
        field = self.env['ir.model.fields']._get('res.partner', 'website')
        self.profile.field_line_ids = [(0, 0, {
            'model_id': self.partner_model.id, 'field_ids': [(6, 0, field.ids)],
            'required': True, 'condition': "is_company",
        })]
        root, _result = self._arch('form')
        self.assertTrue(root.xpath("/form//field[@name='is_company'][not(ancestor::field)]"))

    def test_ui_elements_scan_and_hide(self):
        Element = self.env['access.ui.element']
        Element.scan_models(self.partner_model)
        page = Element.search([('model_id', '=', self.partner_model.id), ('kind', '=', 'page'),
                               ('key', '=', 'internal_notes')])
        self.assertTrue(page, "the Notes page of the partner form should be found by the scan")
        self.profile.element_line_ids = [(0, 0, {
            'model_id': self.partner_model.id, 'element_ids': [(6, 0, page.ids)],
        })]
        root, _res = self._arch('form')
        node = root.xpath("//page[@name='internal_notes']")[0]
        self.assertEqual(node.get('invisible'), 'True')

    def test_chatter_and_actions_menu(self):
        self.profile.model_line_ids = [(0, 0, {
            'model_id': self.partner_model.id, 'hide_chatter': True, 'no_duplicate': True,
            'no_import': True, 'no_export': True, 'no_archive': True,
        })]
        root, _res = self._arch('form')
        self.assertFalse(root.xpath('//chatter'))
        self.assertEqual(root.get('duplicate'), '0')
        root, _res = self._arch('list')
        self.assertEqual(root.get('import'), '0')
        self.assertEqual(root.get('export_xlsx'), '0')
        fields_info = self._partner().fields_get(['active'], ['readonly'])
        self.assertTrue(fields_info['active']['readonly'])
        with self.assertRaises(UserError):
            self._partner().browse(self.partner_a.id).export_data(['name'])
        with self.assertRaises(AccessError):
            self.partner_a.with_user(self.user).copy()
        with self.assertRaises(AccessError):
            self.partner_a.with_user(self.user).action_archive()

    def test_hidden_menu(self):
        menu = self.env.ref('base.menu_administration', raise_if_not_found=False) \
            or self.env['ir.ui.menu'].search([('parent_id', '=', False)], limit=1)
        child = self.env['ir.ui.menu'].create({'name': 'Child test menu', 'parent_id': menu.id})
        Menu = self.env['ir.ui.menu'].with_user(self.user)
        self.profile.hidden_menu_ids = [(6, 0, menu.ids)]
        visible = (menu | child).with_user(self.user)._filter_visible_menus()
        self.assertFalse(visible & (menu | child))
        self.assertNotIn(menu.id, Menu.load_menus(False))

    def test_hidden_view_types_and_bindings(self):
        list_type = self.env.ref('access_management_all_in_one.view_type_kanban')
        action = self.env['ir.actions.act_window'].create({
            'name': 'Partners test', 'res_model': 'res.partner', 'view_mode': 'kanban,list,form',
        })
        self.profile.model_line_ids = [(0, 0, {
            'model_id': self.partner_model.id, 'view_type_ids': [(6, 0, list_type.ids)],
        })]
        result = action.with_user(self.user).sudo()._get_action_dict()
        self.assertNotIn('kanban', result['view_mode'])
        self.assertIn('list', result['view_mode'])

    def test_disable_login_and_rpc(self):
        env = {'interactive': True}
        credential = {'type': 'password', 'login': 'restricted_user', 'password': 'restricted_user_pwd'}
        self.user.with_user(self.user)._check_credentials(credential, env)
        self.profile.block_rpc = True
        self.user.with_user(self.user)._check_credentials(credential, env)
        with self.assertRaises(AccessDenied):
            self.user.with_user(self.user)._check_credentials(credential, {'interactive': False})
        self.profile.disable_login = True
        with self.assertRaises(AccessDenied):
            self.user.with_user(self.user)._check_credentials(credential, env)

    def test_block_module_ops(self):
        self.profile.block_module_ops = True
        module = self.env['ir.module.module'].search([('state', '=', 'uninstalled')], limit=1)
        with self.assertRaises(AccessError):
            module.with_user(self.user)._access_suite_check_module_ops()

    def test_session_client_rules(self):
        self.profile.write({
            'hide_send_message_all': True,
            'model_line_ids': [(0, 0, {'model_id': self.partner_model.id, 'no_spreadsheet': True})],
        })
        client = self.env['access.profile'].with_user(self.user)._get_client_rules()
        self.assertTrue(client['global']['hide_send_message'])
        self.assertTrue(client['models']['res.partner']['no_spreadsheet'])
        self.assertEqual(self.env['access.profile'].with_user(self.other_user)._get_client_rules(), {})

    def test_archived_profile_is_ignored(self):
        self.profile.model_line_ids = [(0, 0, {'model_id': self.partner_model.id, 'no_create': True})]
        self.assertFalse(self._partner().has_access('create'))
        self.profile.active = False
        self.assertTrue(self._partner().has_access('create'))
