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
scripts/calendar_cli.py       GNU-style AI calendar management CLI
bin/calendar                  executable CLI entry point
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

Events have two independent labels. The source directory defines visibility:

- `public`: public activities, including the Beta College autumn birthday
  party.
- `internal`: internal events and meetings.

The VEVENT `STATUS` defines planning state:

- `planned`: `STATUS:CONFIRMED`, or no `STATUS` for existing events.
- `tentative`: `STATUS:TENTATIVE`.

`STATUS:CANCELLED` remains preserved and belongs to the planned category.
An internal event or any tentative event requires the page access password
`betasdc`. Selecting all planning states also requires the password, even
for public events. Both web pages filter by visibility and planning state, hide
restricted events while locked, and share the unlock state within the current
browser-tab session. The lock button clears that state.

This is a lightweight frontend gate for non-sensitive information. Source
files, generated JSON, and ICS subscription URLs remain publicly readable;
the password is not server authentication. The CLI manages all events locally.
See [密码访问说明](docs/key-access.md) for the behavior and limitations.

Calendar names, event summaries, locations (when supplied), and reminder
descriptions must be bilingual, using `中文 / English` in the same field.
Keep shared identifiers such as room numbers and URLs unchanged. For example:

```text
自习打卡营 / Self-Study Check-in Camp
云谷校区 / Yungu Campus H4-103
云谷校区 / Yungu Campus H4-104
云谷校区 / Yungu Campus H4-121
提醒事项 / Reminder
```

Use CRLF line endings and fold ICS content lines at 75 UTF-8 octets without
splitting a character. When updating an event's text, increment `SEQUENCE`
and update `DTSTAMP` and `LAST-MODIFIED`, preserving its `UID`, schedule,
and reminder triggers.

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
status/planned/public.ics    public planned events
status/tentative/public.ics  public tentative events, when present
status/planned/internal.ics  internal planned events
```

Status feeds also have year/month paths such as
`status/planned/public/2026.ics` and `status/planned/public/2026/09.ics`.
Feed metadata keys use `public@planned`, `public@planned:2026`, and
`public@planned:2026-09`. Selecting all statuses uses the legacy scope keys.
The legacy public, internal, and all-event URLs remain stable.
The locked page offers only public planned subscriptions; after unlocking,
all scopes and states are available. The all-events selection means all
currently accessible events.

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
Subscription URLs themselves do not check the password.

Public calendars are named `BETA 公开活动 / Public Events`, internal calendars
are named `BETA-SDC 内部事件 / Internal Events`, and all-event calendars are
named `BETA-SDC 全部活动 / All Events`. Year and month feeds append their period
to the same bilingual name.

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

For AI-assisted operations, use the GNU-style CLI:

```bash
./bin/calendar add -s public --title '活动 / Event' \
  --start 2026-11-01T14:00 --duration-minutes 120 --json
./bin/calendar tentative -s public --title '候选活动 / Candidate Event' \
  --start 2026-11-02 --days 1 --json
./bin/calendar confirm <UID> --start 2026-11-03T14:00 \
  --duration-minutes 120 --title '正式活动 / Scheduled Event' --dry-run --json
./bin/calendar list --json
./bin/calendar search 'math help' --fields uid,title,start,path --limit 5
./bin/calendar agenda --days 14 --json
./bin/calendar show <UID> --json
./bin/calendar inspect /path/to/event.ics --json
./bin/calendar import /path/to/event.ics -s internal --json
./bin/calendar shift <UID> --days 7 --dry-run --json
./bin/calendar links <UID> --json
./bin/calendar validate --json
./bin/calendar build --json
```

`list`, `search`, and `agenda` support scope/status/date filters, `--limit`,
and JSON field selection with `--fields`. `agenda` includes ongoing events
overlapping its date window. `inspect` diagnoses external ICS files and
reports existing UIDs before import. Mutating commands support `--dry-run`
for validation and previews without changing source files. Updating only
the start time preserves the duration; `shift` moves both endpoints.

Create events with an explicit `--end`, timed `--duration-minutes`, or all-day
`--days`. Use `tentative` to create candidate events and `confirm UID` to set
their final fields and transition to planned in one write, preserving the UID,
reminders, attachments, and scope. Omitted fields retain their existing values;
provide `--title` to replace tentative wording and explicit times when the
stored schedule was a placeholder.
The existing `add --status tentative` and `update UID --status planned` commands
remain available. Filter candidates with `list --status tentative`.
`import --status tentative` overrides the imported state; omitting the option
preserves it. Existing events default to planned without changing source files.

The full command contract, JSON output format, safety rules, and add/update/
delete examples are in [AI 操作日历 CLI](docs/ai-calendar-cli.md).

## Local verification

Install dependencies, run the tests, and build the same output used by
GitHub Pages:

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/build_feeds.py --output site
```

To omit internal and tentative events from every generated JSON and ICS file,
run `python scripts/build_feeds.py --output site --public-only` or
`./bin/calendar build --public-only`. The standard Pages build includes all
events and uses the lightweight password gate.

Serve `site/` over HTTP when checking the subscription page locally,
because the page loads `calendar-data.json` with `fetch()`:

```bash
python -m http.server 8000 --directory site
```
