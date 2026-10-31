from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.translate import _


class MwdDashboard(models.Model):
    _name = 'mwd.dashboard'
    _description = 'My Work Day Dashboard'
    _order = 'sequence, id'

    name = fields.Char(required=True, default=lambda self: _("My Work Day"))
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    user_id = fields.Many2one(
        'res.users', string='Owner', required=True, ondelete='cascade',
        default=lambda self: self.env.user, index=True,
    )
    tile_ids = fields.One2many('mwd.tile', 'dashboard_id', string='Tiles')
    tile_count = fields.Integer(compute='_compute_tile_count')
    column_count = fields.Selection(
        [('2', '2 columns'), ('3', '3 columns'), ('4', '4 columns')],
        string='Columns', default='4', required=True,
        help="How many tile columns to use on a wide screen. "
             "Narrow screens always stack to a single column.",
    )
    refresh_interval = fields.Selection(
        [('0', 'Off'), ('120', 'Every 2 minutes'), ('300', 'Every 5 minutes'),
         ('900', 'Every 15 minutes')],
        string='Auto Refresh', default='0', required=True,
        help="Reload the counters on a timer. Refreshing pauses while the "
             "browser tab is in the background, so a dashboard left open "
             "overnight costs nothing.",
    )
    show_apps = fields.Boolean(
        string='Show My Apps', default=True,
        help="Show a row of shortcuts to your favourite apps at the top of the dashboard.",
    )
    starter_tiles_done = fields.Boolean(
        string='Starter Tiles Offered', default=False, copy=False,
        help="Set once this dashboard has been offered its starter tiles, so emptying "
             "it does not bring them back.",
    )

    @api.depends('tile_ids')
    def _compute_tile_count(self):
        for dashboard in self:
            dashboard.tile_count = len(dashboard.tile_ids)

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    @api.model
    def _get_or_create_for_user(self):
        """Return the current user's dashboard, building a starter one if needed."""
        dashboard = self.search([('user_id', '=', self.env.uid)], limit=1)
        if dashboard:
            return dashboard
        # A Reader may not create records, but everyone has to be able to open
        # their own dashboard, so the first one is made for them. Only the
        # writing is elevated: which models may appear on it is still decided
        # by what this user, not the superuser, is allowed to read.
        created = self.sudo().create({'user_id': self.env.uid})
        # Back to the user's own environment before filling it: _offer_starter_tiles
        # asks what this user may read, and sudo would answer "everything".
        dashboard = self.browse(created.id)
        dashboard._offer_starter_tiles()
        return dashboard

    def _offer_starter_tiles(self):
        """Fill an empty dashboard once, the first time there is anything to fill it with.

        This cannot happen only at creation. The selectable-model list starts
        empty, and an administrator usually opens the dashboard before getting
        round to filling that list -- which would leave them with an empty
        dashboard for good. So the offer is retried until it has something to
        offer, and the flag is set only once it does, which is also what stops
        a user who deletes every tile from finding them back the next morning.
        """
        self.ensure_one()
        if self.starter_tiles_done or self.tile_ids:
            return False
        available = self.env['mwd.allowed.model']._search_available()
        if not available:
            return False
        if not self.sudo()._create_starter_tiles(available):
            # Models are selectable, but none of them is one this module has a
            # suggestion for. Leave the flag alone and try again next time, in
            # case the administrator adds Sales tomorrow.
            return False
        self.sudo().starter_tiles_done = True
        return True

    def _starter_tile_blueprints(self):
        """Tiles worth offering on a brand new dashboard.

        Each entry is skipped unless its model is both installed and selectable,
        so this stays silent on a database that has none of these apps.
        Lines are (label, domain, colour condition, threshold, colour).
        """
        today = "context_today().strftime('%Y-%m-%d')"
        return [
            {
                'model': 'mail.activity',
                'name': _("My Activities"),
                'icon': 'fa-bell',
                'lines': [
                    (_("Overdue"), "[('user_id', '=', uid), ('date_deadline', '<', %s)]" % today,
                     'gt', 0, 'danger'),
                    (_("Today"), "[('user_id', '=', uid), ('date_deadline', '=', %s)]" % today,
                     'gt', 0, 'warning'),
                    (_("Planned"), "[('user_id', '=', uid), ('date_deadline', '>', %s)]" % today,
                     'none', 0, 'muted'),
                ],
            },
            {
                'model': 'sale.order',
                'name': _("Sales"),
                'icon': 'fa-shopping-cart',
                'lines': [
                    (_("Quotations"), "[('state', '=', 'draft')]", 'none', 0, 'muted'),
                    (_("Waiting for customer"), "[('state', '=', 'sent')]", 'gt', 5, 'warning'),
                ],
            },
            {
                'model': 'purchase.order',
                'name': _("Purchases"),
                'icon': 'fa-truck',
                'lines': [
                    (_("Draft requests"), "[('state', '=', 'draft')]", 'none', 0, 'muted'),
                    (_("To confirm"), "[('state', '=', 'sent')]", 'gt', 5, 'warning'),
                ],
            },
            {
                'model': 'account.move',
                'name': _("Invoicing"),
                'icon': 'fa-file-text-o',
                'lines': [
                    (_("Draft invoices"),
                     "[('move_type', '=', 'out_invoice'), ('state', '=', 'draft')]",
                     'gt', 0, 'warning'),
                    (_("Draft bills"),
                     "[('move_type', '=', 'in_invoice'), ('state', '=', 'draft')]",
                     'gt', 0, 'warning'),
                ],
            },
            {
                'model': 'project.task',
                'name': _("My Tasks"),
                'icon': 'fa-tasks',
                'lines': [
                    (_("Assigned to me"), "[('user_ids', 'in', [uid])]", 'none', 0, 'muted'),
                ],
            },
        ]

    def _create_starter_tiles(self, available):
        """Populate an empty dashboard so the user never meets a blank page.

        ``available`` is passed in rather than looked up here because this runs
        with sudo: asking the superuser which models are available would answer
        "all of them" and quietly put a tile on a model the owner cannot read.
        """
        self.ensure_one()
        by_model = {allowed.model_name: allowed for allowed in available}
        created = 0
        sequence = 0
        for blueprint in self._starter_tile_blueprints():
            allowed = by_model.get(blueprint['model'])
            if not allowed:
                continue
            sequence += 10
            self.env['mwd.tile'].create({
                'dashboard_id': self.id,
                'name': blueprint['name'],
                'icon': blueprint['icon'],
                'sequence': sequence,
                'allowed_model_id': allowed.id,
                'line_ids': [
                    (0, 0, {
                        'name': name,
                        'sequence': index * 10,
                        'domain': domain,
                        'color_condition': condition,
                        'color_threshold': threshold,
                        'color': color,
                    })
                    for index, (name, domain, condition, threshold, color)
                    in enumerate(blueprint['lines'])
                ],
            })
            created += 1
        return created

    # ------------------------------------------------------------------
    # Client payload
    # ------------------------------------------------------------------

    @api.model
    def get_dashboard_data(self, dashboard_id=None):
        """Everything the dashboard needs, in a single round trip.

        Counting happens here rather than tile by tile from the browser, so a
        dashboard of thirty filters costs one request instead of thirty.
        """
        if dashboard_id:
            dashboard = self.browse(dashboard_id).exists()
            if not dashboard:
                raise UserError(_("This dashboard no longer exists."))
            dashboard.check_access('read')
        else:
            dashboard = self._get_or_create_for_user()
            dashboard._offer_starter_tiles()

        return {
            'id': dashboard.id,
            'name': dashboard.name,
            'column_count': int(dashboard.column_count),
            'refresh_interval': int(dashboard.refresh_interval),
            'show_apps': dashboard.show_apps,
            'is_owner': dashboard.user_id.id == self.env.uid,
            'can_edit': (
                dashboard.user_id.id == self.env.uid
                and self.env.user.has_group('my_work_day.group_my_work_day_editor')
            ),
            'is_home': self._is_home_action(),
            'app_menu_ids': self.env.user.mwd_favorite_menu_ids.ids,
            'tiles': [tile._get_tile_data() for tile in dashboard.tile_ids],
        }

    @api.model
    def _is_home_action(self):
        action = self.env.ref(
            'my_work_day.action_my_work_day_dashboard', raise_if_not_found=False)
        return bool(action) and self.env.user.action_id.id == action.id

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_open_configuration(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Configure Dashboard"),
            'res_model': 'mwd.dashboard',
            'res_id': self.id,
            'views': [[False, 'form']],
            'target': 'current',
        }

    @api.model
    def action_set_as_home(self):
        """Make the dashboard this user's landing page.

        Written with sudo because ``action_id`` lives on res.users, which a
        plain internal user may not write to themselves.
        """
        action = self.env.ref('my_work_day.action_my_work_day_dashboard')
        self.env.user.sudo().action_id = action.id
        return True

    @api.model
    def action_unset_as_home(self):
        self.env.user.sudo().action_id = False
        return True
