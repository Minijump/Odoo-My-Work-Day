# Odoo-My-Work-Day
Creation of a dashboard that aims to replace Odoo's main page

Instead of the app switcher as default odoo menu, we should be able to see a 'daily dashboard' (app switcher should still be available). The goal is to display the work the user has to do. For example: 2 sale orders in draft, 4 invoices to approve, 3 purchase where there is an error in mail sending,... This Dashboard should look similar (in design) to the Dashboard which is used in odoo standard for the accounting app. However, note that this is an enterprise module and I want mine to be usable in a Community db, so do not re-use/copy any components, this is only an example.

The suggested architecture is the Following (open to discussion)
Base feature:
- Every users should be able to create their own Dashboard tiles
- In every of these tiles, they will select a model and several filters. For each filters they will also provide a name. Such as 'name = draft; filter = status == draft'. ON the Dashboard tile, we will see a line 'draft = number of draft order'. Clicking on this line/on the number would redirect to a list view that is filtered accordingly. A tile can of course contain several filters. And a Dashboard have several tiles.
- It is essential that an admin can select what are the models,... the user can select, we do not want the user to bypass some 'hidden menus'

Possible improvements:
- It would be nice if the user could also define things such a 'color rules' for each filters. Such as if there is more than 3 draft, color of the line should be red.
- It would like to enable a 'calendar' tile, that would show the calendar of the user for this day (one of the calendar, in odoo we can find several different calendars so this feature may be challenging)
- It would be nice if the user could also define 'graphs': such as bar graphs displaying draft orders per employee of their team. This feature seems really nice but maybe complex?
- It would be nice if the sizes of the tiles were customizable. Let's say we define that a Dashboard is a 4x3 tiles, we should be able to say that the tile w takes more spaces than the y. I do not know if this is easily feasible and working with mobile views,...
- It would also be nice if we could select 'favourite' apps, those apps would be displayed on the daily dashboard, maybe the best thing would be a bottom bar with the favourite app, and an app switcher iconthat redirects to the app switcher? (for community there is no app switcher but it would simply open the menu)
- It would be nice if the users could 'share' their tile: the idea would be that one of them creates the required filters, and every members that want it/are allowed to, can duplicate it so that they have the same filters in their dashboard. Note that I think that a duplicate function could be enough, the only thing is that 'owner' should be re,oved at duplicate.
- A tile with notifications may also be great. Same things for tasks to doµ
- If possible, an auto refresh of the page evey x time would be very great, so that the user do not need to refresh the page to see new things. Note that too much refresh may increase databse load and too few may be useless. So this feature may not be the best idea.

