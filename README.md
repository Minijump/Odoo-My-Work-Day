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
model.

**Colour rules.** A line turns info, success, warning or danger past a threshold you
set: a tinted row, a coloured left edge and a coloured number, so *Overdue 3* catches
your eye and *Planned 19* does not. The same rules apply to breakdown bars.

**Three kinds of tile.**

| Type | Shows |
|---|---|
| Counter | One line per filter, with counts |
| Agenda | Today's records on a date field, in time order |
| Breakdown | A `read_group` drawn as bars — orders per salesperson, say. Sort by size or by value, so a date breakdown can read chronologically |

**Tile sizes.** One to four columns wide, one or two rows tall. The grid collapses
to a single column on a phone.

**Icons.** Picked from a grid, not typed: the field stores a Font Awesome class, but
you choose by looking at it, with a search across all 786 icons the bundled font can draw.

**Sharing.** Mark a tile shared and colleagues can copy it onto their own dashboard.
They get your filters, not your data: the copy belongs to them and counts through
their own access rights.

**App shortcuts.** Pick your apps from a dialog on the dashboard; they sit in the
header with their real icons, on the one sticky line that holds the controls.

**Auto-refresh.** Off by default. When on, it pauses while the browser tab is
hidden, so a dashboard left open in a background tab stops polling.

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

36 tests, built on `res.partner` so they pass on a database with nothing else installed.
They cover the access levels, the colour rules, the breakdown sorting, and what happens to a
dashboard when a field a tile depends on disappears.

One trap worth knowing if you add tests: when a test writes raw SQL to simulate a broken
field, it has to `env.flush_all()` first. Records created in the test are still in the ORM's
buffer, and the flush would otherwise land after the `UPDATE` and quietly undo it.


## TO THINK

Conclusions below each point. Nothing here is built yet.

### A real calendar view instead of the agenda list

**Conclusion: feasible in Community, and less work than I expected. Worth doing.**

Three things I checked rather than assumed:

- **FullCalendar ships with Community.** `web/static/lib/fullcalendar/` contains `core`,
  `daygrid`, `timegrid`, `list` and `interaction`. `timegrid` is the hour-by-hour day and
  week grid, which is the part that actually answers "do I have a meeting at 11".
- **The whole calendar view is Community too**, at `web/static/src/views/calendar/`. It is
  not an enterprise view.
- **`calendar.event` — meetings — is a Community app.** Your note says "enterprise model",
  but `addons/calendar` is in the Community tree. So meetings are reachable without
  Enterprise.

The part I was unsure about was embedding a view *inside* a tile, and there is a precedent
that settles it: `addons/board` is the stock "My Dashboard" client action, and it renders
arbitrary views with `<View t-props="viewProps"/>` inside a client action. Community, no
special plumbing.

One more thing that makes this cheaper than it sounds: the `View` component accepts an
`arch` and `fields` directly, so the model does **not** need a calendar view defined. The
tile can synthesise `<calendar date_start="..." mode="day" quick_create="0"/>` from the date
field the agenda tile already asks for. That means a calendar tile works on any model with a
date field, not only on the handful that ship a calendar view.

Rough cost: a new `tile_type`, a server method returning the arch and the resolved domain,
a small OWL wrapper, and some height/scoping CSS. Half a day, most of it spent on making a
full calendar look right inside a small tile.

The one real design question is not technical: a day calendar needs vertical room, so this
probably wants to be a tall tile (height 2) or a full-width one, and it will look cramped at
one column. Worth deciding before building, not after.

### The "back to the app switcher" button

**Conclusion: your instinct is right — a systray button. I would not touch the home button.**

What Enterprise does, as far as I can state without a copy to check against: `web_enterprise`
replaces the Community apps dropdown with a full-screen "home menu" overlay, and the Odoo
logo toggles it. It is a different navigation shell, not a setting. I could not verify this
on this machine — there is no Enterprise source here — so treat it as background, not as a
checked fact.

That is also why I would not aim at it. Anything that hooks the enterprise home button would
be code that cannot be tested here and would do nothing in Community.

The systray is the opposite: `registry.category("systray").add(...)` is Community `web`, it
is how the activities, messaging and debug icons are added, and it renders in both editions
untouched. A small icon next to them that opens the dashboard is roughly 40 lines — a tiny
component, a template, one registry line — and it needs no patching of anything.

It also solves a real problem that exists today: once the dashboard is not your landing page,
there is no quick way back to it other than the app menu.

### Should a tile redirect into the app's own menu?

**Conclusion: doable and worth it, but the "filters the user can remove" part is not
possible in general. Decide on that trade-off first.**

The mechanism works like this. Today a tile click returns a bare `act_window`, so the
breadcrumb stays inside My Work Day. To land "in the Sales app" you need two things: the
menu's own action, and the navbar told which app is current. The menu service exposes exactly
that — `setCurrentMenu(menuId)`, and `doAction` takes an `onActionReady` callback, which is
how `selectMenu` itself does it. So: add an optional menu on the tile (and optionally per
line), have the server load that menu's action, AND our domain into it, and have the client
call `setCurrentMenu` once the action is ready. Falling back to today's behaviour when no
menu is set, as you suggested, is the right default.

Where it breaks down is the removable filter. A domain put on an action is not a search
facet — it is invisible and cannot be cleared. To get a facet the user can remove, the
search view of that model must already define a matching filter, and you then pass
`search_default_<name>`. For an arbitrary tile domain there is no such filter, and no way to
inject one. So the realistic choices are:

- **Hard domain** (what I would do): the user lands in Sales, inside the Sales menu, with the
  tile's filter applied and not removable. Clearing it means using the menu normally.
- **No domain**: land in Sales on the unfiltered list, which loses the point of clicking the
  line.

There is a third option worth weighing: keep today's behaviour and treat it as correct.
The current click-through is *not* a worse version of opening the app — it is a filtered
list with a breadcrumb back to the dashboard, which is arguably what you want when you are
working through a list of things to do. The menu version is better when you intend to *stay*
in Sales afterwards.

Cost is small either way: a `Many2one('ir.ui.menu')` on the tile and the line, a server-side
merge, and a few lines of client code.

### Favourite menus as well as favourite apps

**Conclusion: cheap on the data side, and the picker is where the cost is. I would do it as
"favourite menus" outright rather than as a second list.**

The data already allows it. `mwd_favorite_menu_ids` is a many2many to `ir.ui.menu`; the only
thing restricting it to apps is `domain=[('parent_id', '=', False)]` on the field. Remove
that and sub-menus can be stored today. Permissions come for free: the menu service only ever
hands over menus the user may see, so nothing can appear that they could not already reach.

Two real costs:

- **Icons.** Only root menus carry `webIconData`. A sub-menu has no icon of its own, so
  "Sales / Quotations" would have to borrow the Sales icon, or use a generic one. Borrowing
  the parent's icon is the better answer, and it means two shortcuts under the same app look
  alike — so the label has to carry the meaning, perhaps as "Sales · Quotations".
- **The picker.** The current dialog is a flat grid of apps, which works because there are
  seventeen of them. A full menu tree is hundreds of entries, so it needs grouping by app and
  a search box. That is the bulk of the work: maybe 60-80 lines, plus thought about how to
  show a two-level list without it becoming the app menu again.

My recommendation is to replace rather than add. Two separate lists ("favourite apps" and
"favourite menus") is two concepts for the user to understand and two rows competing for the
same strip of header. One list that happens to allow both depths is simpler to explain and
simpler to build.

## Suggested

Only the ones I think earn their cost.

- **A "nothing to do" state worth seeing.** When every counter on the dashboard is zero,
  the page currently shows a column of zeros. Saying so explicitly — a single quiet line
  instead of five empty tiles — turns the dashboard into something you are pleased to see.
  Cheap: the payload already knows every count.

- **Per-tile refresh timing is in the wrong place.** Auto-refresh is set on the dashboard, so
  a tile counting activities refreshes at the same rate as one counting last year's invoices.
  Not urgent, but if you ever enable refresh by default this becomes the thing that decides
  whether it is reasonable.

- **A hard cap on tiles per dashboard.** Nothing stops a user adding fifty tiles, each with
  ten filters, and every page load then runs five hundred `search_count` queries. One request,
  but a heavy one. A limit — or a warning past, say, twenty tiles — costs almost nothing and
  removes the only way a user can make this module a performance problem for everyone else.
  I would pair it with the per-tile timing above.

- **An "is this filter still valid" check on upgrade.** A broken tile currently reports
  itself when someone opens the dashboard, which is the right behaviour. But nobody finds
  out until they look. A cheap administrator view listing tiles whose domain no longer
  validates would make an upgrade's damage visible at the moment it happens.

Deliberately not suggesting: drag-and-drop tile reordering (the sequence field and the list
view already do it, and dragging inside a CSS grid is a lot of code for a rare action), and
tile templates shared by an administrator (the duplicate-a-shared-tile flow already covers
it).

## Licence

LGPL-3.
