{
    'name': 'All In One Access Management | Hide Menu, Field, Button, Tab, Chatter | Read Only User | Restrict Records',
    'summary': """
        Access management for Odoo 20: user wise access rights, hide menu, hide submenu,
        hide field, read only field, required field, hide button, hide smart button, hide tab / page,
        hide filter and group by, hide chatter, hide send message / log note / activity,
        read only user, restrict create / edit / delete, hide export / import / duplicate / archive,
        hide report and action, hide view type, record level domain restriction,
        disable developer mode, disable login, block XML-RPC / JSON-RPC, block module install.
    """,
    'description': """
All In One Access Management
============================
Manage user access from a single screen using Access Profiles.
    """,
    'version': '20.0.1.0.0',
    'category': 'Extra Tools',
    'author': 'Donika Enterprise',
    'maintainer': 'Donika Enterprise',
    'support': 'shra.patel225@gmail.com',
    'license': 'OPL-1',
    'price': 200.0,
    'currency': 'EUR',
    'depends': ['base', 'web', 'mail', 'base_import'],
    'data': [
        'security/access_security.xml',
        'security/ir.access.csv',
        'data/access_view_type_data.xml',
        'views/access_ui_element_views.xml',
        'views/access_profile_views.xml',
        'views/res_users_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'access_management_all_in_one/static/src/js/access_rules.js',
            'access_management_all_in_one/static/src/js/list_controller_patch.js',
            'access_management_all_in_one/static/src/js/cog_menu_patch.js',
            'access_management_all_in_one/static/src/js/chatter_patch.js',
            'access_management_all_in_one/static/src/xml/chatter.xml',
        ],
    },
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': True,
    'auto_install': False,
}
