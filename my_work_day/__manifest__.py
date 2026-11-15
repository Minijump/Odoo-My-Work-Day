{
    'name': 'My Work Day',
    'version': '19.0.1.0.0',
    'category': 'Productivity',
    'summary': 'A personal daily dashboard showing the work waiting for you',
    'author': 'SJ',
    'website': 'https://github.com/Minijump/Odoo-My-Work-Day',
    # MIT, see LICENSE. Odoo's module registry has no 'MIT' value, and MIT is
    # an OSI-approved licence, which is what this value stands for.
    'license': 'Other OSI approved licence',
    # The first image is the App Store thumbnail; the full description is
    # static/description/index.html.
    'images': ['static/description/banner.png'],
    'depends': ['base', 'web'],
    'data': [
        'security/my_work_day_groups.xml',
        'security/ir.model.access.csv',
        'security/my_work_day_rules.xml',
        'views/my_work_day_actions.xml',
        'views/mwd_allowed_model_views.xml',
        'views/mwd_tile_views.xml',
        'views/mwd_dashboard_views.xml',
        'views/res_users_views.xml',
        'views/res_config_settings_views.xml',
        'views/my_work_day_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'my_work_day/static/src/**/*.js',
            'my_work_day/static/src/**/*.xml',
            'my_work_day/static/src/dashboard/dashboard.scss',
        ],
        'web.assets_web_dark': [
            'my_work_day/static/src/**/*.dark.scss',
        ],
    },
    'installable': True,
    'application': True,
}
