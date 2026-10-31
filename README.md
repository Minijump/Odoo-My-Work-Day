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

**Colour rules.** A line can turn info, success, warning or danger past a threshold
you set, so *Overdue 3* catches your eye and *Planned 19* does not.

**Three kinds of tile.**

| Type | Shows |
|---|---|
| Counter | One line per filter, with counts |
| Agenda | Today's records on a date field, in time order |
| Breakdown | A `read_group` drawn as bars — orders per salesperson, say |

**Tile sizes.** One to four columns wide, one or two rows tall. The grid collapses
to a single column on a phone.

**Sharing.** Mark a tile shared and colleagues can copy it onto their own dashboard.
They get your filters, not your data: the copy belongs to them and counts through
their own access rights.

**App shortcuts.** Pick your apps from the dashboard header; they sit next to the
title with their real icons.

**Auto-refresh.** Off by default. When on, it pauses while the browser tab is
hidden, so a dashboard left open in a background tab stops polling.

## Security

Two separate mechanisms, and it matters which does what.

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
Models*. Until you do, users have nothing to build tiles on. The first time a user
opens the dashboard they get starter tiles for whatever you made selectable.

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

26 tests, built on `res.partner` so they pass on a database with nothing else
installed.

## Licence

LGPL-3.


## TODO
- the favourite apps should be on the same line than My Work Day title (a one line sticky header). Additionally, we can remove this useless title
- instead of a fa class to add, the user should be allowed to select it based on the icon (user do not know the fa name)
- coloring when number respect rule is working, but it looks too light. Can we have also a light background on the whole line? To test and see difference
- If user do a filter based on a field, and the field is removed. Make sure the whole app does not crash (only the tile should not be working)
- allow sorting the bar of graphs in tile setting. Currently is is gibbest first, We may want smallest first + allow to give a color to the lines based on conditions (similar to the other tile type)
- have 3 groups: 1 group that can only see its dashboard but do no change on it, one group that can edit its own dashboard and one admin group that can do everything

## TO THINK
- Is having a real calendar view too complex. The current view is ok but not as good as a real calendar view. If a real calendar view brings much more complexity, keep it as is. The thing is that, at one point, I would like people to see if for example they have meetings, ... in their agenda (enterprise model), but the current view will not allow it. Once again, if too complex or if you are not sure on how you could do this (because you do not have access to enterpise for example), forget about it. We will see this later.
- How is the 'return to app switcher' button works in enterprise? The objective was that when clicking on the home btn, we would be redirected to this dashboard. On the 'favourite' app bar, we would have the button to allow going on the real app switcher. If you do not know it is ok. Maybe the best thing to do, to make sure that it is also working in community, would be to add a small 'icon' button next to the debug, activities, discuss icon on top right. This button would allow to open the dashboard easily (as if we clicked on the app). This should be working in community and enterprise I think. This is probably the best thing to do in fact. 
- Should the 'tile redirection' redirect to a menu selected during config of the tile? The problem is that when clicking on the tiles we always get redirected to a view inside the my daily dashboard app while the user may want to go in the sale app for example - TO THINK BEFORE DOING ANYTHING. (for tile of tile lines we could allow to add a menu, if no menu it redirects to the view as it is the case right now, if menu it redirects to the menu, with filters the user can remove?)
- Investigate if instead/in addition of 'favourite apps' we could do 'favourite menus' (same icon but instead of only the app name, it would be menu name) - think how much code it would add and how much difficultoes in parametring,... This app favourite list is already an improvment compared to the other app switcher
