"""Evaluate a tile filter as data, never as code.

Tile filters are written by ordinary users and evaluated on the server. They
used to go through ``safe_eval``, Odoo's general-purpose Python sandbox, with
a few names made available. A sandbox is a deny-list: it is only as safe as
the list of things someone thought to forbid, and it was found wanting twice --
a record in reach let a filter call ``sudo()`` and take over the database, and
``str.format`` walked attribute chains hidden inside a string out to the
server's configuration.

This module does not execute anything. It parses the filter with Python's own
parser and then evaluates only the node types and calls listed below, which is
exactly what Odoo's filter builder writes:

- literals: strings, numbers, booleans, None, lists and tuples of them,
  including the '&', '|' and '!' domain operators;
- the names passed in (``uid``, the company ids, ``today``, ``now``);
- ``context_today()``;
- ``relativedelta(...)`` with whole-number keyword arguments;
- ``datetime.datetime.combine(d, t)``, ``datetime.time(...)``,
  ``datetime.date(...)`` and ``datetime.timedelta(...)``;
- on a date or datetime: ``+``/``-`` a delta, ``.strftime(...)``,
  ``.replace(...)``, and ``.to_utc()`` on a datetime.

Anything else -- an attribute, a subscript, a comparison, a lambda, a
comprehension, any other call -- is refused because it is not on the list,
whether or not anyone has thought of a way to abuse it. No object with
methods of its own is ever handed to the filter: there is nothing to escape
from.
"""
import ast
import datetime

import pytz
from dateutil.relativedelta import relativedelta


class FilterError(ValueError):
    """The filter uses something a tile filter may not contain."""


DATE_TYPES = (datetime.date,)  # datetime.datetime is a subclass of date
DELTA_TYPES = (relativedelta, datetime.timedelta)

RELATIVEDELTA_KEYS = frozenset({
    'years', 'months', 'weeks', 'days', 'hours', 'minutes', 'seconds',
    'year', 'month', 'day', 'hour', 'minute', 'second',
})
TIMEDELTA_KEYS = frozenset({'weeks', 'days', 'hours', 'minutes', 'seconds'})
DATE_REPLACE_KEYS = frozenset({'year', 'month', 'day'})
DATETIME_REPLACE_KEYS = DATE_REPLACE_KEYS | {'hour', 'minute', 'second'}

# The module-level functions a filter may call, by their dotted name.
DATETIME_CONSTRUCTORS = {
    'datetime.datetime.combine', 'datetime.time', 'datetime.date', 'datetime.timedelta',
}


def evaluate_filter(source, names, today, timezone):
    """The value ``source`` describes, or FilterError.

    :param names: the plain values a filter may refer to by name
    :param today: the date ``context_today()`` returns
    :param timezone: the user's timezone, for ``to_utc()``
    """
    try:
        tree = ast.parse(source.strip(), mode='eval')
    except SyntaxError as error:
        raise FilterError("this is not a valid filter (%s)" % error.msg) from error
    return _Evaluator(names, today, timezone).evaluate(tree.body)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _dotted_name(node):
    """'datetime.datetime.combine' for that chain of plain names, else None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return '.'.join(reversed(parts))


class _Evaluator:

    def __init__(self, names, today, timezone):
        self.names = names
        self.today = today
        self.timezone = timezone

    def refuse(self, node):
        raise FilterError("%s is not allowed in a filter" % ast.unparse(node)[:80])

    def evaluate(self, node):
        method = getattr(self, 'visit_' + type(node).__name__, None)
        if method is None:
            self.refuse(node)
        return method(node)

    # -- values ------------------------------------------------------------

    def visit_Constant(self, node):
        if node.value is None or isinstance(node.value, (str, bool, int, float)):
            return node.value
        self.refuse(node)

    def visit_List(self, node):
        return [self.evaluate(element) for element in node.elts]

    def visit_Tuple(self, node):
        return tuple(self.evaluate(element) for element in node.elts)

    def visit_Name(self, node):
        if node.id not in self.names:
            raise FilterError("%s is not a name a filter can use" % node.id)
        return self.names[node.id]

    def visit_UnaryOp(self, node):
        operand = self.evaluate(node.operand)
        if isinstance(node.op, (ast.USub, ast.UAdd)) and _is_number(operand):
            return -operand if isinstance(node.op, ast.USub) else operand
        self.refuse(node)

    def visit_BinOp(self, node):
        left, right = self.evaluate(node.left), self.evaluate(node.right)
        if isinstance(left, DATE_TYPES) and isinstance(right, DELTA_TYPES):
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
        self.refuse(node)

    # -- calls -------------------------------------------------------------

    def _arguments(self, node, allowed_keys=frozenset(), positional=(0, 0)):
        """Evaluate a call's arguments, refusing any it does not expect.

        ``positional`` is the (fewest, most) positional arguments accepted;
        keyword arguments must be named in ``allowed_keys``.
        """
        fewest, most = positional
        if not fewest <= len(node.args) <= most:
            self.refuse(node)
        values = [self.evaluate(argument) for argument in node.args]
        keywords = {}
        for keyword in node.keywords:
            if keyword.arg not in allowed_keys:  # also refuses **kwargs (arg is None)
                self.refuse(node)
            keywords[keyword.arg] = self.evaluate(keyword.value)
        return values, keywords

    def _whole_numbers(self, node, values):
        if not all(isinstance(value, int) and not isinstance(value, bool) for value in values):
            self.refuse(node)

    def visit_Call(self, node):
        name = _dotted_name(node.func)
        if name == 'context_today':
            self._arguments(node)
            return self.today
        if name == 'relativedelta':
            _positional, keywords = self._arguments(node, RELATIVEDELTA_KEYS)
            self._whole_numbers(node, keywords.values())
            return relativedelta(**keywords)
        if name in DATETIME_CONSTRUCTORS:
            return self._datetime_constructor(node, name)
        if isinstance(node.func, ast.Attribute):
            return self._method(node, self.evaluate(node.func.value), node.func.attr)
        self.refuse(node)

    def _datetime_constructor(self, node, name):
        if name == 'datetime.datetime.combine':
            (day, time), _keywords = self._arguments(node, positional=(2, 2))
            if not isinstance(day, datetime.date) or not isinstance(time, datetime.time):
                self.refuse(node)
            return datetime.datetime.combine(day, time)
        if name == 'datetime.timedelta':
            _positional, keywords = self._arguments(node, TIMEDELTA_KEYS)
            self._whole_numbers(node, keywords.values())
            return datetime.timedelta(**keywords)
        if name == 'datetime.time':
            values, _keywords = self._arguments(node, positional=(0, 3))
            self._whole_numbers(node, values)
            return datetime.time(*values)
        values, _keywords = self._arguments(node, positional=(3, 3))  # datetime.date
        self._whole_numbers(node, values)
        return datetime.date(*values)

    def _method(self, node, value, method):
        if not isinstance(value, DATE_TYPES):
            self.refuse(node)
        if method == 'strftime':
            (pattern,), _keywords = self._arguments(node, positional=(1, 1))
            if not isinstance(pattern, str):
                self.refuse(node)
            return value.strftime(pattern)
        if method == 'replace':
            allowed = (DATETIME_REPLACE_KEYS if isinstance(value, datetime.datetime)
                       else DATE_REPLACE_KEYS)
            _positional, keywords = self._arguments(node, allowed)
            self._whole_numbers(node, keywords.values())
            return value.replace(**keywords)
        if method == 'to_utc' and isinstance(value, datetime.datetime):
            # The browser's meaning: a naive datetime in the user's timezone,
            # converted to UTC -- what "today" must mean on a datetime field.
            self._arguments(node)
            return self.timezone.localize(value).astimezone(pytz.utc).replace(tzinfo=None)
        self.refuse(node)
