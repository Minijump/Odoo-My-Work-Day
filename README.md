# My Work Day

An Odoo 19 **Community** module that replaces the app-switcher landing page with a
personal dashboard of the work actually waiting for you: draft orders, invoices to
approve, activities due today, and anything else you care to count.

It is written from scratch. It borrows nothing from the enterprise accounting
dashboard, depends only on `base` and `web`, and installs on a plain Community
database.

## What it does

**Tiles.** Each tile points at one model and holds any number of named filters.
A filter line shows its label and its count: *Quotations 4*. Click the line and
you land on that exact list, filtered. Click the tile header and you get the whole
model. Ctrl+click (Cmd+click on a Mac) or middle-click opens any of these in a new
browser tab instead, so the dashboard stays where it is.

**Open in an app.** By default a click opens a plain list under My Work Day. Set a
tile's *Open In* to one of the app's own menus — *Sales › Orders › Quotations*, say —
and clicks land inside that app instead: its menu bar, its views, its kanban and
pivot, with a breadcrumb back to the dashboard. Only menus that show the tile's model
are offered. The list always shows exactly what the tile counted: the menu's own
filter is replaced by the tile's, and its default search filters (a *My Quotations*
facet, for instance) are dropped. The one thing that cannot be had is a filter you can
remove from the search bar — Odoo cannot turn an arbitrary filter into a search facet,
so the tile's filter arrives fixed. A menu the user cannot see falls back to the plain
list.

**Colour rules.** A line turns info, success, warning or danger past a threshold you
set: a tinted row, a coloured left edge and a coloured number, so *Overdue 3* catches
your eye and *Planned 19* does not. The same rules apply to bar charts and to
single numbers.

**Five kinds of tile.**

| Type | Shows |
|---|---|
| Counter | One line per filter, with counts |
| Number | One count, large, for the figure that matters most |
| Today's List | Today's records on a date field, in time order |
| Bar Chart | A `read_group` drawn as bars — orders per salesperson, say. Sort by size or by value, so a chart over dates can read chronologically |
| Calendar | A real calendar grid — Odoo's own calendar view, on the date field you pick |

**The calendar tile is the real thing**, not a drawing of one: the month and week
layouts, the hour grid, the popovers and the time zones are the ones used everywhere
else in Odoo. It is read-only, because a drag on a tile the size of a postcard is
likelier to be a slip than an intention, and it needs room — give it a *Tall* height
and at least a double width.

It does not need the model to have a calendar view. The arch is built around the date
field the tile points at, which is both more useful (you choose the field) and more
widely applicable: Odoo's own generated fallback insists on an end date that most
models do not have, and would refuse.

Which calendar you get is therefore which model and which date field you pick: meetings
are *Calendar Event* on *Start*, the project calendar is *Task* on *Deadline*, and so on
for anything with a date. One tile shows one model; meetings and deadlines together are
two tiles.

Give it an **end date field** too, or every record is drawn exactly one hour long — a
9:00–12:00 meeting as 9:00–10:00 — and an **all-day field**, or an all-day event lands
in the hour grid at whatever time its start happens to hold. You rarely have to look for
them: when the model has a calendar view of its own, picking the date field fills both
in from it.

Clicking the header of a calendar tile opens the model's own calendar view, filtered
the same way, when the model has one; otherwise it opens the list like any other tile.

**A number tile is a counter tile with the lines taken away**, which is the point:
when one figure matters more than the five around it, it should not have to share a
tile with them. It has no filters of its own — the tile's base filter *is* the filter,
since there is nothing for a second one to sit on top of — and it takes the same
colour rules, so a number can turn red on its own terms. Clicking it opens the records
behind it, exactly as clicking a counter line does.

**Tile sizes.** One to four columns wide, one or two rows tall. The grid collapses
to a single column on a phone. A number tile sizes its figure off the tile's height,
so making one tall is how you make its number bigger.

**Icons.** Picked from a grid, not typed: the field stores a Font Awesome class, but
you choose by looking at it, with a search across all 786 icons the bundled font can draw.

**Sharing.** Mark a tile shared and colleagues can copy it onto their own dashboard,
either from the *Shared Tiles* menu or from the copy button next to *Add Tile*, which
picks one without leaving the page. They get your filters, not your data: the copy
belongs to them and counts through their own access rights.

**App shortcuts.** Pick your apps from a dialog on the dashboard; they sit in the
header with their real icons, on the one sticky line that holds the controls.

**All clear.** When every tile comes back with nothing in it, the dashboard says so
in one line instead of drawing a screenful of tiles that each read "Nothing to show".
The tiles are one click away, because "all clear" is only believable if you can check
what was looked at.

**A shortcut back.** An icon in the systray opens the dashboard from anywhere, and so
does **Alt+Shift+W** — Odoo's own hotkey mechanism, so holding Alt shows the hint like it
does for every other button. Once My Work Day is not your landing page there is
otherwise nothing quick that gets you back to it.

**Auto-refresh.** Off by default, and set by an administrator in *Settings → General
Settings → My Work Day* rather than per dashboard: the interval decides how often the
database is queried, which is not a number to leave to each user. Anywhere from every
two minutes to every four hours. When on, it pauses while the browser tab is hidden, so
a dashboard left open in a background tab stops polling.

## Security

Three access levels and two separate mechanisms, and it matters which does what.

### The three levels

Under a single *My Work Day* dropdown on the user form:

| Level | Can |
|---|---|
| Reader | Open their own dashboard. Change nothing. |
| Editor | Build and edit the tiles on their own dashboard. |
| Administrator | Decide which models are selectable, and reach every dashboard. |

Every internal user is a **Reader**, because a dashboard nobody can open is pointless.
**Editor is granted deliberately.** That is the part worth knowing before you install this
on an existing database: out of the box, users can see a dashboard and not build one. On a
deployment where the dashboards are laid out centrally that is exactly right; if you want
everyone building their own, grant Editor to the internal-user group and it behaves the way
it did before the levels existed.

A Reader still gets a dashboard on first visit, created for them, because being unable to
create a record should not mean being unable to open the page.

### The two mechanisms

**The whitelist is governance, not security.** An administrator decides which models
anyone may build a tile on, under *My Work Day → Configuration → Selectable Models*.
It stops users pointing tiles at corners of the database nobody meant them to think
about. **It is empty on install by design** — nothing is offered until an
administrator chooses it. It is enforced server-side by a constraint on the tile,
not only by the form's domain, because a domain is a hint to the client.

**Access rights are the real boundary.** Every count, every breakdown and every
click-through runs in the user's own environment. Record rules and access rights
apply exactly as they do anywhere else, so a tile can never show a number larger
than what that user could already reach from the menus. There is a test that proves
this: it adds a record rule hiding records from a user and asserts the tile count
drops to match.

**One grant on a core model, kept narrow.** Odoo 19 gives ordinary users no access at
all to `ir.model.fields`, the list of fields behind the *Date Field* and *Group By*
pickers. Without it a non-administrator could neither build a Today's List, Bar Chart
or Calendar tile nor even display one. The module therefore lets Readers read field
definitions, and a record rule narrows that to the fields of selectable models — the
grant is no wider than the whitelist. Because every internal user is a Reader,
administrators included, a second rule gives *Access Rights* managers the full list
back; without it the first rule would also trim what an administrator sees under
*Settings → Technical → Fields*. Field names are schema, not data: no record of any
model becomes readable through this.

## Landing page

Two steps, both opt-in:

1. *Settings → General Settings → My Work Day* turns on the default for new users.
2. Any user can click the home icon on the dashboard to make it their own landing
   page, or click it again to go back to the apps.

Odoo 19 does not honour `res.users.action_id` on `/odoo` by itself — the web client
opens the first app in the menu and only falls back to the home action for a broken
URL. The module patches one method, `WebClient._loadDefaultApp`, and the patch is
guarded by a session flag that is only true for users who opted in. Everyone else
runs Odoo's original code.

## Installing

Needs nothing but a Community database.

```bash
odoo-bin -d <database> --addons-path=<odoo>/addons,<this repo> -i my_work_day
```

Then, as an administrator, add a few models under *Configuration → Selectable
Models*. Until you do, users have nothing to build tiles on.

After an upgrade, *Settings → General Settings → My Work Day → Check all tiles* lists
any tile whose filters no longer match the database — a field that disappeared, a
model that was uninstalled. A broken tile already reports itself to whoever opens the
dashboard; this is the same information at the moment an administrator wants it,
instead of waiting for someone to notice. It validates the tiles rather than running
them, so it costs nothing to run on a big database.

Under *Settings → General Settings → My Work Day* you can also cap what a user may
build: how many tiles one dashboard may hold, and how many filters one tile may hold.
Every tile on the page is counted on each load, so without a cap one enthusiastic user
can turn their own page load into hundreds of queries. Leave either limit empty, or at
zero, for no limit — which is how the module behaves out of the box.

The caps apply to what gets added, not to what already exists. Lowering a limit never
breaks a dashboard that is already over it: it stays readable and its tiles stay
editable, and only the next tile or filter is refused. The starter tiles respect the
caps too, because a welcome that tripped over its own limit would leave a new user
with no dashboard at all.

A dashboard is offered starter tiles for whatever is selectable, once. The offer waits
until there is something to offer, so filling the whitelist after people have already
opened the page still works — otherwise everyone who looked too early would be stuck
with an empty dashboard. Once the tiles have been offered they are not offered again,
so clearing your dashboard keeps it clear.

## Developing

`.vscode/launch.json` is git-ignored, so each developer keeps their own. A working
set of configurations covers: create a test database with demo data, run the server
with `--dev=xml`, run the tests, and run the tests on a bare `base` + `web` database.

Two things that bite on Odoo 19 specifically:

- Demo data is **opt-in**. Without `--with-demo` you get an empty database and every
  tile counts zero.
- The test tag is `--test-tags=/my_work_day` and nothing else. `post_install` is a
  global tag rather than a filter, so `/my_work_day,post_install` reads as "this
  module OR anything tagged post_install" and pulls in the whole `web` browser suite.

```bash
odoo-bin -d <database> --addons-path=<odoo>/addons,<this repo> -u my_work_day --test-enable --test-tags=/my_work_day --stop-after-init
```

91 tests, built on `res.partner` so they pass on a database with nothing else installed.
They cover the access levels, the colour rules, the bar chart sorting, the calendar arch
and its end and all-day fields, the limits, the health check, what a non-administrator
can and cannot read, how a tile opens inside an app, and what happens to a dashboard
when a field a tile depends on disappears.

Three traps worth knowing if you add tests:

- A test that checks what a non-administrator can do has to `env.invalidate_all()`
  before switching user. Records the test setup read as the superuser — field
  definitions especially — stay in the ORM cache, and the user then reads them from
  there without any access check. That is how the `ir.model.fields` problem above went
  unnoticed for a while: every test passed, and every real non-administrator got an
  error.

- When a test writes raw SQL to simulate a broken field, it has to `env.flush_all()`
  first. Records created in the test are still in the ORM's buffer, and the flush would
  otherwise land after the `UPDATE` and quietly undo it.
- In Git Bash on Windows, `--test-tags=/my_work_day` is rewritten to a Windows path
  before Odoo ever sees it, and the run silently executes nothing. Prefix the command
  with `MSYS_NO_PATHCONV=1`.

### Why the systray, and not the home button

The shortcut back to the dashboard is a systray item because the systray is Community
`web`: `registry.category("systray").add(...)` is how the activities and messaging
icons get there, it renders in both editions, and it patches nothing.

The alternative would have been to hook the Enterprise home button. As far as I can
state without a copy of Enterprise to check against, `web_enterprise` replaces the
Community apps dropdown with a full-screen home-menu overlay toggled by the logo —
but that is background, not a checked fact, and code aimed at it could not be tested
here and would do nothing in Community.

## Licence

LGPL-3.

## Roadmap

- code audit (redundant code, useless code, structural problems, security issues, 'low
  use' features that take too much code or increase structural complexity, ...)
- update readme
- ?publish on the odoo store?
- go public

Decided against, for the record: chatter on tiles (would add a dependency on `mail`
for an audit trail on mostly personal records, and filter changes would need extra
code to be tracked at all), and a live preview while building a tile (the form already
counts the records behind the base filter, and saving shows the real tile).
