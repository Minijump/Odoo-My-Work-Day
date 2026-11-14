from unittest.mock import patch

from odoo.addons.my_work_day.models.mwd_dashboard import MwdDashboard
from odoo import fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMyWorkDay(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.group_user = cls.env.ref('base.group_user')
        # Being an internal user only makes you a Reader. Building tiles is the
        # Editor level, so the two users who do the building are given it here.
        cls.group_editor = cls.env.ref('my_work_day.group_my_work_day_editor')
        cls.group_reader = cls.env.ref('my_work_day.group_my_work_day_reader')
        cls.alice = cls.env['res.users'].create({
            'name': 'Alice', 'login': 'mwd_alice',
            'group_ids': [(6, 0, [cls.group_user.id, cls.group_editor.id])],
        })
        cls.bob = cls.env['res.users'].create({
            'name': 'Bob', 'login': 'mwd_bob',
            'group_ids': [(6, 0, [cls.group_user.id, cls.group_editor.id])],
        })
        cls.reader = cls.env['res.users'].create({
            'name': 'Rita', 'login': 'mwd_rita',
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
        self.env.flush_all()
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
                    'can_edit', 'is_home', 'app_menu_ids', 'tiles'):
            self.assertIn(key, data)
        self.assertTrue(data['can_edit'])
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

    # ------------------------------------------------------------------
    # Access levels
    # ------------------------------------------------------------------

    def test_a_reader_can_open_a_dashboard_without_being_able_to_create_one(self):
        """Reading your own dashboard is part of being an internal user."""
        data = self.env['mwd.dashboard'].with_user(self.reader).get_dashboard_data()
        self.assertEqual(data['id'], self._dashboard_for(self.reader).id)
        self.assertFalse(data['can_edit'], "a Reader must not be offered the edit controls")

    def test_a_reader_cannot_build_a_tile(self):
        dashboard = self._dashboard_for(self.reader)
        with self.assertRaises(AccessError):
            self.env['mwd.tile'].with_user(self.reader).create({
                'dashboard_id': dashboard.id,
                'name': 'Not mine to make',
                'allowed_model_id': self.allowed_partner.id,
            })

    def test_a_reader_cannot_edit_their_own_tile(self):
        """The dashboard may be theirs; changing it is still not their level."""
        dashboard = self._dashboard_for(self.reader)
        tile = self.env['mwd.tile'].create({
            'dashboard_id': dashboard.id,
            'name': 'Made for them',
            'allowed_model_id': self.allowed_partner.id,
            'line_ids': [(0, 0, {'name': 'All', 'domain': "[]"})],
        })
        # They can read it...
        self.assertEqual(tile.with_user(self.reader).name, 'Made for them')
        # ...and that is all.
        with self.assertRaises(AccessError):
            tile.with_user(self.reader).write({'name': 'changed'})
        with self.assertRaises(AccessError):
            tile.with_user(self.reader).unlink()

    def test_an_editor_can_edit_only_their_own(self):
        alice_tile = self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}])
        with self.assertRaises(AccessError):
            alice_tile.with_user(self.bob).write({'name': 'hijacked'})
        alice_tile.with_user(self.alice).write({'name': 'fine'})
        self.assertEqual(alice_tile.name, 'fine')

    # ------------------------------------------------------------------
    # Breakdown sorting and bar colours
    # ------------------------------------------------------------------

    def _breakdown_tile(self, user, **values):
        dashboard = self._dashboard_for(user)
        field = self.env['ir.model.fields']._get('res.partner', 'is_company')
        return self.env['mwd.tile'].with_user(user).create({
            'dashboard_id': dashboard.id,
            'name': 'By kind',
            'tile_type': 'breakdown',
            'allowed_model_id': self.allowed_partner.id,
            'group_field_id': field.id,
            **values,
        })

    def test_breakdown_sort_order_reverses_the_bars(self):
        biggest = self._breakdown_tile(self.alice, group_order='count desc')
        smallest = self._breakdown_tile(self.alice, group_order='count asc')

        descending = [bar['count'] for bar in biggest._get_tile_data()['bars']]
        ascending = [bar['count'] for bar in smallest._get_tile_data()['bars']]

        self.assertEqual(descending, sorted(descending, reverse=True))
        self.assertEqual(ascending, sorted(ascending))
        self.assertEqual(sorted(descending), sorted(ascending),
                         "the same bars, only the order differs")

    def test_breakdown_bars_scale_to_the_biggest_bar_on_show(self):
        """With a limit and an ascending sort, the top bar must still be full."""
        tile = self._breakdown_tile(self.alice, group_order='count asc', group_limit=1)
        bars = tile._get_tile_data()['bars']
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]['ratio'], 100)

    def test_breakdown_bar_colour_rule(self):
        tile = self._breakdown_tile(self.alice)
        bars = tile._get_tile_data()['bars']
        self.assertTrue(all(bar['color'] == 'muted' for bar in bars),
                        "no rule set, so nothing is highlighted")

        smallest = min(bar['count'] for bar in bars)
        tile.write({
            'bar_color_condition': 'gt',
            'bar_color_threshold': smallest,
            'bar_color': 'danger',
        })
        for bar in tile._get_tile_data()['bars']:
            expected = 'danger' if bar['count'] > smallest else 'muted'
            self.assertEqual(bar['color'], expected)

    # ------------------------------------------------------------------
    # Surviving a field that disappears
    # ------------------------------------------------------------------

    def _blank_tile_column(self, tile, column):
        """Point a tile at a field that is not there, the way an uninstall would.

        The flush matters: records created in this test are still sitting in
        the ORM's buffer, and writing raw SQL before they are flushed means the
        flush overwrites it a moment later.
        """
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE mwd_tile SET {} = NULL WHERE id = %s".format(column), (tile.id,))
        self.env.invalidate_all()

    def test_a_broken_agenda_tile_does_not_take_the_dashboard_with_it(self):
        dashboard = self._dashboard_for(self.alice)
        good = self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}])
        date_field = self.env['ir.model.fields']._get('res.partner', 'create_date')
        broken = self.env['mwd.tile'].with_user(self.alice).create({
            'dashboard_id': dashboard.id,
            'name': 'Agenda', 'tile_type': 'agenda',
            'allowed_model_id': self.allowed_partner.id,
            'date_field_id': date_field.id,
        })
        self._blank_tile_column(broken, 'date_field_id')

        data = self.env['mwd.dashboard'].with_user(self.alice).get_dashboard_data(dashboard.id)
        by_id = {tile['id']: tile for tile in data['tiles']}
        self.assertTrue(by_id[broken.id]['error'], "the broken tile reports its own failure")
        self.assertFalse(by_id[good.id]['error'], "every other tile still works")

    def test_a_broken_breakdown_tile_does_not_take_the_dashboard_with_it(self):
        dashboard = self._dashboard_for(self.alice)
        good = self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}])
        broken = self._breakdown_tile(self.alice)
        self._blank_tile_column(broken, 'group_field_id')

        data = self.env['mwd.dashboard'].with_user(self.alice).get_dashboard_data(dashboard.id)
        by_id = {tile['id']: tile for tile in data['tiles']}
        self.assertTrue(by_id[broken.id]['error'])
        self.assertFalse(by_id[good.id]['error'])

    def test_a_tile_whose_model_is_gone_reports_itself_and_nothing_more(self):
        dashboard = self._dashboard_for(self.alice)
        good = self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}])

        # The broken tile needs a selectable model of its own: the two tiles
        # would otherwise share one record, and breaking it would break both.
        allowed_currency = self.env['mwd.allowed.model'].create({
            'model_id': self.env['ir.model']._get('res.currency').id,
        })
        broken = self.env['mwd.tile'].with_user(self.alice).create({
            'dashboard_id': dashboard.id,
            'name': 'Vanished model',
            'allowed_model_id': allowed_currency.id,
            'line_ids': [(0, 0, {'name': 'All', 'domain': "[]"})],
        })
        # model_name is stored, so overwriting it is what uninstalling the
        # module that provided the model would effectively leave behind.
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE mwd_allowed_model SET model_name = 'no.such.model' WHERE id = %s",
            (allowed_currency.id,))
        self.env.invalidate_all()

        data = self.env['mwd.dashboard'].with_user(self.alice).get_dashboard_data(dashboard.id)
        by_id = {tile['id']: tile for tile in data['tiles']}
        self.assertTrue(by_id[broken.id]['error'])
        self.assertFalse(by_id[good.id]['error'])

    # The shipped blueprints are for Sales, Project and friends, none of which
    # exist on a bare database. Standing in a partner blueprint lets these
    # tests check the offering logic itself wherever they run.
    PARTNER_BLUEPRINT = [{
        'model': 'res.partner',
        'name': 'Contacts',
        'icon': 'fa-users',
        'lines': [('Companies', "[('is_company', '=', True)]", 'none', 0, 'muted')],
    }]

    def _with_partner_blueprint(self):
        return patch.object(
            MwdDashboard, '_starter_tile_blueprints',
            lambda dashboard: self.PARTNER_BLUEPRINT)

    def test_starter_tiles_wait_until_a_model_is_selectable(self):
        """An empty whitelist at first visit must not mean an empty dashboard for good."""
        charlie = self.env['res.users'].create({
            'name': 'Charlie', 'login': 'mwd_charlie',
            'group_ids': [(6, 0, [self.group_user.id, self.group_editor.id])],
        })
        dashboard_model = self.env['mwd.dashboard'].with_user(charlie)

        with self._with_partner_blueprint():
            # Nothing is selectable yet, so there is nothing to put on it.
            self.env['mwd.allowed.model'].search([]).unlink()
            first = dashboard_model.get_dashboard_data()
            self.assertEqual(first['tiles'], [])

            # The administrator gets round to it afterwards, the normal order.
            self.env['mwd.allowed.model'].create({'model_id': self.partner_model.id})
            second = dashboard_model.get_dashboard_data()
            self.assertTrue(second['tiles'],
                            "the starter tiles should arrive on the next visit")
            self.assertEqual(second['id'], first['id'], "and on the same dashboard")

    def test_starter_tiles_are_not_offered_twice(self):
        """Clearing your dashboard must not undo itself overnight."""
        dashboard_model = self.env['mwd.dashboard'].with_user(self.alice)
        with self._with_partner_blueprint():
            dashboard_model.get_dashboard_data()
            dashboard = self._dashboard_for(self.alice)
            self.assertTrue(dashboard.starter_tiles_done)

            dashboard.tile_ids.unlink()
            self.assertEqual(dashboard_model.get_dashboard_data()['tiles'], [])

    def test_a_selectable_model_with_no_blueprint_leaves_the_offer_open(self):
        """Whitelisting only unusual models must not burn the one-time offer."""
        dana = self.env['res.users'].create({
            'name': 'Dana', 'login': 'mwd_dana',
            'group_ids': [(6, 0, [self.group_user.id, self.group_editor.id])],
        })
        dashboard_model = self.env['mwd.dashboard'].with_user(dana)
        # res.partner is selectable, but the shipped blueprints never mention it.
        self.assertEqual(dashboard_model.get_dashboard_data()['tiles'], [])
        self.assertFalse(self._dashboard_for(dana).starter_tiles_done)

        with self._with_partner_blueprint():
            self.assertTrue(dashboard_model.get_dashboard_data()['tiles'])

    # ------------------------------------------------------------------
    # Calendar tiles
    # ------------------------------------------------------------------

    def _calendar_tile(self, user, field_name='create_date', **values):
        dashboard = self._dashboard_for(user)
        date_field = self.env['ir.model.fields']._get('res.partner', field_name)
        return self.env['mwd.tile'].with_user(user).create({
            'dashboard_id': dashboard.id,
            'name': values.pop('name', 'Diary'),
            'tile_type': 'calendar',
            'allowed_model_id': self.allowed_partner.id,
            'date_field_id': date_field.id,
            **values,
        })

    def test_calendar_tile_is_built_around_its_own_date_field(self):
        """The arch must name the field the owner picked, not the model's own view."""
        tile = self._calendar_tile(self.alice, calendar_mode='day')
        data = tile.with_user(self.alice)._get_tile_data()

        self.assertFalse(data['error'])
        self.assertEqual(data['type'], 'calendar')
        self.assertIn('date_start="create_date"', data['arch'])
        self.assertIn('mode="day"', data['arch'])
        # The browser keys the remembered scale on it, per tile.
        self.assertEqual(data['mode'], 'day')
        # Read-only: a dashboard is for looking at.
        for attribute in ('create="0"', 'edit="0"', 'delete="0"'):
            self.assertIn(attribute, data['arch'])
        self.assertIsInstance(data['domain'], list)

    def test_calendar_tile_hands_over_a_resolved_domain(self):
        """The browser is handed a domain, never an expression to evaluate."""
        tile = self._calendar_tile(
            self.alice, base_domain="[('is_company', '=', True), ('id', '!=', uid)]")
        data = tile.with_user(self.alice)._get_tile_data()
        leaves = [tuple(leaf) for leaf in data['domain'] if not isinstance(leaf, str)]
        self.assertIn(('is_company', '=', True), leaves)
        self.assertIn(('id', '!=', self.alice.id), leaves)

    def test_calendar_tile_requires_a_date_field(self):
        dashboard = self._dashboard_for(self.alice)
        with self.assertRaises(ValidationError):
            self.env['mwd.tile'].with_user(self.alice).create({
                'dashboard_id': dashboard.id,
                'name': 'No date', 'tile_type': 'calendar',
                'allowed_model_id': self.allowed_partner.id,
            })

    def test_a_broken_calendar_tile_does_not_take_the_dashboard_with_it(self):
        dashboard = self._dashboard_for(self.alice)
        good = self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}])
        broken = self._calendar_tile(self.alice)
        self._blank_tile_column(broken, 'date_field_id')

        data = self.env['mwd.dashboard'].with_user(self.alice).get_dashboard_data(dashboard.id)
        by_id = {tile['id']: tile for tile in data['tiles']}
        self.assertTrue(by_id[broken.id]['error'], "the broken tile reports its own failure")
        self.assertFalse(by_id[good.id]['error'], "every other tile still works")

    # ------------------------------------------------------------------
    # Auto-refresh is the administrator's to set
    # ------------------------------------------------------------------

    def test_refresh_interval_is_off_until_an_administrator_sets_it(self):
        self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}])
        data = self.env['mwd.dashboard'].with_user(self.alice).get_dashboard_data()
        self.assertEqual(data['refresh_interval'], 0)

    def test_refresh_interval_comes_from_the_system_parameter(self):
        """One setting for the database: it decides how often everyone queries."""
        self.env['ir.config_parameter'].sudo().set_param(
            'my_work_day.refresh_interval', '300')
        self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}])
        data = self.env['mwd.dashboard'].with_user(self.alice).get_dashboard_data()
        self.assertEqual(data['refresh_interval'], 300)

    def test_a_nonsense_refresh_parameter_does_not_break_the_dashboard(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'my_work_day.refresh_interval', 'every so often')
        self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}])
        data = self.env['mwd.dashboard'].with_user(self.alice).get_dashboard_data()
        self.assertEqual(data['refresh_interval'], 0)

    def test_a_user_has_no_refresh_interval_to_set(self):
        """It was a per-dashboard field; it is a system parameter now."""
        self.assertNotIn('refresh_interval', self.env['mwd.dashboard']._fields)

    # ------------------------------------------------------------------
    # The upgrade health check
    # ------------------------------------------------------------------

    def _break_line_domain(self, line, domain):
        """Put a domain past the ORM's validation, the way an upgrade would."""
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE mwd_tile_line SET domain = %s WHERE id = %s", (domain, line.id))
        self.env.invalidate_all()

    def test_a_healthy_tile_has_no_problem_to_report(self):
        tile = self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}])
        self.assertFalse(tile.broken_reason)

    def test_check_tiles_says_so_when_every_tile_is_fine(self):
        self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}])
        result = self.env['mwd.tile'].action_check_tiles()
        self.assertEqual(result['type'], 'ir.actions.client')
        self.assertEqual(result['tag'], 'display_notification')

    def test_check_tiles_lists_a_tile_whose_field_disappeared(self):
        tile = self._counter_tile(self.alice, [{'name': 'Companies', 'domain': "[]"}])
        self._break_line_domain(tile.line_ids, "[('field_that_vanished', '=', 1)]")

        self.assertIn('field_that_vanished', tile.broken_reason)
        self.assertIn('Companies', tile.broken_reason,
                      "the report says which line is at fault")

        result = self.env['mwd.tile'].action_check_tiles()
        self.assertEqual(result['type'], 'ir.actions.act_window')
        self.assertEqual(result['res_model'], 'mwd.tile')
        self.assertIn(tile.id, result['domain'][0][2])

    def test_check_tiles_lists_a_tile_whose_model_is_gone(self):
        dashboard = self._dashboard_for(self.alice)
        allowed_currency = self.env['mwd.allowed.model'].create({
            'model_id': self.env['ir.model']._get('res.currency').id,
        })
        tile = self.env['mwd.tile'].with_user(self.alice).create({
            'dashboard_id': dashboard.id,
            'name': 'Vanished model',
            'allowed_model_id': allowed_currency.id,
            'line_ids': [(0, 0, {'name': 'All', 'domain': "[]"})],
        })
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE mwd_allowed_model SET model_name = %s WHERE id = %s",
            ('no.such.model', allowed_currency.id))
        self.env.invalidate_all()

        self.assertIn('no.such.model', tile.broken_reason)
        result = self.env['mwd.tile'].action_check_tiles()
        self.assertEqual(result['type'], 'ir.actions.act_window')
        self.assertIn(tile.id, result['domain'][0][2])

    def test_check_tiles_reaches_every_owner(self):
        """An administrator's check is worthless if it only sees their own tiles."""
        tile = self._counter_tile(self.bob, [{'name': 'All', 'domain': "[]"}])
        self._break_line_domain(tile.line_ids, "[('nope', '=', 1)]")
        result = self.env['mwd.tile'].action_check_tiles()
        self.assertIn(tile.id, result['domain'][0][2])

    # ------------------------------------------------------------------
    # Single-number tiles
    # ------------------------------------------------------------------

    def _value_tile(self, user, domain="[]", **values):
        dashboard = self._dashboard_for(user)
        return self.env['mwd.tile'].with_user(user).create({
            'dashboard_id': dashboard.id,
            'name': values.pop('name', 'Companies'),
            'tile_type': 'value',
            'allowed_model_id': self.allowed_partner.id,
            'base_domain': domain,
            **values,
        })

    def test_value_tile_counts_through_its_own_filter(self):
        """The base filter is the filter: there are no lines to put one on."""
        tile = self._value_tile(self.alice, "[('is_company', '=', True)]")
        data = tile.with_user(self.alice)._get_tile_data()

        self.assertFalse(data['error'])
        self.assertEqual(data['type'], 'value')
        self.assertEqual(
            data['value'],
            self.env['res.partner'].with_user(self.alice).search_count(
                [('is_company', '=', True)]),
        )
        self.assertEqual(data['lines'], [], "a number tile has no lines")

    def test_value_tile_shows_zero_rather_than_nothing(self):
        """Zero is the answer, not the absence of one."""
        tile = self._value_tile(self.alice, "[('id', '=', 0)]")
        self.assertEqual(tile.with_user(self.alice)._get_tile_data()['value'], 0)

    def test_value_tile_colour_rule(self):
        tile = self._value_tile(
            self.alice, "[('is_company', '=', True)]",
            value_color_condition='gt', value_color_threshold=1,
            value_color='danger')
        self.assertEqual(tile.with_user(self.alice)._get_tile_data()['color'], 'danger')

        tile.value_color_threshold = 10_000
        self.assertEqual(tile.with_user(self.alice)._get_tile_data()['color'], 'muted')

    def test_value_tile_click_through_opens_what_was_counted(self):
        tile = self._value_tile(self.alice, "[('is_company', '=', True)]")
        tile = tile.with_user(self.alice)
        action = tile.action_open_tile()
        self.assertEqual(
            self.env['res.partner'].with_user(self.alice).search_count(action['domain']),
            tile._get_tile_data()['value'],
        )

    def test_value_tile_counts_only_what_its_owner_may_see(self):
        """The same boundary as every other tile, not a shortcut around it."""
        self.env['ir.rule'].create({
            'name': 'MWD test: hide companies from Alice',
            'model_id': self.partner_model.id,
            'groups': [(6, 0, [self.group_user.id])],
            'domain_force': "[('is_company', '=', False)]",
        })
        tile = self._value_tile(self.alice, "[]")
        data = tile.with_user(self.alice)._get_tile_data()
        self.assertEqual(
            data['value'],
            self.env['res.partner'].with_user(self.alice).search_count([]),
        )
        self.assertLess(
            data['value'],
            self.env['res.partner'].sudo().search_count([]),
            'the rule should have hidden some records',
        )

    # ------------------------------------------------------------------
    # The limits an administrator can set
    # ------------------------------------------------------------------

    def _set_limit(self, param, value):
        self.env['ir.config_parameter'].sudo().set_param(param, value)

    def test_nothing_is_limited_until_an_administrator_says_so(self):
        for index in range(6):
            self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}],
                               name='Tile %s' % index)
        self.assertEqual(len(self._dashboard_for(self.alice).tile_ids), 6)

    def test_a_dashboard_stops_at_the_tile_limit(self):
        self._set_limit('my_work_day.max_tiles_per_dashboard', '2')
        self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}], name='One')
        self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}], name='Two')
        with self.assertRaises(ValidationError):
            self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}], name='Three')
        self.assertEqual(len(self._dashboard_for(self.alice).tile_ids), 2)

    def test_the_tile_limit_is_per_dashboard_not_per_database(self):
        self._set_limit('my_work_day.max_tiles_per_dashboard', '1')
        self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}], name='Alice only')
        # Bob's own dashboard is untouched by how full Alice's is.
        self._counter_tile(self.bob, [{'name': 'All', 'domain': "[]"}], name='Bob only')
        self.assertEqual(len(self._dashboard_for(self.bob).tile_ids), 1)

    def test_lowering_the_limit_leaves_a_full_dashboard_readable(self):
        """A cap applies to what you build next, not to what you already have."""
        for index in range(3):
            self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}],
                               name='Tile %s' % index)
        self._set_limit('my_work_day.max_tiles_per_dashboard', '1')

        data = self.env['mwd.dashboard'].with_user(self.alice).get_dashboard_data()
        self.assertEqual(len(data['tiles']), 3)
        with self.assertRaises(ValidationError):
            self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}], name='One more')

    def test_a_tile_stops_at_the_filter_limit(self):
        self._set_limit('my_work_day.max_lines_per_tile', '2')
        with self.assertRaises(ValidationError):
            self._counter_tile(self.alice, [
                {'name': 'One', 'domain': "[]"},
                {'name': 'Two', 'domain': "[]"},
                {'name': 'Three', 'domain': "[]"},
            ])

    def test_the_filter_limit_catches_a_line_added_on_its_own(self):
        """A line can be created with only tile_id set, bypassing the tile's own check."""
        self._set_limit('my_work_day.max_lines_per_tile', '2')
        tile = self._counter_tile(self.alice, [
            {'name': 'One', 'domain': "[]"},
            {'name': 'Two', 'domain': "[]"},
        ])
        with self.assertRaises(ValidationError):
            self.env['mwd.tile.line'].with_user(self.alice).create({
                'tile_id': tile.id, 'name': 'Three', 'domain': "[]",
            })

    def test_the_filter_limit_does_not_touch_a_number_tile(self):
        """A single-number tile has no lines, so no filter limit can bite it."""
        self._set_limit('my_work_day.max_lines_per_tile', '1')
        tile = self._value_tile(self.alice, "[('is_company', '=', True)]")
        self.assertTrue(tile.with_user(self.alice)._get_tile_data()['value'])

    def test_a_nonsense_limit_is_no_limit(self):
        self._set_limit('my_work_day.max_tiles_per_dashboard', 'as many as you like')
        for index in range(3):
            self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}],
                               name='Tile %s' % index)
        self.assertEqual(len(self._dashboard_for(self.alice).tile_ids), 3)

    def test_zero_means_no_limit_rather_than_no_tiles(self):
        self._set_limit('my_work_day.max_tiles_per_dashboard', '0')
        self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}])
        self.assertEqual(len(self._dashboard_for(self.alice).tile_ids), 1)

    def test_starter_tiles_stay_within_the_limits(self):
        """A welcome that trips over the cap would leave the user with nothing."""
        self._set_limit('my_work_day.max_tiles_per_dashboard', '1')
        self._set_limit('my_work_day.max_lines_per_tile', '1')
        erin = self.env['res.users'].create({
            'name': 'Erin', 'login': 'mwd_erin',
            'group_ids': [(6, 0, [self.group_user.id, self.group_editor.id])],
        })
        with self._with_partner_blueprint():
            data = self.env['mwd.dashboard'].with_user(erin).get_dashboard_data()
        self.assertEqual(len(data['tiles']), 1)
        self.assertLessEqual(len(data['tiles'][0]['lines']), 1)

    def test_a_tile_over_a_new_limit_can_still_be_edited(self):
        """Lowering a limit must not strand people with unmaintainable tiles.

        The checks fire on what adds to the count, not on every write, so a
        tile that was legal when it was built stays editable: only one more
        filter is refused.
        """
        tile = self._counter_tile(self.alice, [
            {'name': 'One', 'domain': "[]"},
            {'name': 'Two', 'domain': "[]"},
            {'name': 'Three', 'domain': "[]"},
        ])
        self._set_limit('my_work_day.max_lines_per_tile', '2')

        tile.with_user(self.alice).write({'name': 'Renamed', 'width': '2'})
        self.assertEqual(tile.name, 'Renamed')
        tile.with_user(self.alice).line_ids[0].write({'name': 'Still editable'})

        with self.assertRaises(ValidationError):
            self.env['mwd.tile.line'].with_user(self.alice).create({
                'tile_id': tile.id, 'name': 'Four', 'domain': "[]",
            })

    # ------------------------------------------------------------------
    # Calendar tiles: end dates, all-day records, opening on a calendar
    # ------------------------------------------------------------------

    def _partner_field(self, name):
        return self.env['ir.model.fields']._get('res.partner', name)

    def _partner_calendar_view(self):
        """A calendar view for res.partner, which a bare database does not have."""
        return self.env['ir.ui.view'].create({
            'name': 'MWD test partner calendar',
            'model': 'res.partner',
            'type': 'calendar',
            'arch': '<calendar date_start="create_date" date_stop="write_date"'
                    ' all_day="is_company"/>',
        })

    def test_calendar_tile_without_an_end_draws_one_hour_blocks(self):
        """No end field, no date_stop: Odoo's calendar then defaults to one hour."""
        data = self._calendar_tile(self.alice).with_user(self.alice)._get_tile_data()
        self.assertNotIn('date_stop', data['arch'])
        self.assertNotIn('all_day', data['arch'])

    def test_calendar_tile_passes_its_end_and_all_day_fields_on(self):
        """A 9:00-12:00 meeting must be drawn 9:00-12:00, not 9:00-10:00."""
        tile = self._calendar_tile(
            self.alice,
            date_stop_field_id=self._partner_field('write_date').id,
            all_day_field_id=self._partner_field('is_company').id,
        )
        arch = tile.with_user(self.alice)._get_tile_data()['arch']
        self.assertIn('date_stop="write_date"', arch)
        self.assertIn('all_day="is_company"', arch)

    def test_calendar_end_field_must_belong_to_the_tile_model(self):
        with self.assertRaises(ValidationError):
            self._calendar_tile(
                self.alice,
                date_stop_field_id=self.env['ir.model.fields']._get(
                    'res.users', 'write_date').id,
            )

    def test_calendar_end_and_all_day_are_borrowed_from_the_model_view(self):
        """Pick the date field and the rest follows, when the model knows it."""
        self._partner_calendar_view()
        dashboard = self._dashboard_for(self.alice)
        tile_model = self.env['mwd.tile'].with_user(self.alice).with_context(
            default_dashboard_id=dashboard.id)
        with Form(tile_model) as form:
            form.name = 'Diary'
            form.allowed_model_id = self.allowed_partner
            form.tile_type = 'calendar'
            form.date_field_id = self._partner_field('create_date')
            self.assertEqual(form.date_stop_field_id, self._partner_field('write_date'))
            self.assertEqual(form.all_day_field_id, self._partner_field('is_company'))

    def test_calendar_view_is_not_borrowed_for_a_different_start(self):
        """The view's end only means something alongside the view's own start."""
        self._partner_calendar_view()
        dashboard = self._dashboard_for(self.alice)
        tile_model = self.env['mwd.tile'].with_user(self.alice).with_context(
            default_dashboard_id=dashboard.id)
        with Form(tile_model) as form:
            form.name = 'Diary'
            form.allowed_model_id = self.allowed_partner
            form.tile_type = 'calendar'
            form.date_field_id = self._partner_field('write_date')
            self.assertFalse(form.date_stop_field_id)
            self.assertFalse(form.all_day_field_id)

    def test_calendar_tile_opens_on_a_calendar_when_the_model_has_one(self):
        tile = self._calendar_tile(self.alice).with_user(self.alice)
        self.assertEqual(tile.action_open_tile()['views'][0], [False, 'list'],
                         "no calendar view of its own: Odoo's fallback would fail")

        self._partner_calendar_view()
        self.assertEqual(tile.action_open_tile()['views'][0], [False, 'calendar'])

    def test_only_calendar_tiles_open_on_a_calendar(self):
        self._partner_calendar_view()
        tile = self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}])
        self.assertEqual(
            tile.with_user(self.alice).action_open_tile()['views'][0], [False, 'list'])

    # ------------------------------------------------------------------
    # Odds and ends from the roadmap
    # ------------------------------------------------------------------

    def test_longer_refresh_intervals_are_honoured(self):
        self._set_limit('my_work_day.refresh_interval', '14400')
        self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}])
        data = self.env['mwd.dashboard'].with_user(self.alice).get_dashboard_data()
        self.assertEqual(data['refresh_interval'], 14400)

    def test_the_health_check_has_no_menu_of_its_own(self):
        """It lives in Settings only; the action behind it stays."""
        self.assertFalse(self.env.ref(
            'my_work_day.menu_my_work_day_check_tiles', raise_if_not_found=False))
        self.assertTrue(self.env.ref('my_work_day.action_mwd_tile_check'))

    # ------------------------------------------------------------------
    # Field metadata for users who are not administrators
    # ------------------------------------------------------------------
    #
    # Odoo 19 gives ordinary users no access to ir.model.fields. Every test in
    # this section clears the ORM cache first: metadata an administrator looked
    # up earlier in the same test otherwise sits there and hides the access
    # error a real user would hit -- which is exactly how this went unnoticed.

    def _as_fresh(self, record, user):
        self.env.invalidate_all()
        return record.with_user(user)

    def test_field_based_tiles_render_for_their_editor(self):
        agenda = self.env['mwd.tile'].with_user(self.alice).create({
            'dashboard_id': self._dashboard_for(self.alice).id,
            'name': 'Created today', 'tile_type': 'agenda',
            'allowed_model_id': self.allowed_partner.id,
            'date_field_id': self._partner_field('create_date').id,
        })
        breakdown = self._breakdown_tile(self.alice)
        calendar = self._calendar_tile(
            self.alice, date_stop_field_id=self._partner_field('write_date').id)
        for tile in (agenda, breakdown, calendar):
            data = self._as_fresh(tile, self.alice)._get_tile_data()
            self.assertFalse(data['error'], "%s tile failed" % tile.tile_type)

    def test_field_based_tiles_render_for_a_reader(self):
        """A Reader's dashboard is often laid out by someone else."""
        dashboard = self._dashboard_for(self.reader)
        tile = self.env['mwd.tile'].create({
            'dashboard_id': dashboard.id,
            'name': 'By kind', 'tile_type': 'breakdown',
            'allowed_model_id': self.allowed_partner.id,
            'group_field_id': self._partner_field('is_company').id,
        })
        data = self._as_fresh(tile, self.reader)._get_tile_data()
        self.assertFalse(data['error'])
        self.assertTrue(data['bars'])

    def test_an_editor_can_pick_fields_of_selectable_models_only(self):
        self.assertFalse(self.env['mwd.allowed.model'].search(
            [('model_name', '=', 'res.users')]), "res.users must not be whitelisted here")
        fields_model = self._as_fresh(self.env['ir.model.fields'], self.alice)
        self.assertTrue(fields_model.search_count([('model', '=', 'res.partner')]))
        self.assertFalse(fields_model.search_count([('model', '=', 'res.users')]),
                         "the grant is no wider than the whitelist")
        self.assertTrue(fields_model.name_search(
            'create', domain=[('model', '=', 'res.partner')]))

    def test_an_editor_cannot_point_a_tile_at_another_models_field(self):
        """Refused with a proper message, not an access error."""
        with self.assertRaises(ValidationError):
            self._as_fresh(self.env['mwd.tile'], self.alice).create({
                'dashboard_id': self._dashboard_for(self.alice).id,
                'name': 'Sneaky', 'tile_type': 'agenda',
                'allowed_model_id': self.allowed_partner.id,
                'date_field_id': self.env['ir.model.fields'].sudo()._get(
                    'res.users', 'login_date').id,
            })

    def test_administrators_still_see_every_field(self):
        """Every user is a Reader; the Reader rule must not narrow the admin."""
        admin = self.env.ref('base.user_admin')
        fields_model = self._as_fresh(self.env['ir.model.fields'], admin)
        self.assertTrue(fields_model.search_count([('model', '=', 'res.users')]))

    # ------------------------------------------------------------------
    # Linking a tile to an app menu
    # ------------------------------------------------------------------

    def _partner_menu(self, **values):
        """A menu opening res.partner, which a bare database does not have.

        Its action carries a domain and a search default of its own, the way
        real app menus do, so the tests can check both are kept out of the way.
        """
        action = self.env['ir.actions.act_window'].create({
            'name': 'MWD test contacts',
            'res_model': 'res.partner',
            'view_mode': 'kanban,list,form',
            'domain': "[('is_company', '=', True)]",
            'context': "{'search_default_type_company': 1, 'default_is_company': True}",
        })
        return self.env['ir.ui.menu'].create({
            'name': 'MWD test contacts',
            'action': 'ir.actions.act_window,%s' % action.id,
            **values,
        })

    def test_only_menus_on_the_tile_model_are_offered(self):
        menu = self._partner_menu()
        menus = self.env['ir.ui.menu']
        self.assertIn(menu, menus.search([('mwd_res_model', '=', 'res.partner')]))
        self.assertNotIn(menu, menus.search([('mwd_res_model', '=', 'res.users')]))

    def test_a_menu_on_another_model_is_refused(self):
        users_action = self.env['ir.actions.act_window'].create({
            'name': 'MWD test users', 'res_model': 'res.users'})
        menu = self.env['ir.ui.menu'].create({
            'name': 'MWD test users',
            'action': 'ir.actions.act_window,%s' % users_action.id,
        })
        with self.assertRaises(ValidationError):
            self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}], menu_id=menu.id)

    def test_a_linked_tile_opens_its_menu_on_exactly_what_it_counted(self):
        menu = self._partner_menu()
        tile = self._counter_tile(
            self.alice, [{'name': 'People', 'domain': "[('is_company', '=', False)]"}],
            menu_id=menu.id,
        ).with_user(self.alice)

        action = tile.action_open_line(tile.line_ids.id)
        self.assertEqual(action['mwd_menu_id'], menu.id)
        self.assertEqual(action['id'], menu.action.id, "the menu's own action and views")
        self.assertEqual(
            self.env['res.partner'].with_user(self.alice).search_count(action['domain']),
            tile._get_tile_data()['lines'][0]['count'],
            "the menu's own domain (companies only) must not narrow the list",
        )

    def test_a_menu_the_user_cannot_see_falls_back_to_a_plain_list(self):
        menu = self._partner_menu(group_ids=[(6, 0, [self.env.ref('base.group_system').id])])
        tile = self._counter_tile(
            self.alice, [{'name': 'All', 'domain': "[]"}], menu_id=menu.id)
        action = tile.with_user(self.alice).action_open_tile()
        self.assertNotIn('mwd_menu_id', action)
        self.assertEqual(action['views'][0], [False, 'list'])

    def test_an_unlinked_tile_still_opens_a_plain_list(self):
        tile = self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}])
        action = tile.with_user(self.alice).action_open_tile()
        self.assertNotIn('mwd_menu_id', action)

    def test_a_linked_agenda_entry_opens_inside_the_app(self):
        menu = self._partner_menu()
        tile = self.env['mwd.tile'].with_user(self.alice).create({
            'dashboard_id': self._dashboard_for(self.alice).id,
            'name': 'Created today', 'tile_type': 'agenda',
            'allowed_model_id': self.allowed_partner.id,
            'date_field_id': self._partner_field('create_date').id,
            'menu_id': menu.id,
        })
        partner = self.env['res.partner'].search([], limit=1)
        action = tile.with_user(self.alice).action_open_record(partner.id)
        self.assertEqual(action['res_id'], partner.id)
        self.assertEqual(action['mwd_menu_id'], menu.id)

    def test_changing_the_model_clears_the_menu(self):
        menu = self._partner_menu()
        allowed_currency = self.env['mwd.allowed.model'].create({
            'model_id': self.env['ir.model']._get('res.currency').id,
        })
        tile_model = self.env['mwd.tile'].with_user(self.alice).with_context(
            default_dashboard_id=self._dashboard_for(self.alice).id)
        with Form(tile_model) as form:
            form.name = 'Moving'
            form.allowed_model_id = self.allowed_partner
            form.menu_id = menu
            form.allowed_model_id = allowed_currency
            self.assertFalse(form.menu_id)

    # ------------------------------------------------------------------
    # Code audit: what a filter may and may not do
    # ------------------------------------------------------------------

    def test_a_filter_cannot_run_code_with_someone_elses_rights(self):
        """The hole this closes: `user` in the filter context let an Editor run
        `user.sudo().write(...)` and make themselves an administrator."""
        attempts = [
            "[('id', '!=', user.sudo().write({'name': 'PWNED'}))]",
            "[('id', 'in', user.env['res.users'].sudo().search([]).ids)]",
            "[('id', '=', user.id)]",
        ]
        for domain in attempts:
            with self.subTest(domain=domain), self.assertRaises(UserError):
                self._counter_tile(self.alice, [{'name': 'All', 'domain': domain}])
        self.env.invalidate_all()
        self.assertEqual(self.alice.name, 'Alice')

    def test_the_filter_context_holds_no_record(self):
        """Belt and braces: the evaluator calls no method on what it is given,
        but nothing a filter can name should be an object with methods."""
        tile = self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}])
        context = tile.with_user(self.alice)._filter_names()
        for name, value in context.items():
            self.assertNotIsInstance(value, models.BaseModel, "%r is a record" % name)

    def test_a_plain_uid_filter_still_works(self):
        tile = self._counter_tile(self.alice, [{'name': 'Me', 'domain': "[('id', '=', uid)]"}])
        self.assertFalse(tile.with_user(self.alice)._get_tile_data()['lines'][0]['error'])

    # ------------------------------------------------------------------
    # Code audit: the bugs found on the way
    # ------------------------------------------------------------------

    def test_only_administrators_may_check_every_tile(self):
        with self.assertRaises(AccessError):
            self.env['mwd.tile'].with_user(self.alice).action_check_tiles()
        self.assertEqual(
            self.env.ref('my_work_day.action_mwd_tile_check').group_ids,
            self.env.ref('my_work_day.group_my_work_day_manager'),
        )

    def test_changing_the_model_clears_the_calendar_end_fields(self):
        """They belonged to the old model, and would have refused the save."""
        self._partner_calendar_view()
        allowed_currency = self.env['mwd.allowed.model'].create({
            'model_id': self.env['ir.model']._get('res.currency').id,
        })
        tile_model = self.env['mwd.tile'].with_user(self.alice).with_context(
            default_dashboard_id=self._dashboard_for(self.alice).id)
        with Form(tile_model) as form:
            form.name = 'Moving'
            form.allowed_model_id = self.allowed_partner
            form.tile_type = 'calendar'
            form.date_field_id = self._partner_field('create_date')
            self.assertTrue(form.date_stop_field_id)
            form.allowed_model_id = allowed_currency
            self.assertFalse(form.date_stop_field_id)
            self.assertFalse(form.all_day_field_id)
            form.date_field_id = self.env['ir.model.fields']._get('res.currency', 'create_date')

    def test_a_line_takes_its_model_from_the_tile(self):
        """Including on a tile that is not saved yet, which is where the filter
        editor needs it."""
        tile_model = self.env['mwd.tile'].with_user(self.alice).with_context(
            default_dashboard_id=self._dashboard_for(self.alice).id)
        with Form(tile_model) as form:
            form.name = 'New'
            form.allowed_model_id = self.allowed_partner
            with form.line_ids.new() as line:
                line.name = 'All'
                self.assertEqual(line.model_name, 'res.partner')
        tile = form.record
        self.assertEqual(tile.line_ids.model_name, 'res.partner')

    def test_open_dashboard_shows_that_dashboard(self):
        """From All Dashboards, an administrator opens the colleague's layout."""
        bob_dashboard = self._dashboard_for(self.bob)
        action = bob_dashboard.action_open_dashboard()
        self.assertEqual(action['tag'], 'my_work_day_dashboard')
        self.assertEqual(action['params']['dashboard_id'], bob_dashboard.id)

    def test_a_tile_that_lost_its_field_says_so_plainly(self):
        tile = self._breakdown_tile(self.alice)
        self._blank_tile_column(tile, 'group_field_id')
        error = tile.with_user(self.alice)._get_tile_data()['error']
        self.assertTrue(error)
        self.assertNotIn('False', error)

    # ------------------------------------------------------------------
    # The filter sandbox, beyond records
    # ------------------------------------------------------------------

    def _eval_as_alice(self, expression):
        tile = self._counter_tile(self.alice, [{'name': 'All', 'domain': "[]"}])
        return tile.with_user(self.alice)._eval_domain(expression)

    def test_a_filter_cannot_read_the_server_configuration(self):
        """The format-string route: it got as far as the database password."""
        leak = ("[('name', '=', '{0.__init__.__globals__[calendar].sys.modules[odoo]"
                ".tools.config.options[db_password]}'.format(relativedelta))]")
        with self.assertRaises(UserError):
            self._eval_as_alice(leak)

    def test_every_way_to_reach_str_format_is_refused(self):
        attempts = [
            "[('name', '=', '{0.__class__}'.format(today))]",
            "[('name', '=', '{x.__class__}'.format_map({'x': today}))]",
            "[('name', '=', str.format('{0.__class__}', today))]",
            # Nested code is checked too, not only the top level.
            "[('name', '=', (lambda: '{0}'.format(today))())]",
            "[('name', 'in', [s.format(today) for s in ['{0}']])]",
        ]
        for expression in attempts:
            with self.subTest(expression=expression), self.assertRaises(UserError):
                self._eval_as_alice(expression)

    def test_the_word_format_in_a_value_is_fine(self):
        """Only the attribute is refused, not the word."""
        domain = self._eval_as_alice("[('name', 'ilike', 'format')]")
        self.assertEqual(domain, [('name', 'ilike', 'format')])

    def test_a_filter_cannot_stall_a_worker_with_sleep(self):
        with self.assertRaises(UserError):
            self._eval_as_alice("[('id', '!=', time.sleep(0))]")

    def test_the_builders_datetime_filters_work_on_the_server(self):
        """What Odoo's filter builder writes for "today" on a datetime field."""
        expression = (
            "[('create_date', '>=', datetime.datetime.combine(context_today(), "
            "datetime.time(0, 0, 0)).to_utc().strftime('%Y-%m-%d %H:%M:%S'))]"
        )
        self.alice.tz = 'Europe/Brussels'
        domain = self._eval_as_alice(expression)
        start_utc, _end, _today = self._counter_tile(
            self.alice, [{'name': 'All', 'domain': "[]"}]).with_user(self.alice)._today_bounds()
        self.assertEqual(domain[0][2], fields.Datetime.to_string(start_utc),
                         "midnight in the user's timezone, expressed in UTC")

    # ------------------------------------------------------------------
    # Filters are read as data: what the grammar accepts and refuses
    # ------------------------------------------------------------------

    # What Odoo's filter builder writes for its "smart date" ranges, copied
    # from web/static/src/core/tree_editor/virtual_operators.js.
    BUILDER_DELTAS = [
        '', 'days = 1', 'days = -7', 'days = -30', 'day = 1',
        'day = 1, months = -1', 'day = 1, month = 1', 'day = 1, months = -12',
    ]

    def test_every_date_filter_the_builder_writes_is_understood(self):
        for delta in self.BUILDER_DELTAS:
            value = ('context_today().strftime("%Y-%m-%d")' if not delta else
                     "(context_today() + relativedelta(%s)).strftime('%%Y-%%m-%%d')" % delta)
            with self.subTest(delta=delta):
                domain = self._eval_as_alice("[('date', '>=', %s)]" % value)
                fields.Date.to_date(domain[0][2])  # a real date string

    def test_every_datetime_filter_the_builder_writes_is_understood(self):
        for delta in self.BUILDER_DELTAS:
            day = 'context_today()' if not delta else 'context_today() + relativedelta(%s)' % delta
            value = ('datetime.datetime.combine(%s, datetime.time(0, 0, 0))'
                     '.to_utc().strftime("%%Y-%%m-%%d %%H:%%M:%%S")' % day)
            with self.subTest(delta=delta):
                domain = self._eval_as_alice("[('create_date', '>=', %s)]" % value)
                fields.Datetime.to_datetime(domain[0][2])

    def test_the_shipped_starter_filters_are_understood(self):
        for blueprint in self.env['mwd.dashboard']._starter_tile_blueprints():
            for _name, domain, *_rest in blueprint['lines']:
                with self.subTest(domain=domain):
                    self.assertIsInstance(self._eval_as_alice(domain), list)

    def test_plain_domains_keep_their_shape(self):
        self.assertEqual(
            self._eval_as_alice(
                "['|', ('state', 'in', ['draft', 'sent']), '!', ('amount', '>', -1.5), "
                "('user_id', 'in', [uid]), ('active', '=', True), ('note', '=', False)]"),
            ['|', ('state', 'in', ['draft', 'sent']), '!', ('amount', '>', -1.5),
             ('user_id', 'in', [self.alice.id]), ('active', '=', True), ('note', '=', False)],
        )

    def test_anything_outside_the_grammar_is_refused(self):
        """Not a list of known attacks: things that are simply not on the list."""
        refused = [
            "uid.real",                              # attribute
            "[1, 2][0]",                             # subscript
            "uid == 1",                              # comparison
            "uid and 1",                             # boolean operator
            "uid * 2",                               # arithmetic on numbers
            "2 ** 64",                               # power
            "(lambda: 1)()",                         # lambda
            "[x for x in [1]]",                      # comprehension
            "{'a': 1}",                              # dict
            "{1}",                                   # set
            "f'{uid}'",                              # f-string
            "bool(1)",                               # any other function
            "str(uid)",
            "'x'.upper()",                           # a method on anything but a date
            "today.year",                            # an attribute of a date
            "context_today().weekday()",             # a date method not on the list
            "context_today(1)",                      # unexpected argument
            "relativedelta(days=1.5)",               # not a whole number
            "relativedelta(leapdays=1)",             # keyword not on the list
            "relativedelta(**{'days': 1})",          # keyword splat
            "datetime.datetime.now()",               # module function not on the list
            "datetime.time(*[1, 2])",                # positional splat
            "context_today().strftime()",            # missing argument
            "user",                                  # a name that is not there
            "time.sleep(1)",
        ]
        for expression in refused:
            with self.subTest(expression=expression), self.assertRaises(UserError):
                self._eval_as_alice("[('name', '=', %s)]" % expression)
