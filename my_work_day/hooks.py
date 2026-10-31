import logging

_logger = logging.getLogger(__name__)

# Models worth offering out of the box, with the date field an agenda tile
# should default to. Anything not installed is skipped, so this list can
# mention models from apps the database does not have.
DEFAULT_ALLOWED_MODELS = [
    ('mail.activity', 'date_deadline', True),
    ('sale.order', 'date_order', True),
    ('purchase.order', 'date_order', True),
    ('account.move', 'invoice_date_due', True),
    ('project.task', 'date_deadline', True),
    ('crm.lead', 'date_deadline', True),
    ('stock.picking', 'scheduled_date', True),
    ('helpdesk.ticket', None, False),
    ('hr.leave', 'request_date_from', True),
    ('hr.expense', 'date', True),
    ('calendar.event', 'start', True),
    ('res.partner', None, False),
]


def post_init_hook(env):
    """Seed the selectable-model whitelist.

    Without this an administrator would have to build the list from nothing
    before anyone could make a single tile. These are suggestions only: the
    records are ordinary data an administrator can edit or delete.
    """
    allowed_model = env['mwd.allowed.model']
    ir_model = env['ir.model']
    created = 0

    for model_name, date_field_name, allow_agenda in DEFAULT_ALLOWED_MODELS:
        if model_name not in env:
            continue
        model_record = ir_model.sudo().search([('model', '=', model_name)], limit=1)
        if not model_record:
            continue
        if allowed_model.sudo().search_count([('model_id', '=', model_record.id)]):
            continue

        date_field = env['ir.model.fields'].sudo().browse()
        if date_field_name:
            date_field = env['ir.model.fields'].sudo().search([
                ('model', '=', model_name),
                ('name', '=', date_field_name),
                ('ttype', 'in', ['date', 'datetime']),
            ], limit=1)

        allowed_model.sudo().create({
            'model_id': model_record.id,
            'allow_agenda': allow_agenda and bool(date_field),
            'date_field_id': date_field.id if date_field else False,
        })
        created += 1

    _logger.info("My Work Day: %s selectable models seeded", created)
