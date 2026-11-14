"""Weeks for the battle pass and the weekly speedruns.

A week runs from Monday 00:00 UTC to the next Monday, and is named like
"2026-W46" (ISO week numbering). The server decides which week it is; the
game asks it, so a wrong clock on a player's computer doesn't matter.

A site can restart the current week (new weekly speedruns, a fresh battle
pass): the week then gets a suffix, like "2026-W46r1", and runs to the same
Monday. Weekly speedruns and battle pass rewards are made from the full name,
so a restarted week has new ones.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def week_id(when: datetime | None = None) -> str:
    when = when or datetime.now(timezone.utc)
    year, week, _day = when.astimezone(timezone.utc).isocalendar()
    return f"{year}-W{week:02d}"


def calendar_week(week: str) -> str:
    """The calendar week of a (possibly restarted) week: "2026-W46r1" -> "2026-W46"."""
    return week.split("r", 1)[0]


def week_start(week: str) -> datetime:
    year, number = calendar_week(week).split("-W")
    return datetime.fromisocalendar(int(year), int(number), 1).replace(tzinfo=timezone.utc)


def week_end(week: str) -> datetime:
    return week_start(week) + timedelta(days=7)


def previous_week(week: str) -> str:
    return week_id(week_start(week) - timedelta(days=1))


def time_left(week: str, now: datetime | None = None) -> str:
    """How long until the week ends, like "3d 4h" or "5h 12m"."""
    left = week_end(week) - (now or datetime.now(timezone.utc))
    secs = max(0, int(left.total_seconds()))
    days, hours, minutes = secs // 86400, secs % 86400 // 3600, secs % 3600 // 60
    return f"{days}d {hours}h" if days else f"{hours}h {minutes}m"
