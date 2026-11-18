"""Today's date, as the business sees it.

The buyer is in Gurugram, so "today" is the date in India (UTC+5:30, no daylight saving),
whatever time zone the server happens to run in. The pipeline asks this module for the date
once per run and passes it into the Validate stage, which itself never reads a clock."""

from datetime import date, datetime, timedelta, timezone

INDIA = timezone(timedelta(hours=5, minutes=30))


def today() -> date:
    return datetime.now(INDIA).date()
