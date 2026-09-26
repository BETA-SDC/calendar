# BETA-SDC Calendar

This repository publishes one-event ICS source files and automatically
builds aggregate feeds for different scopes and time periods.

Subscription page:

https://beta-sdc.github.io/calendar/

## Source layout

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
西湖大学云谷校区 H4-103
西湖大学云谷校区 H4-104
西湖大学云谷校区 H4-121
```

`H4-xxx` is the building/room identifier inside the Xihu University
Yungu Campus. Source files do not include Apple Maps coordinates unless
they have been verified.

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

## Subscribe

The subscription page provides selectable `webcal://` and HTTPS links.
The stable top-level URLs are:

```text
webcal://beta-sdc.github.io/calendar/BETA-SDC.ics
webcal://beta-sdc.github.io/calendar/public.ics
webcal://beta-sdc.github.io/calendar/internal.ics
```

Use the HTTPS URL when adding a calendar by URL in Google Calendar or
Outlook. Do not download and import the file if you want automatic
updates; use the subscription option instead.

## Updating events

Add, edit, move, or delete one-event ICS files under `public/` or
`internal/`, then commit to `main`. The workflow validates every source
file and rebuilds all aggregate feeds. Month and year options appear
automatically when their directories contain events.
