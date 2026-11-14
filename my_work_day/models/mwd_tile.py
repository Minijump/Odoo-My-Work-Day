import datetime
import logging

import pytz
from dateutil.relativedelta import relativedelta

from lxml import etree
from markupsafe import escape

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain

from .filter_expression import evaluate_filter

_logger = logging.getLogger(__name__)

# Caps an administrator can put on what a user may build. Both are optional:
# an unset, empty or nonsensical parameter means no limit, which is how the
# module behaves out of the box.
MAX_TILES_PARAM = 'my_work_day.max_tiles_per_dashboard'
MAX_LINES_PARAM = 'my_work_day.max_lines_per_tile'


def limit_from(env, param):
    """An administrator's cap as a positive number, or None for "no limit"."""
    try:
        limit = int(env['ir.config_parameter'].sudo().get_param(param) or 0)
    except ValueError:
        # A hand-edited parameter should not lock everyone out of their own
        # dashboard; an unreadable limit is no limit.
        return None
    return limit if limit > 0 else None


COLORS = [
    ('muted', 'Neutral'),
    ('info', 'Blue'),
    ('success', 'Green'),
    ('warning', 'Orange'),
    ('danger', 'Red'),
]

CONDITIONS = [
    ('none', 'Never'),
    ('gt', 'More than'),
    ('ge', 'At least'),
    ('lt', 'Fewer than'),
    ('eq', 'Exactly'),
]


def color_for(condition, threshold, color, count):
    """The colour a count should take, or 'muted' when the rule does not fire.

    Shared by counter lines and breakdown bars so that a highlight means the
    same thing wherever it appears.
    """
    triggered = (
        (condition == 'gt' and count > threshold)
        or (condition == 'ge' and count >= threshold)
        or (condition == 'lt' and count < threshold)
        or (condition == 'eq' and count == threshold)
    )
    return color if triggered else 'muted'


class MwdTile(models.Model):
    _name = 'mwd.tile'
    _description = 'My Work Day Tile'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    dashboard_id = fields.Many2one(
        'mwd.dashboard', string='Dashboard', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one(
        related='dashboard_id.user_id', string='Owner', store=True, index=True)
    tile_type = fields.Selection(
        [('count', 'Counters'), ('value', 'Single Number'), ('agenda', "Today's List"),
         ('breakdown', 'Bar Chart'), ('calendar', 'Calendar')],
        string='Type', default='count', required=True,
        help="Counters: one line per named filter, showing how many records match.\n"
             "Single Number: one count, large, for the figure that matters most.\n"
             "Today's List: the records of this model happening today, in time order.\n"
             "Bar Chart: how many records fall into each value of a field.\n"
             "Calendar: a real calendar grid, for a tile you read like a diary.",
    )
    icon = fields.Char(
        string='Icon', default='fa-list',
        help="A Font Awesome icon name, for example fa-shopping-cart.")
    width = fields.Selection(
        [('1', 'Normal'), ('2', 'Double width'), ('3', 'Triple width'), ('4', 'Full width')],
        string='Width', default='1', required=True)
    height = fields.Selection(
        [('1', 'Normal'), ('2', 'Tall')], string='Height', default='1', required=True)
    menu_id = fields.Many2one(
        'ir.ui.menu', string='Open In', ondelete='set null',
        domain="[('mwd_res_model', '=', model_name)]",
        help="An app menu to open when the tile is clicked, so you land inside that "
             "app rather than on a plain list. Only menus showing this tile's model "
             "are offered. The tile's filter still applies, as a fixed filter that "
             "cannot be removed from the search bar. Leave empty for a plain list.")

    is_shared = fields.Boolean(
        string='Share With Colleagues', default=False, copy=False,
        help="Let other users find this tile and copy it onto their own dashboard. "
             "They get your filters, not your data: a copy still counts only what "
             "its new owner is allowed to see.",
    )

    allowed_model_id = fields.Many2one(
        'mwd.allowed.model', string='Model', required=True, ondelete='cascade',
        help="Which records this tile counts. Administrators decide which models appear here.")
    model_name = fields.Char(related='allowed_model_id.model_name', string='Technical Model')

    base_domain = fields.Char(
        string='Base Filter', default='[]',
        help="Applied on top of every line of this tile. Leave as [] for no extra filter.")

    # -- counter tiles --
    # copy=True because one2many fields are not copied by default, and a tile
    # duplicated without its lines would be an empty shell -- which is the
    # whole point of sharing a tile with a colleague.
    line_ids = fields.One2many('mwd.tile.line', 'tile_id', string='Lines', copy=True)
    hide_empty_lines = fields.Boolean(
        string='Hide Empty Lines', default=False,
        help="Leave out lines that count zero, so the tile only shows actual work.")
    show_total = fields.Boolean(string='Show Total', default=False)

    # -- single-number tiles --
    # These have no lines of their own: the tile's base filter *is* the filter,
    # since there is nothing for a second one to sit on top of. That keeps the
    # type to what it is for -- one figure, large enough to read across a room.
    value_color_condition = fields.Selection(
        CONDITIONS, string='Highlight When', default='none', required=True,
        help="Colour the number once it crosses a threshold, the same way a "
             "counter line is highlighted.")
    value_color_threshold = fields.Integer(string='Threshold', default=0)
    value_color = fields.Selection(
        COLORS, string='Highlight Colour', default='warning', required=True)

    # -- agenda tiles --
    date_field_id = fields.Many2one(
        'ir.model.fields', string='Date Field', ondelete='set null',
        domain="[('model', '=', model_name), ('ttype', 'in', ['date', 'datetime']),"
               " ('store', '=', True)]",
        help="The field that says when a record happens.")
    agenda_limit = fields.Integer(string='Maximum Entries', default=10)

    # -- calendar tiles --
    # The date field is shared with agenda tiles: both answer "when does this
    # record happen", and a tile is only ever one type at a time.
    calendar_mode = fields.Selection(
        [('day', 'Day'), ('week', 'Week'), ('month', 'Month')],
        string='Calendar Scale', default='week', required=True,
        help="Which span the calendar opens on. The reader can still switch "
             "scale from the tile itself.")
    # Without an end, Odoo's calendar draws every record as exactly one hour
    # from its start: a 9:00-12:00 meeting shows as 9:00-10:00, and an all-day
    # event as a one-hour block at whatever time its start happens to hold.
    date_stop_field_id = fields.Many2one(
        'ir.model.fields', string='End Date Field', ondelete='set null',
        domain="[('model', '=', model_name), ('ttype', 'in', ['date', 'datetime']),"
               " ('store', '=', True)]",
        help="The field that says when a record ends. Leave empty and every "
             "record is drawn one hour long.")
    all_day_field_id = fields.Many2one(
        'ir.model.fields', string='All-Day Field', ondelete='set null',
        domain="[('model', '=', model_name), ('ttype', '=', 'boolean'),"
               " ('store', '=', True)]",
        help="A yes/no field marking records that last the whole day, such as "
             "'All Day' on a meeting.")

    # -- breakdown tiles --
    group_field_id = fields.Many2one(
        'ir.model.fields', string='Group By', ondelete='set null',
        domain="[('model', '=', model_name), ('store', '=', True),"
               " ('ttype', 'in', ['many2one', 'selection', 'char', 'boolean', 'date', 'datetime'])]",
        help="The field whose values become the bars of the chart.")
    group_field_ttype = fields.Selection(
        related='group_field_id.ttype', string='Group Field Type')
    group_granularity = fields.Selection(
        [('day', 'Day'), ('week', 'Week'), ('month', 'Month'),
         ('quarter', 'Quarter'), ('year', 'Year')],
        string='Group Dates By', default='month',
        help="How to bucket a date field. Grouping by a raw date would give one "
             "bar per timestamp, so a granularity is always needed.")
    group_limit = fields.Integer(string='Maximum Bars', default=8)
    group_order = fields.Selection(
        [('count desc', 'Largest first'), ('count asc', 'Smallest first'),
         ('value asc', 'By value, ascending'), ('value desc', 'By value, descending')],
        string='Sort Bars By', default='count desc', required=True,
        help="Largest first answers 'where is the work piling up'. Sorting by "
             "value is what you want for a date breakdown, where the bars mean "
             "more in chronological order than in size order.",
    )
    bar_color_condition = fields.Selection(
        CONDITIONS, string='Highlight Bars When', default='none', required=True,
        help="Colour a bar once its count crosses a threshold, the same way a "
             "counter line is highlighted.")
    bar_color_threshold = fields.Integer(string='Bar Threshold', default=0)
    bar_color = fields.Selection(
        COLORS, string='Bar Highlight Colour', default='warning', required=True)

    broken_reason = fields.Char(
        string='Problem', compute='_compute_broken_reason',
        help="Filled in when this tile can no longer be counted, usually "
             "because a field it refers to disappeared in an upgrade.")

    # ------------------------------------------------------------------
    # Consistency
    # ------------------------------------------------------------------

    @api.onchange('allowed_model_id')
    def _onchange_allowed_model_id(self):
        """Clear anything that referred to the previous model."""
        self.date_field_id = False
        self.date_stop_field_id = False
        self.all_day_field_id = False
        self.group_field_id = False
        self.menu_id = False
        self.base_domain = '[]'
        for line in self.line_ids:
            line.domain = '[]'
        if self.allowed_model_id.date_field_id:
            self.date_field_id = self.allowed_model_id.date_field_id

    @api.onchange('tile_type', 'date_field_id')
    def _onchange_calendar_fields(self):
        """Borrow the end and all-day fields from the model's own calendar view.

        Only when that view starts on the same field the tile does, and only to
        fill blanks: this is a suggestion for the common case -- a calendar
        tile on meetings should show meetings the way the Calendar app does
        without anyone having to know the field is called ``stop`` -- not a
        rule that overrides what the owner chose.
        """
        if (self.tile_type != 'calendar' or not self.date_field_id
                or self.date_stop_field_id or self.all_day_field_id):
            return
        model = self.env.get(self.model_name)
        if model is None:
            return
        try:
            arch = model.get_view(view_type='calendar')['arch']
        except Exception:  # noqa: BLE001 - most models have no calendar view
            return
        node = etree.fromstring(arch)
        if node.get('date_start') != self.date_field_id.sudo().name:
            return
        fields_model = self.env['ir.model.fields']
        if node.get('date_stop'):
            self.date_stop_field_id = fields_model._get(self.model_name, node.get('date_stop'))
        if node.get('all_day'):
            self.all_day_field_id = fields_model._get(self.model_name, node.get('all_day'))

    @api.constrains('menu_id', 'allowed_model_id')
    def _check_menu_model(self):
        for tile in self:
            if tile.menu_id and tile.menu_id.sudo().mwd_res_model != tile.model_name:
                raise ValidationError(_(
                    "The menu %(menu)s does not show %(model)s records, so it cannot "
                    "show what this tile counts.",
                    menu=tile.menu_id.sudo().complete_name,
                    model=tile.allowed_model_id.display_name,
                ))

    @api.constrains('allowed_model_id')
    def _check_model_allowed(self):
        """A user may only build on a model an administrator made available.

        The field's domain already filters the dropdown, but a domain is only a
        hint to the client. This is the part that actually holds.
        """
        available = None
        for tile in self:
            if tile.user_id.id != self.env.uid and not self.env.user.has_group('base.group_system'):
                continue
            if available is None:
                available = self.env['mwd.allowed.model']._search_available()
            if tile.allowed_model_id not in available:
                raise ValidationError(_(
                    "You are not allowed to build a tile on %s.",
                    tile.allowed_model_id.display_name,
                ))

    @api.constrains('dashboard_id')
    def _check_tile_limit(self):
        """Keep a dashboard within the number of tiles an administrator allows.

        Every tile on the page is counted in one request, so fifty tiles of ten
        filters is one request that runs five hundred queries. The cap is the
        only thing stopping one user making that everyone's problem.

        Counted with sudo: the point is how many tiles the dashboard holds, not
        how many this user happens to be able to see.
        """
        limit = limit_from(self.env, MAX_TILES_PARAM)
        if not limit:
            return
        for dashboard in self.mapped('dashboard_id'):
            count = self.env['mwd.tile'].sudo().search_count([
                ('dashboard_id', '=', dashboard.id),
            ])
            if count > limit:
                raise ValidationError(_(
                    "A dashboard can hold at most %(limit)s tiles, and this one "
                    "would have %(count)s. Remove a tile first, or ask an "
                    "administrator to raise the limit.",
                    limit=limit, count=count,
                ))

    @api.constrains('line_ids')
    def _check_line_limit(self):
        """Keep a tile within the number of filters an administrator allows."""
        limit = limit_from(self.env, MAX_LINES_PARAM)
        if not limit:
            return
        for tile in self:
            count = len(tile.sudo().line_ids)
            if count > limit:
                raise ValidationError(_(
                    "A tile can hold at most %(limit)s filters, and \"%(name)s\" "
                    "would have %(count)s. Remove a filter first, or ask an "
                    "administrator to raise the limit.",
                    limit=limit, name=tile.name, count=count,
                ))

    @api.constrains('base_domain')
    def _check_base_domain(self):
        for tile in self:
            tile._validate_domain(tile.base_domain)

    @api.constrains('tile_type', 'date_field_id', 'group_field_id')
    def _check_required_fields(self):
        for tile in self:
            if tile.tile_type in ('agenda', 'calendar') and not tile.date_field_id:
                raise ValidationError(_("This type of tile needs a date field."))
            if tile.tile_type == 'breakdown' and not tile.group_field_id:
                raise ValidationError(_("A bar chart tile needs a field to group by."))

    @api.constrains('date_field_id', 'group_field_id', 'date_stop_field_id',
                    'all_day_field_id', 'allowed_model_id')
    def _check_fields_belong_to_model(self):
        for tile in self:
            # sudo: a field the user may not read must still be refused
            # with this message rather than an access error.
            used = (tile.date_field_id | tile.group_field_id
                    | tile.date_stop_field_id | tile.all_day_field_id)
            for field in used.sudo():
                if field and field.model != tile.model_name:
                    raise ValidationError(_(
                        "The field %(field)s does not belong to %(model)s.",
                        field=field.name, model=tile.model_name,
                    ))

    # ------------------------------------------------------------------
    # Domain handling
    # ------------------------------------------------------------------

    def _filter_names(self):
        """The plain values a tile filter may refer to by name.

        Values, never objects: see filter_expression.py for why a filter is
        read as data rather than run as code.
        """
        self.ensure_one()
        return {
            'uid': self.env.uid,
            'company_id': self.env.company.id,
            'company_ids': self.env.companies.ids,
            'allowed_company_ids': self.env.companies.ids,
            'today': fields.Date.context_today(self),
            'now': fields.Datetime.now(),
        }

    def _eval_domain(self, domain_string):
        """Turn a stored domain string into a real domain, or raise UserError."""
        self.ensure_one()
        if not domain_string or not domain_string.strip():
            return []
        try:
            domain = evaluate_filter(
                domain_string, self._filter_names(),
                today=fields.Date.context_today(self), timezone=self._user_timezone())
        except Exception as error:
            raise UserError(_("Invalid filter: %s", error)) from error
        if not isinstance(domain, (list, tuple)):
            raise UserError(_("A filter must be a domain, such as [('state', '=', 'draft')]."))
        return list(domain)

    def _validate_domain(self, domain_string):
        """Check a domain parses and only mentions real fields of the model."""
        self.ensure_one()
        if not self.model_name:
            return
        model = self.env.get(self.model_name)
        if model is None:
            return
        try:
            Domain(self._eval_domain(domain_string)).validate(model.sudo())
        except UserError:
            raise
        except Exception as error:
            raise ValidationError(_("Invalid filter: %s", error)) from error

    def _full_domain(self, extra_domain=(), base=None):
        """The tile's base filter combined with a line's own filter.

        ``base`` lets a caller that combines many filters with the same base
        evaluate it once rather than once per filter.
        """
        self.ensure_one()
        if base is None:
            base = Domain(self._eval_domain(self.base_domain))
        return list(base & Domain(list(extra_domain)))

    def _record_model(self):
        """The model this tile reads, as the current user.

        Returns None when the model is gone, which happens if the module that
        provided it was uninstalled while a tile still pointed at it.
        """
        self.ensure_one()
        return self.env.get(self.model_name)

    # ------------------------------------------------------------------
    # Payload
    # ------------------------------------------------------------------

    def _get_tile_data(self):
        self.ensure_one()
        data = {
            'id': self.id,
            'name': self.name,
            'icon': self.icon or 'fa-list',
            'type': self.tile_type,
            'width': int(self.width),
            'height': int(self.height),
            'model': self.model_name,
            'error': False,
            'lines': [],
        }

        model = self._record_model()
        if model is None:
            data['error'] = _("The model %s is not available on this database.", self.model_name)
            return data
        if not model.has_access('read'):
            data['error'] = _("You do not have access to %s.", self.allowed_model_id.display_name)
            return data

        try:
            if self.tile_type == 'count':
                data.update(self._get_count_data())
            elif self.tile_type == 'value':
                data.update(self._get_value_data())
            elif self.tile_type == 'agenda':
                data.update(self._get_agenda_data())
            elif self.tile_type == 'breakdown':
                data.update(self._get_breakdown_data())
            elif self.tile_type == 'calendar':
                data.update(self._get_calendar_data())
        except (AccessError, UserError) as error:
            data['error'] = str(error)
        except Exception as error:  # noqa: BLE001 - one bad tile must not blank the page
            _logger.warning("My Work Day: tile %s failed to load", self.id, exc_info=True)
            data['error'] = _("This tile could not be loaded: %s", error)
        return data

    def _get_count_data(self):
        """One count per line, each isolated so a single bad filter is survivable."""
        self.ensure_one()
        model = self._record_model()
        base = Domain(self._eval_domain(self.base_domain))
        lines = []
        total = 0
        for line in self.line_ids:
            entry = {
                'id': line.id,
                'name': line.name,
                'count': 0,
                'color': 'muted',
                'error': False,
            }
            try:
                count = model.search_count(
                    self._full_domain(self._eval_domain(line.domain), base=base))
            except (AccessError, UserError) as error:
                entry['error'] = str(error)
                entry['color'] = 'danger'
            except Exception as error:  # noqa: BLE001
                _logger.warning(
                    "My Work Day: line %s failed to count", line.id, exc_info=True)
                entry['error'] = _("Invalid filter: %s", error)
                entry['color'] = 'danger'
            else:
                entry['count'] = count
                entry['color'] = line._line_color(count)
                total += count
                if not count and self.hide_empty_lines:
                    continue
            lines.append(entry)
        return {
            'lines': lines,
            'total': total if self.show_total else None,
        }

    def _get_value_data(self):
        """One number, counted through the tile's own filter.

        No lines, so nothing here can half-fail: either the count works or the
        tile reports an error, which `_get_tile_data` already handles.
        """
        self.ensure_one()
        count = self._record_model().search_count(self._full_domain())
        return {
            'value': count,
            'color': color_for(
                self.value_color_condition, self.value_color_threshold,
                self.value_color, count),
        }

    def _user_timezone(self):
        return pytz.timezone(self.env.user.tz or self.env.context.get('tz') or 'UTC')

    def _today_bounds(self):
        """Start and end of the user's today, as naive UTC datetimes."""
        self.ensure_one()
        now_local = pytz.utc.localize(fields.Datetime.now()).astimezone(self._user_timezone())
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + relativedelta(days=1)
        return (
            start_local.astimezone(pytz.utc).replace(tzinfo=None),
            end_local.astimezone(pytz.utc).replace(tzinfo=None),
            start_local.date(),
        )

    def _required_field_name(self, field, model):
        """The technical name of a field the tile cannot work without.

        Raises a readable error when it is gone: either the field record itself
        was deleted with its module (the link is then empty), or it still exists
        but the model no longer has it.
        """
        name = field.sudo().name
        if not name:
            raise UserError(_("This tile has lost one of its fields, probably in an "
                              "upgrade. Pick it again in the tile's settings."))
        if name not in model._fields:
            raise UserError(_("The field %s no longer exists.", name))
        return name

    def _get_agenda_data(self):
        """Today's records of this model, in time order.

        This is a list rather than a calendar grid on purpose: it answers "what
        is happening today" without needing to understand every model's
        calendar view.
        """
        self.ensure_one()
        model = self._record_model()
        field_name = self._required_field_name(self.date_field_id, model)
        field = model._fields[field_name]

        start_utc, end_utc, today = self._today_bounds()
        if field.type == 'date':
            day_domain = [(field_name, '=', fields.Date.to_string(today))]
        else:
            day_domain = [
                (field_name, '>=', fields.Datetime.to_string(start_utc)),
                (field_name, '<', fields.Datetime.to_string(end_utc)),
            ]

        domain = self._full_domain(day_domain)
        limit = max(1, self.agenda_limit or 10)
        records = model.search(domain, order='%s asc' % field_name, limit=limit)
        total = model.search_count(domain)

        entries = []
        for record in records:
            value = record[field_name]
            if field.type == 'datetime' and value:
                local = pytz.utc.localize(value).astimezone(self._user_timezone())
                label = local.strftime('%H:%M')
            else:
                label = _("All day")
            entries.append({
                'id': record.id,
                'name': record.display_name,
                'time': label,
            })
        return {
            'entries': entries,
            'total': total,
            'truncated': total > len(entries),
        }

    def _get_calendar_data(self):
        """Everything the browser needs to render a real calendar for this tile.

        The arch is synthesised here rather than read from the model's own
        calendar view, for two reasons. The tile's date field is the one its
        owner picked, which is not necessarily the one the model's view uses;
        and most models have no calendar view at all, while Odoo's generated
        fallback insists on both a start and an end date and raises when a
        model has only one.

        It is deliberately read-only. A dashboard is for looking at, and a
        drag on a tile the size of a postcard is far likelier to be a slip
        than an intention.
        """
        self.ensure_one()
        model = self._record_model()
        field_name = self._required_field_name(self.date_field_id, model)
        # The end and all-day fields are optional, and a field that vanished
        # since the tile was built is simply left out rather than failing the
        # tile: a calendar with one-hour blocks is still a calendar.
        extra = ''
        used = [field_name, 'display_name']
        for attribute, field in (('date_stop', self.date_stop_field_id.sudo()),
                                 ('all_day', self.all_day_field_id.sudo())):
            if field and field.name in model._fields:
                extra += ' %s="%s"' % (attribute, escape(field.name))
                used.append(field.name)
        arch = (
            '<calendar date_start="%s"%s mode="%s" string="%s"'
            ' create="0" edit="0" delete="0" quick_create="0"'
            ' show_date_picker="0" event_limit="3"/>'
        ) % (
            escape(field_name),
            extra,
            escape(self.calendar_mode or 'week'),
            escape(self.name or ''),
        )
        # The domain is resolved here, as everywhere else, so the browser is
        # handed a plain list and never evaluates a stored expression.
        #
        # `fields` describes every field the arch relies on. The browser gets
        # the rest from the model's list view, but a list view only describes
        # the fields it shows -- usually not display_name, which is where the
        # calendar takes each event's title from, and without which every
        # event was drawn as a blank block.
        return {
            'arch': arch,
            'mode': self.calendar_mode,
            'domain': self._full_domain(),
            'fields': model.fields_get(used),
        }

    def _get_breakdown_data(self):
        """How many records fall into each value of the grouping field."""
        self.ensure_one()
        model = self._record_model()
        field_name = self._required_field_name(self.group_field_id, model)
        field = model._fields[field_name]

        # Grouping by a bare date or datetime is rejected outright: without a
        # granularity it would mean one bar per timestamp.
        group_spec = field_name
        if field.type in ('date', 'datetime'):
            group_spec = '%s:%s' % (field_name, self.group_granularity or 'month')

        domain = self._full_domain()
        limit = max(1, self.group_limit or 8)
        # "value asc" sorts on the grouped field itself, which is what makes a
        # date breakdown read chronologically. The limit still applies, so a
        # value sort shows the first N values rather than the N biggest bars.
        order_by, _space, direction = (self.group_order or 'count desc').partition(' ')
        order = '%s %s' % ('__count' if order_by == 'count' else group_spec, direction)
        groups = model.formatted_read_group(
            domain, [group_spec], ['__count'], order=order, limit=limit)

        # formatted_read_group hands back the stored value of a selection
        # field, not its label, so "sale" would show instead of "Sales Order".
        # fields_get resolves selections however they were declared, including
        # the callable and method-name forms.
        selection_labels = {}
        if field.type == 'selection':
            description = model.fields_get([field_name]).get(field_name, {})
            selection_labels = dict(description.get('selection') or [])

        bars = []
        for group in groups:
            value = group.get(group_spec)
            count = group.get('__count', 0)
            bars.append({
                'label': selection_labels.get(value) or self._format_group_value(value),
                'count': count,
                'domain': group.get('__extra_domain') or [],
                'color': color_for(
                    self.bar_color_condition, self.bar_color_threshold,
                    self.bar_color, count),
            })
        # The bar lengths are relative to the biggest bar on show, not to the
        # biggest overall: with a "smallest first" sort the largest value may
        # not even be in the list, and scaling to it would leave every bar a
        # sliver.
        biggest = max((bar['count'] for bar in bars), default=0)
        for bar in bars:
            bar['ratio'] = round(100.0 * bar['count'] / biggest, 1) if biggest else 0
        return {
            'bars': bars,
            'total': sum(bar['count'] for bar in bars),
        }

    def _format_group_value(self, value):
        """Turn a grouped value into something readable on a bar label."""
        if value in (False, None):
            return _("None")
        if value is True:
            return _("Yes")
        if isinstance(value, (tuple, list)) and len(value) == 2:
            return str(value[1])
        if isinstance(value, (datetime.date, datetime.datetime)):
            return fields.Date.to_string(value)
        return str(value)

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    @api.depends('tile_type', 'allowed_model_id', 'base_domain', 'line_ids.domain',
                 'date_field_id', 'group_field_id')
    def _compute_broken_reason(self):
        for tile in self:
            tile.broken_reason = tile._broken_reason() or False

    def _broken_reason(self):
        """Why this tile can no longer be counted, or False when it is fine.

        Checks the shape of the tile rather than running it: validating the
        domains costs nothing, while counting every line of every tile on the
        database would be a report nobody dares run.
        """
        self.ensure_one()
        model = self.env.get(self.model_name)
        if model is None:
            return _("The model %s is no longer installed.", self.model_name)
        for field in (self.date_field_id | self.group_field_id).sudo():
            if field.name not in model._fields:
                return _("The field %s no longer exists.", field.name)
        if self.tile_type in ('agenda', 'calendar') and not self.date_field_id:
            return _("This tile needs a date field and has none.")
        if self.tile_type == 'breakdown' and not self.group_field_id:
            return _("This tile needs a field to group by and has none.")
        candidates = [(_("Base filter"), self.base_domain)]
        candidates += [(line.name, line.domain) for line in self.line_ids]
        for label, domain in candidates:
            try:
                self._validate_domain(domain)
            except (UserError, ValidationError) as error:
                return '%s: %s' % (label, error.args[0] if error.args else error)
        return False

    @api.model
    def action_check_tiles(self):
        """List every tile that would fail, or say that none would.

        Broken tiles already report themselves on the dashboard, but only to
        whoever opens it. This is the same information at the moment an
        administrator wants it: just after an upgrade.
        """
        # It reads every tile on the database, so it is for administrators
        # only, whoever calls the method and however they reach it.
        if not self.env.user.has_group('my_work_day.group_my_work_day_manager'):
            raise AccessError(_("Only My Work Day administrators can check every tile."))
        tiles = self.sudo().search([])
        broken = tiles.filtered(lambda tile: tile._broken_reason())
        if not broken:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'success',
                    'message': _("All %s tiles are fine.", len(tiles)),
                    'next': {'type': 'ir.actions.act_window_close'},
                },
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _("Broken Tiles"),
            'res_model': 'mwd.tile',
            'domain': [('id', 'in', broken.ids)],
            'views': [
                [self.env.ref('my_work_day.mwd_tile_view_list_broken').id, 'list'],
                [False, 'form'],
            ],
            'target': 'current',
            'context': {'create': False},
        }

    # ------------------------------------------------------------------
    # Click-through
    # ------------------------------------------------------------------

    def _menu_action(self):
        """The action behind this tile's menu, or None to open a plain list.

        Only while the user can still see the menu and it still opens this
        tile's model: either can change after the tile was built, and a click
        should then fall back quietly rather than fail. Visibility is the same
        test the navbar uses, which hides a menu whose groups the user lacks or
        whose action they could not read.
        """
        self.ensure_one()
        menu = self.menu_id._filter_visible_menus()
        if not menu or menu.sudo().mwd_res_model != self.model_name:
            return None
        action = menu.sudo().action._get_action_dict()
        action['mwd_menu_id'] = menu.id
        return action

    def _open_action(self, domain, name):
        """An act_window on this tile's model, filtered to what was clicked.

        The domain is resolved here and handed over as a plain list, so the
        browser never evaluates a stored expression.
        """
        self.ensure_one()
        model = self._record_model()
        if model is None:
            raise UserError(_("The model %s is not available.", self.model_name))
        menu_action = self._menu_action()
        if menu_action:
            # The menu provides the frame -- its views, its help text, the app
            # around it -- and the tile provides the records. The menu's own
            # domain is replaced rather than combined, so the list always shows
            # exactly what the tile counted.
            # display_name too: it is what the breadcrumb shows, and the tile's
            # own name is what explains why the list is filtered.
            menu_action.update({
                'name': name, 'display_name': name, 'domain': domain, 'target': 'current',
            })
            return menu_action
        views = [[False, 'list'], [False, 'form']]
        # A calendar tile opens on a calendar, when the model has one of its
        # own: reading a week as a list is a step backwards. Only a real view
        # counts here -- Odoo's generated fallback needs an end date most
        # models lack and would fail as the page opened.
        if self.tile_type == 'calendar' and self.env['ir.ui.view'].sudo().search_count([
            ('model', '=', self.model_name), ('type', '=', 'calendar'),
        ], limit=1):
            views.insert(0, [False, 'calendar'])
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': self.model_name,
            'domain': domain,
            'views': views,
            'target': 'current',
            'context': {'create': False},
        }

    def action_open_line(self, line_id):
        """Open the records behind one counter line."""
        self.ensure_one()
        line = self.line_ids.filtered(lambda l: l.id == line_id)
        if not line:
            raise UserError(_("This line no longer exists."))
        return self._open_action(
            self._full_domain(self._eval_domain(line.domain)),
            '%s / %s' % (self.name, line.name),
        )

    def action_open_tile(self):
        """Open every record the tile looks at."""
        self.ensure_one()
        return self._open_action(self._full_domain(), self.name)

    def action_open_group(self, extra_domain):
        """Open the records behind one breakdown bar."""
        self.ensure_one()
        if not isinstance(extra_domain, (list, tuple)):
            raise UserError(_("Invalid group filter."))
        return self._open_action(self._full_domain(extra_domain), self.name)

    def action_open_record(self, res_id):
        """Open one agenda entry in its form view."""
        self.ensure_one()
        model = self._record_model()
        if model is None:
            raise UserError(_("The model %s is not available.", self.model_name))
        record = model.browse(res_id).exists()
        if not record:
            raise UserError(_("This record no longer exists."))
        record.check_access('read')
        result = {
            'type': 'ir.actions.act_window',
            'res_model': self.model_name,
            'res_id': record.id,
            'views': [[False, 'form']],
            'target': 'current',
        }
        menu_action = self._menu_action()
        if menu_action:
            result['mwd_menu_id'] = menu_action['mwd_menu_id']
        return result

    def action_duplicate_to_my_dashboard(self):
        """Copy this tile onto the current user's own dashboard.

        Ownership is not carried over: the copy belongs to whoever took it.
        """
        dashboard = self.env['mwd.dashboard']._get_or_create_for_user()
        copies = self.env['mwd.tile']
        for tile in self:
            copies |= tile.copy({
                'dashboard_id': dashboard.id,
                'name': _("%s (copy)", tile.name),
            })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': _(
                    "%s added to your dashboard.",
                    ', '.join(copies.mapped('name')),
                ),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
