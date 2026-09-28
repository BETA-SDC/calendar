# BETA-SDC Calendar

This repository publishes one-event ICS source files and automatically
builds aggregate feeds for different scopes and time periods.

Subscription page:

https://beta-sdc.github.io/calendar/

Single-event page:

https://beta-sdc.github.io/calendar/events.html

## Repository layout

```text
public/                       public one-event ICS sources
internal/                     internal one-event ICS sources
web/                          subscription page HTML, CSS, and JavaScript
scripts/build_feeds.py        validation and feed/site generator
tests/test_build_feeds.py     feed and site regression tests
outlook-subscription-guide/   Outlook-specific instructions and assets
docs/                         operating guides for calendar links
```

Generated files are written to `site/` locally and are not committed.

## Event source layout

Each source file contains exactly one event. Use a readable filename:

```text
<category>/<year>/<month>/<start-date>-<readable-title>.ics
```

For example:

```text
public/2026/09/2026-09-16-beta-college-autumn-birthday-party.ics
internal/2026/09/2026-09-23-sdc-biweekly-meeting-reminder.ics
```

The filename is for people; the `UID` inside the ICS file is the stable
identity used by calendar applications. Keep the `UID` unchanged when
editing an event.

Current categories:

- `public`: public activities, including the Beta College autumn birthday
  party.
- `internal`: internal events and meetings.

Locations use the following convention:

```text
云谷校区 H4-103
云谷校区 H4-104
云谷校区 H4-121
```

`H4-xxx` is the building/room identifier on Westlake University's Yungu
Campus. Source files do not include Apple Maps coordinates unless they
have been verified.

## Generated feeds

The GitHub Actions workflow generates:

```text
BETA-SDC.ics                 all events
public.ics                   all public activities
internal.ics                 all internal events
2026.ics                     all events in 2026
public/2026.ics              public activities in 2026
internal/2026.ics            internal events in 2026
2026/09.ics                  all events in September 2026
public/2026/09.ics           public activities in September 2026
internal/2026/09.ics         internal events in September 2026
```

The generated files are deployed by the GitHub Actions Pages workflow
from the `main` branch. They are not committed back into the repository.
The workflow also runs once per day so that scheduled changes can be
published without a source commit.

The subscription page loads generated feed metadata from
`calendar-data.json`. Its maintained source files live under `web/`.
The single-event page loads generated event metadata from
`events-data.json`, groups events by date, and provides download, open
subscription-link, and copy-subscription-link actions.

Each source event is also published at the same relative path on GitHub
Pages. For example:

```text
https://beta-sdc.github.io/calendar/public/2026/09/2026-09-29-beta-meet-09-tibet-biodiversity-field-survey.ics
```

Use an individual event URL for an "Add to calendar" link in an email.
Calendar applications decide whether a remote ICS URL is downloaded or
subscribed; iPhone may treat the URL as a one-event subscription. Use an
aggregate subscription URL when recipients should continue receiving
future additions and updates.

For the recommended email wording and `Command + K` instructions, see
[在邮件中添加日历链接](docs/email-calendar-links.md).

## Subscribe

The subscription page provides selectable `webcal://` and HTTPS links.
The stable top-level URLs are:

```text
webcal://beta-sdc.github.io/calendar/BETA-SDC.ics
webcal://beta-sdc.github.io/calendar/public.ics
webcal://beta-sdc.github.io/calendar/internal.ics
```

Use the HTTPS URL when adding a calendar by URL in Google Calendar or
Outlook. The subscription page also has a direct ICS download link:
public downloads use the default filename `BETA.ics`, while internal and
all-event downloads use `BETA-SDC.ics`. Do not download and import the
file if you want automatic updates; use the subscription option instead.

Generated feeds preserve the event properties and subcomponents from the
source ICS files, including reminders (`VALARM`) and attachments
(`ATTACH`). The build does not remove these fields, so subscribed
calendars can continue to deliver event reminders.

Generated feeds request an hourly subscription refresh with
`REFRESH-INTERVAL;VALUE=DURATION:PT1H` and `X-PUBLISHED-TTL:PT1H`.
Calendar applications may allow users to override this suggested interval.

## Updating events

Add, edit, move, or delete one-event ICS files under `public/` or
`internal/`, then commit to `main`. The workflow validates every source
file and rebuilds all aggregate feeds. Month and year options appear
automatically when their directories contain events.

The source directory must match the event's `DTSTART` year and month.
Every event must have a non-empty, repository-wide unique `UID`.

## Local verification

Install dependencies, run the tests, and build the same output used by
GitHub Pages:

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/build_feeds.py --output site
```

Serve `site/` over HTTP when checking the subscription page locally,
because the page loads `calendar-data.json` with `fetch()`:

```bash
python -m http.server 8000 --directory site
```
