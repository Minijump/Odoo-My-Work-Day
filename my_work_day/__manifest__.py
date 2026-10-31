{
    'name': 'My Work Day',
    'version': '19.0.1.0.0',
    'category': 'Productivity',
    'summary': 'A personal daily dashboard showing the work waiting for you',
    'description': """
My Work Day
===========

Replaces the app switcher landing page with a personal dashboard that shows
the work actually waiting for the user: draft orders, invoices to approve,
activities due today, and anything else they care to count.

Users build their own tiles out of named filters on models an administrator
has made available. Every count and every click-through runs with the user's
own access rights, so the dashboard can never show more than the user could
already reach from the menus.
""",
    'author': 'SJ',
    'license': 'LGPL-3',
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
            'my_work_day/static/src/dashboard/**/*.js',
            'my_work_day/static/src/dashboard/**/*.xml',
            'my_work_day/static/src/dashboard/dashboard.scss',
        ],
        'web.assets_web_dark': [
            'my_work_day/static/src/dashboard/**/*.dark.scss',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': True,
}
