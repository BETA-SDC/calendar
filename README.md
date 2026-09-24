# BETA-SDC Calendar

This repository publishes the BETA-SDC calendar as an iCalendar file.
The source file is kept unchanged and can be replaced directly with a
new valid `.ics` file.

Subscription page:

https://beta-sdc.github.io/calendar/

## Subscribe

Apple Calendar, macOS Calendar, and compatible apps:

```text
webcal://beta-sdc.github.io/calendar/BETA-SDC.ics
```

Generic HTTPS subscription:

```text
https://beta-sdc.github.io/calendar/BETA-SDC.ics
```

Raw GitHub fallback:

```text
https://raw.githubusercontent.com/BETA-SDC/calendar/main/BETA-SDC.ics
```

Use the HTTPS URL when adding a calendar by URL in Google Calendar or
Outlook. Do not download and import the file if you want automatic
updates; use the subscription option instead.

## Updating the calendar

Replace `BETA-SDC.ics` with the latest valid iCalendar file and commit it
to the `main` branch. Keep the filename unchanged so existing
subscriptions continue using the same URL.
