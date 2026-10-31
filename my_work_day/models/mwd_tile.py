import datetime
import logging

import pytz
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import safe_eval as safe_eval_module
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

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
        [('count', 'Counters'), ('agenda', "Today's Agenda"), ('breakdown', 'Breakdown')],
        string='Type', default='count', required=True,
        help="Counters: one line per named filter, showing how many records match.\n"
             "Today's Agenda: the records of this model happening today.\n"
             "Breakdown: how many records fall into each value of a field.",
    )
    icon = fields.Char(
        string='Icon', default='fa-list',
        help="A Font Awesome icon name, for example fa-shopping-cart.")
    width = fields.Selection(
        [('1', 'Normal'), ('2', 'Double width'), ('3', 'Triple width'), ('4', 'Full width')],
        string='Width', default='1', required=True)
    height = fields.Selection(
        [('1', 'Normal'), ('2', 'Tall')], string='Height', default='1', required=True)

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

    # -- agenda tiles --
    date_field_id = fields.Many2one(
        'ir.model.fields', string='Date Field', ondelete='set null',
        domain="[('model', '=', model_name), ('ttype', 'in', ['date', 'datetime']),"
               " ('store', '=', True)]",
        help="The field that says when a record happens.")
    agenda_limit = fields.Integer(string='Maximum Entries', default=10)

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

    # ------------------------------------------------------------------
    # Consistency
    # ------------------------------------------------------------------

    @api.onchange('allowed_model_id')
    def _onchange_allowed_model_id(self):
        """Clear anything that referred to the previous model."""
        self.date_field_id = False
        self.group_field_id = False
        self.base_domain = '[]'
        for line in self.line_ids:
            line.domain = '[]'
            line.model_name = self.allowed_model_id.model_name
        if self.allowed_model_id.date_field_id:
            self.date_field_id = self.allowed_model_id.date_field_id

    @api.constrains('allowed_model_id')
    def _check_model_allowed(self):
        """A user may only build on a model an administrator made available.

        The field's domain already filters the dropdown, but a domain is only a
        hint to the client. This is the part that actually holds.
        """
        available = self.env['mwd.allowed.model']._search_available()
        for tile in self:
            if tile.user_id.id != self.env.uid and not self.env.user.has_group('base.group_system'):
                continue
            if tile.allowed_model_id not in available:
                raise ValidationError(_(
                    "You are not allowed to build a tile on %s.",
                    tile.allowed_model_id.display_name,
                ))

    @api.constrains('base_domain')
    def _check_base_domain(self):
        for tile in self:
            tile._validate_domain(tile.base_domain)

    @api.constrains('tile_type', 'date_field_id', 'group_field_id')
    def _check_required_fields(self):
        for tile in self:
            if tile.tile_type == 'agenda' and not tile.date_field_id:
                raise ValidationError(_("An agenda tile needs a date field."))
            if tile.tile_type == 'breakdown' and not tile.group_field_id:
                raise ValidationError(_("A breakdown tile needs a field to group by."))

    @api.constrains('date_field_id', 'group_field_id', 'allowed_model_id')
    def _check_fields_belong_to_model(self):
        for tile in self:
            for field in (tile.date_field_id, tile.group_field_id):
                if field and field.model != tile.model_name:
                    raise ValidationError(_(
                        "The field %(field)s does not belong to %(model)s.",
                        field=field.name, model=tile.model_name,
                    ))

    @api.model_create_multi
    def create(self, vals_list):
        tiles = super().create(vals_list)
        tiles._sync_line_model_name()
        return tiles

    def write(self, vals):
        result = super().write(vals)
        if 'allowed_model_id' in vals:
            self._sync_line_model_name()
        return result

    def _sync_line_model_name(self):
        """Keep the lines' helper copy of the model name in step with the tile.

        ``model_name`` on a line exists only so the domain editor widget knows
        which model to offer fields for. Counting never trusts it.
        """
        for tile in self:
            lines = tile.line_ids.filtered(lambda l: l.model_name != tile.model_name)
            if lines:
                lines.model_name = tile.model_name

    # ------------------------------------------------------------------
    # Domain handling
    # ------------------------------------------------------------------

    def _domain_eval_context(self):
        """Names a user may use inside a tile domain.

        Deliberately small: enough to write "mine" and "today" filters, and
        nothing that reaches the ORM or the file system. The date and time
        modules are Odoo's own wrapped versions, which expose only a safe
        subset of attributes -- safe_eval refuses a raw module outright.
        """
        self.ensure_one()
        return {
            'uid': self.env.uid,
            'user': self.env.user.with_context({}),
            'company_id': self.env.company.id,
            'company_ids': self.env.companies.ids,
            'allowed_company_ids': self.env.companies.ids,
            'time': safe_eval_module.time,
            'datetime': safe_eval_module.datetime,
            'dateutil': safe_eval_module.dateutil,
            'relativedelta': relativedelta,
            'context_today': lambda: fields.Date.context_today(self),
            'today': fields.Date.context_today(self),
            'now': fields.Datetime.now(),
        }

    def _eval_domain(self, domain_string):
        """Turn a stored domain string into a real domain, or raise UserError."""
        self.ensure_one()
        if not domain_string or not domain_string.strip():
            return []
        try:
            domain = safe_eval(domain_string, self._domain_eval_context())
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

    def _full_domain(self, extra_domain=()):
        """The tile's base filter combined with a line's own filter."""
        self.ensure_one()
        return list(Domain(self._eval_domain(self.base_domain)) & Domain(list(extra_domain)))

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
            elif self.tile_type == 'agenda':
                data.update(self._get_agenda_data())
            elif self.tile_type == 'breakdown':
                data.update(self._get_breakdown_data())
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
                count = model.search_count(self._full_domain(self._eval_domain(line.domain)))
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

    def _today_bounds(self):
        """Start and end of the user's today, as naive UTC datetimes."""
        self.ensure_one()
        timezone = pytz.timezone(self.env.user.tz or self.env.context.get('tz') or 'UTC')
        now_local = pytz.utc.localize(fields.Datetime.now()).astimezone(timezone)
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + relativedelta(days=1)
        return (
            start_local.astimezone(pytz.utc).replace(tzinfo=None),
            end_local.astimezone(pytz.utc).replace(tzinfo=None),
            start_local.date(),
        )

    def _get_agenda_data(self):
        """Today's records of this model, in time order.

        This is a list rather than a calendar grid on purpose: it answers "what
        is happening today" without needing to understand every model's
        calendar view.
        """
        self.ensure_one()
        model = self._record_model()
        field_name = self.date_field_id.name
        field = model._fields.get(field_name)
        if field is None:
            raise UserError(_("The field %s no longer exists.", field_name))

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
                local = pytz.utc.localize(value).astimezone(
                    pytz.timezone(self.env.user.tz or 'UTC'))
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

    def _get_breakdown_data(self):
        """How many records fall into each value of the grouping field."""
        self.ensure_one()
        model = self._record_model()
        field_name = self.group_field_id.name
        field = model._fields.get(field_name)
        if field is None:
            raise UserError(_("The field %s no longer exists.", field_name))

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
    # Click-through
    # ------------------------------------------------------------------

    def _open_action(self, domain, name):
        """An act_window on this tile's model, filtered to what was clicked.

        The domain is resolved here and handed over as a plain list, so the
        browser never evaluates a stored expression.
        """
        self.ensure_one()
        model = self._record_model()
        if model is None:
            raise UserError(_("The model %s is not available.", self.model_name))
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': self.model_name,
            'domain': domain,
            'views': [[False, 'list'], [False, 'form']],
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
        return {
            'type': 'ir.actions.act_window',
            'res_model': self.model_name,
            'res_id': record.id,
            'views': [[False, 'form']],
            'target': 'current',
        }

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
