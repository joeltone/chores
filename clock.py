"""Single source of truth for what day/time it is for chore purposes.

The household runs on Manitoba time regardless of where the bot process
happens to be hosted, so all "today"/due-date/scheduling logic should read
the current date and time through this module rather than calling
date.today() / datetime.now() directly.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Winnipeg")


def now() -> datetime:
    """Current time in the app's timezone (Manitoba)."""
    return datetime.now(TZ)


def today() -> date:
    """Current calendar date in the app's timezone (Manitoba)."""
    return now().date()
