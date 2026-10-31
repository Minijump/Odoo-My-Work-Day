from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMyWorkDay(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.group_user = cls.env.ref('base.group_user')
        cls.alice = cls.env['res.users'].create({
            'name': 'Alice', 'login': 'mwd_alice',
            'group_ids': [(6, 0, [cls.group_user.id])],
        })
        cls.bob = cls.env['res.users'].create({
            'name': 'Bob', 'login': 'mwd_bob',
            'group_ids': [(6, 0, [cls.group_user.id])],
        })

        # res.partner is always present, so the suite does not depend on which
        # business apps the database happens to have installed.
        cls.partner_model = cls.env['ir.model']._get('res.partner')
        cls.allowed_partner = cls.env['mwd.allowed.model'].search(
            [('model_id', '=', cls.partner_model.id)], limit=1)
        if not cls.allowed_partner:
            cls.allowed_partner = cls.env['mwd.allowed.model'].create({
                'model_id': cls.partner_model.id,
            })

        cls.env['res.partner'].create([
            {'name': 'MWD Company A', 'is_company': True},
            {'name': 'MWD Company B', 'is_company': True},
            {'name': 'MWD Person C', 'is_company': False},
        ])

    def _dashboard_for(self, user):
        return self.env['mwd.dashboard'].with_user(user)._get_or_create_for_user()

    def _counter_tile(self, user, lines, **values):
        dashboard = self._dashboard_for(user)
        return self.env['mwd.tile'].with_user(user).create({
            'dashboard_id': dashboard.id,
            'name': values.pop('name', 'Partners'),
            'allowed_model_id': self.allowed_partner.id,
            'line_ids': [(0, 0, line) for line in lines],
            **values,
        })

    # ------------------------------------------------------------------
    # Counting
    # ------------------------------------------------------------------

    def test_counter_counts_match_the_orm(self):
        tile = self._counter_tile(self.alice, [
            {'name': 'Companies', 'domain': "[('is_company', '=', True)]"},
            {'name': 'Everyone', 'domain': "[]"},
        ])
        data = tile._get_tile_data()
        self.assertFalse(data['error'])
        counts = {line['name']: line['count'] for line in data['lines']}
        self.assertEqual(
            counts['Companies'],
            self.env['res.partner'].with_user(self.alice).search_count(
                [('is_company', '=', True)]),
        )
        self.assertEqual(
            counts['Everyone'],
            self.env['res.partner'].with_user(self.alice).search_count([]),
        )

    def test_base_domain_narrows_every_line(self):
        tile = self._counter_tile(
            self.alice,
            [{'name': 'All', 'domain': "[]"}],
            base_domain="[('is_company', '=', True)]",
        )
        data = tile._get_tile_data()
        self.assertEqual(
            data['lines'][0]['count'],
            self.env['res.partner'].search_count([('is_company', '=', True)]),
        )

    def test_click_through_domain_returns_the_same_records(self):
        """The number on screen and the list behind it must agree."""
        tile = self._counter_tile(
            self.alice, [{'name': 'Companies', 'domain': "[('is_company', '=', True)]"}])
        line = tile.line_ids[0]
        shown = tile._get_tile_data()['lines'][0]['count']
        action = tile.with_user(self.alice).action_open_line(line.id)
        self.assertEqual(action['res_model'], 'res.partner')
        self.assertEqual(
            shown,
            self.env['res.partner'].with_user(self.alice).search_count(action['domain']),
        )

    def test_uid_resolves_to_the_reader(self):
        """A domain written with `uid` must count for whoever is looking."""
        tile = self._counter_tile(
            self.alice, [{'name': 'Mine', 'domain': "[('user_id', '=', uid)]"}])
        self.env['res.partner'].create({'name': 'Alice Partner', 'user_id': self.alice.id})
        data = tile.with_user(self.alice)._get_tile_data()
        self.assertEqual(data['lines'][0]['count'], 1)

    def test_hide_empty_lines_and_total(self):
        tile = self._counter_tile(
            self.alice,
            [
                {'name': 'Companies', 'domain': "[('is_company', '=', True)]"},
                {'name': 'Impossible', 'domain': "[('name', '=', 'no-such-partner')]"},
            ],
            hide_empty_lines=True, show_total=True,
        )
        data = tile._get_tile_data()
        self.assertEqual([line['name'] for line in data['lines']], ['Companies'])
        # The total counts every line, including the ones hidden from view.
        self.assertEqual(data['total'], data['lines'][0]['count'])

    # ------------------------------------------------------------------
    # Colour rules
    # ------------------------------------------------------------------

    def test_colour_rules(self):
        line = self._counter_tile(self.alice, [{
            'name': 'Companies', 'domain': "[]",
            'color_condition': 'gt', 'color_threshold': 5, 'color': 'danger',
        }]).line_ids[0]
        self.assertEqual(line._line_color(6), 'danger')
        self.assertEqual(line._line_color(5), 'muted')
        line.color_condition = 'ge'
        self.assertEqual(line._line_color(5), 'danger')
        line.color_condition = 'lt'
        self.assertEqual(line._line_color(4), 'danger')
        self.assertEqual(line._line_color(5), 'muted')
        line.color_condition = 'eq'
        self.assertEqual(line._line_color(5), 'danger')
        line.color_condition = 'none'
        self.assertEqual(line._line_color(999), 'muted')

    # ------------------------------------------------------------------
    # Breakdown
    # ------------------------------------------------------------------

    def test_breakdown_on_boolean_field(self):
        field = self.env['ir.model.fields']._get('res.partner', 'is_company')
        tile = self.env['mwd.tile'].with_user(self.alice).create({
            'dashboard_id': self._dashboard_for(self.alice).id,
            'name': 'By kind', 'tile_type': 'breakdown',
            'allowed_model_id': self.allowed_partner.id,
            'group_field_id': field.id,
        })
        data = tile._get_tile_data()
        self.assertFalse(data['error'])
        self.assertTrue(data['bars'])
        # Each bar's own domain must return exactly the records it claims.
        for bar in data['bars']:
            action = tile.action_open_group(bar['domain'])
            self.assertEqual(
                bar['count'],
                self.env['res.partner'].with_user(self.alice).search_count(action['domain']),
                'bar %r does not match its own filter' % bar['label'],
            )

    def test_breakdown_on_date_field_needs_no_manual_granularity(self):
        """Odoo 19 refuses a bare date groupby, so the tile supplies one."""
        field = self.env['ir.model.fields']._get('res.partner', 'create_date')
        tile = self.env['mwd.tile'].with_user(self.alice).create({
            'dashboard_id': self._dashboard_for(self.alice).id,
            'name': 'By month', 'tile_type': 'breakdown',
            'allowed_model_id': self.allowed_partner.id,
            'group_field_id': field.id,
            'group_granularity': 'month',
        })
        data = tile._get_tile_data()
        self.assertFalse(data['error'])
        self.assertTrue(data['bars'])

    def test_breakdown_respects_the_bar_limit(self):
        field = self.env['ir.model.fields']._get('res.partner', 'name')
        tile = self.env['mwd.tile'].with_user(self.alice).create({
            'dashboard_id': self._dashboard_for(self.alice).id,
            'name': 'By name', 'tile_type': 'breakdown',
            'allowed_model_id': self.allowed_partner.id,
            'group_field_id': field.id, 'group_limit': 3,
        })
        self.assertLessEqual(len(tile._get_tile_data()['bars']), 3)

    # ------------------------------------------------------------------
    # Agenda
    # ------------------------------------------------------------------

    def test_agenda_lists_only_today(self):
        field = self.env['ir.model.fields']._get('res.partner', 'create_date')
        tile = self.env['mwd.tile'].with_user(self.alice).create({
            'dashboard_id': self._dashboard_for(self.alice).id,
            'name': 'Created today', 'tile_type': 'agenda',
            'allowed_model_id': self.allowed_partner.id,
            'date_field_id': field.id, 'agenda_limit': 50,
        })
        data = tile._get_tile_data()
        self.assertFalse(data['error'])
        start, end, _today = tile._today_bounds()
        self.assertEqual(
            data['total'],
            self.env['res.partner'].with_user(self.alice).search_count([
                ('create_date', '>=', start), ('create_date', '<', end),
            ]),
        )

    def test_agenda_window_follows_the_users_timezone(self):
        field = self.env['ir.model.fields']._get('res.partner', 'create_date')
        tile = self.env['mwd.tile'].with_user(self.alice).create({
            'dashboard_id': self._dashboard_for(self.alice).id,
            'name': 'Created today', 'tile_type': 'agenda',
            'allowed_model_id': self.allowed_partner.id,
            'date_field_id': field.id,
        })
        self.alice.tz = 'UTC'
        utc_start = tile.with_user(self.alice)._today_bounds()[0]
        self.alice.tz = 'Pacific/Kiritimati'  # UTC+14
        ahead_start = tile.with_user(self.alice)._today_bounds()[0]
        self.assertNotEqual(utc_start, ahead_start)

    def test_agenda_requires_a_date_field(self):
        with self.assertRaises(ValidationError):
            self.env['mwd.tile'].with_user(self.alice).create({
                'dashboard_id': self._dashboard_for(self.alice).id,
                'name': 'Broken agenda', 'tile_type': 'agenda',
                'allowed_model_id': self.allowed_partner.id,
            })

    # ------------------------------------------------------------------
    # Bad input
    # ------------------------------------------------------------------

    def test_invalid_domains_are_refused_on_save(self):
        dashboard = self._dashboard_for(self.alice)
        for bad in [
            "[('no_such_field', '=', 1)]",
            "'not a domain'",
            "42",
            "[('name', '=', 'x')",
            "__import__('os').system('echo hi')",
        ]:
            # UserError covers both branches: a domain that will not parse is
            # reported as a UserError, one naming a missing field as the
            # ValidationError that subclasses it.
            with self.subTest(domain=bad), self.assertRaises(UserError):
                self.env['mwd.tile'].with_user(self.alice).create({
                    'dashboard_id': dashboard.id,
                    'name': 'Bad', 'allowed_model_id': self.allowed_partner.id,
                    'line_ids': [(0, 0, {'name': 'Bad', 'domain': bad})],
                })

    def test_a_filter_that_breaks_later_degrades_to_one_line(self):
        """A field removed by an upgrade must not blank the whole dashboard."""
        tile = self._counter_tile(self.alice, [
            {'name': 'Good', 'domain': "[('is_company', '=', True)]"},
            {'name': 'Stale', 'domain': "[]"},
        ])
        stale = tile.line_ids.filtered(lambda line: line.name == 'Stale')
        # Write past the validation, the way a module upgrade would leave things.
        self.env.cr.execute(
            "UPDATE mwd_tile_line SET domain = %s WHERE id = %s",
            ("[('field_that_vanished', '=', 1)]", stale.id))
        self.env.invalidate_all()

        data = self.env['mwd.tile'].browse(tile.id)._get_tile_data()
        self.assertFalse(data['error'], "the tile itself should still render")
        by_name = {line['name']: line for line in data['lines']}
        self.assertFalse(by_name['Good']['error'])
        self.assertTrue(by_name['Stale']['error'])
        self.assertEqual(by_name['Stale']['color'], 'danger')

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    def test_a_user_cannot_see_another_users_dashboard(self):
        self._dashboard_for(self.alice)
        bob_view = self.env['mwd.dashboard'].with_user(self.bob).search([])
        self.assertFalse(bob_view.filtered(lambda d: d.user_id != self.bob))

    def test_a_user_cannot_read_another_users_tiles(self):
        tile = self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}])
        self.assertNotIn(
            tile, self.env['mwd.tile'].with_user(self.bob).search([]))

    def test_a_user_cannot_edit_a_shared_tile_they_do_not_own(self):
        tile = self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}])
        tile.is_shared = True
        self.assertIn(tile, self.env['mwd.tile'].with_user(self.bob).search([]))
        with self.assertRaises(AccessError):
            tile.with_user(self.bob).write({'name': 'hijacked'})

    def test_a_restricted_model_cannot_be_used(self):
        """The dropdown's domain is a hint; this is the check that holds."""
        cron_model = self.env['ir.model']._get('ir.cron')
        restricted = self.env['mwd.allowed.model'].create({
            'model_id': cron_model.id,
            'group_ids': [(6, 0, [self.env.ref('base.group_system').id])],
        })
        with self.assertRaises(ValidationError):
            self.env['mwd.tile'].with_user(self.alice).create({
                'dashboard_id': self._dashboard_for(self.alice).id,
                'name': 'Sneaky', 'allowed_model_id': restricted.id,
            })

    def test_a_tile_never_counts_more_than_its_reader_may_see(self):
        """The whitelist is not the security boundary; record rules are."""
        self.env['ir.rule'].create({
            'name': 'MWD test: hide companies from Alice',
            'model_id': self.partner_model.id,
            'groups': [(6, 0, [self.group_user.id])],
            'domain_force': "[('is_company', '=', False)]",
        })
        tile = self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}])
        data = tile.with_user(self.alice)._get_tile_data()
        self.assertEqual(
            data['lines'][0]['count'],
            self.env['res.partner'].with_user(self.alice).search_count([]),
        )
        self.assertLess(
            data['lines'][0]['count'],
            self.env['res.partner'].sudo().search_count([]),
            'the rule should have hidden some records',
        )

    # ------------------------------------------------------------------
    # Sharing
    # ------------------------------------------------------------------

    def test_duplicating_a_tile_brings_its_lines_and_resets_ownership(self):
        tile = self._counter_tile(self.alice, [
            {'name': 'Companies', 'domain': "[('is_company', '=', True)]"},
            {'name': 'People', 'domain': "[('is_company', '=', False)]"},
        ])
        tile.is_shared = True

        # Taking a tile builds Bob a dashboard if he has none, starter tiles
        # included, so give him one first and then look only at what the copy
        # added.
        self._dashboard_for(self.bob)
        before = self.env['mwd.tile'].with_user(self.bob).search(
            [('user_id', '=', self.bob.id)])
        tile.with_user(self.bob).action_duplicate_to_my_dashboard()
        copy = self.env['mwd.tile'].with_user(self.bob).search(
            [('user_id', '=', self.bob.id)]) - before

        self.assertEqual(len(copy), 1)
        self.assertEqual(copy.user_id, self.bob)
        self.assertFalse(copy.is_shared, 'a copy must not stay shared by itself')
        self.assertEqual(
            sorted(copy.line_ids.mapped('name')), ['Companies', 'People'])
        self.assertEqual(
            sorted(copy.line_ids.mapped('domain')),
            sorted(tile.line_ids.mapped('domain')),
        )

    # ------------------------------------------------------------------
    # Payload and landing page
    # ------------------------------------------------------------------

    def test_payload_shape(self):
        self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}])
        data = self.env['mwd.dashboard'].with_user(self.alice).get_dashboard_data()
        for key in ('id', 'name', 'column_count', 'refresh_interval', 'show_apps',
                    'is_owner', 'is_home', 'app_menu_ids', 'tiles'):
            self.assertIn(key, data)
        self.assertTrue(data['is_owner'])
        self.assertIsInstance(data['column_count'], int)
        self.assertIsInstance(data['refresh_interval'], int)

    def test_a_user_cannot_load_someone_elses_dashboard_by_id(self):
        alice_dashboard = self._dashboard_for(self.alice)
        with self.assertRaises(AccessError):
            self.env['mwd.dashboard'].with_user(self.bob).get_dashboard_data(
                dashboard_id=alice_dashboard.id)

    def test_home_action_can_be_set_and_cleared(self):
        action = self.env.ref('my_work_day.action_my_work_day_dashboard')
        dashboard_model = self.env['mwd.dashboard'].with_user(self.alice)

        dashboard_model.action_set_as_home()
        self.assertEqual(self.alice.action_id.id, action.id)
        self.assertTrue(dashboard_model._is_home_action())

        dashboard_model.action_unset_as_home()
        self.assertFalse(self.alice.action_id)
        self.assertFalse(dashboard_model._is_home_action())

    def test_starter_dashboard_is_created_once(self):
        first = self._dashboard_for(self.alice)
        second = self._dashboard_for(self.alice)
        self.assertEqual(first, second)

    def test_starter_tiles_only_use_available_models(self):
        dashboard = self._dashboard_for(self.alice)
        available = self.env['mwd.allowed.model'].with_user(self.alice)._search_available()
        for tile in dashboard.tile_ids:
            self.assertIn(tile.allowed_model_id, available)

    def test_the_whole_payload_is_one_query_burst(self):
        """Counting on the server is the point; keep it from fanning out."""
        self._counter_tile(self.alice, [
            {'name': 'A', 'domain': "[('is_company', '=', True)]"},
            {'name': 'B', 'domain': "[('is_company', '=', False)]"},
            {'name': 'C', 'domain': "[]"},
        ])
        dashboard_model = self.env['mwd.dashboard'].with_user(self.alice)
        dashboard_model.get_dashboard_data()  # warm caches
        self.env.invalidate_all()
        data = dashboard_model.get_dashboard_data()
        self.assertTrue(data['tiles'])
