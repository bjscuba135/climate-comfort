"""Weekly schedules: profiles, which profile a day uses, and the preset at any time.

Plain Python with no Home Assistant imports, so every rule here is tested on
its own. ``scheduler.py`` connects it to Home Assistant.

A schedule is a list of **profiles**. Each profile has a name, the days it
covers and a list of **slots**; a slot is a start time and a preset and lasts
until the next slot. If a day's first slot does not start at 00:00, the last
preset of the day before carries on until it. As text, one profile per line::

    workday [workdays]: 00:00 sleep, 06:30 comfort, 22:30 sleep
    weekend [weekend]: 00:00 sleep, 08:00 comfort, 23:00 sleep
    home_office [wed] (off): 00:00 sleep, 07:30 comfort, 22:30 sleep

Which profile a day uses, first match wins:

1. a calendar event on that day titled with a profile's name (even one that
   is switched off);
2. an enabled profile for chosen days that include that weekday;
3. the enabled *workdays* or *weekend* profile, by whether the day is a
   workday (holidays count as weekend when a Workday sensor is set);
4. the enabled *all days* profile;
5. none: the schedule has no opinion that day.

A calendar event titled with a preset name (``away``, ``eco``...) sets that
preset while the event lasts, over whatever the profiles say.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAYS_ALL = "all"
DAYS_WORKDAYS = "workdays"
DAYS_WEEKEND = "weekend"
DAY_GROUPS = (DAYS_ALL, DAYS_WORKDAYS, DAYS_WEEKEND)

# Characters a profile name may not contain: they delimit the text format.
FORBIDDEN_NAME_CHARS = "[]:#,"

# How far ahead the next change is looked for.
HORIZON_DAYS = 8

_DAY_ALIASES = {
    "all": DAYS_ALL, "every": DAYS_ALL, "everyday": DAYS_ALL, "daily": DAYS_ALL,
    "workday": DAYS_WORKDAYS, "workdays": DAYS_WORKDAYS, "weekday": DAYS_WORKDAYS,
    "weekdays": DAYS_WORKDAYS,
    "weekend": DAYS_WEEKEND, "weekends": DAYS_WEEKEND,
    **{d: d for d in WEEKDAYS},
    "monday": "mon", "tuesday": "tue", "wednesday": "wed", "thursday": "thu",
    "friday": "fri", "saturday": "sat", "sunday": "sun",
    "tues": "tue", "weds": "wed", "thur": "thu", "thurs": "thu",
}

_LINE = re.compile(
    r"^(?P<name>[^\[\]:#,]+?)\s*"
    r"(?:\[(?P<days>[^\]]*)\])?\s*"
    r"(?P<off>\(\s*off\s*\))?\s*"
    r":\s*(?P<slots>.*)$",
    re.IGNORECASE,
)
_TIME = re.compile(r"^(\d{1,2}):(\d{2})$")


class ScheduleError(ValueError):
    """A schedule that cannot be used, with a message for the person."""


@dataclass(frozen=True)
class Slot:
    """From ``start`` (minutes after the start of the day) the preset is ``preset``."""

    start: int
    preset: str


@dataclass
class Profile:
    """A named day plan and the days it covers.

    ``days`` is ``"all"``, ``"workdays"``, ``"weekend"`` or a tuple of weekday
    numbers (Monday = 0).
    """

    name: str
    days: str | tuple[int, ...] = DAYS_ALL
    enabled: bool = True
    slots: list[Slot] = field(default_factory=list)

    @property
    def chosen_days(self) -> bool:
        return isinstance(self.days, tuple)


@dataclass(frozen=True)
class Event:
    """A calendar event: its title may name a profile or a preset."""

    start: datetime
    end: datetime
    title: str


# ── Times ────────────────────────────────────────────────────────────────────


def parse_time(text: str) -> int:
    """``"06:30"`` → 390 minutes."""
    match = _TIME.match(str(text).strip())
    if not match:
        raise ScheduleError(f"'{text}' is not a time like 06:30")
    hours, minutes = int(match.group(1)), int(match.group(2))
    if hours > 23 or minutes > 59:
        raise ScheduleError(f"'{text}' is not a time of day")
    return hours * 60 + minutes


def format_time(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


# ── Days ─────────────────────────────────────────────────────────────────────


def parse_days(value: Any) -> str | tuple[int, ...]:
    """Days from text (``"mon, wed"``), a group name, or a list of day names."""
    if value is None:
        return DAYS_ALL
    tokens = (
        [str(v) for v in value]
        if isinstance(value, (list, tuple))
        else re.split(r"[\s,]+", str(value))
    )
    tokens = [t.strip().lower() for t in tokens if t.strip()]
    if not tokens:
        return DAYS_ALL
    resolved = []
    for token in tokens:
        if token not in _DAY_ALIASES:
            raise ScheduleError(
                f"'{token}' is not a day: use all, workdays, weekend or mon…sun"
            )
        resolved.append(_DAY_ALIASES[token])
    groups = [t for t in resolved if t in DAY_GROUPS]
    if groups:
        if len(set(resolved)) > 1:
            raise ScheduleError(
                "Use either all, workdays or weekend, or a list of days, not both"
            )
        return groups[0]
    return tuple(sorted({WEEKDAYS.index(t) for t in resolved}))


def format_days(days: str | tuple[int, ...]) -> str | list[str]:
    if isinstance(days, tuple):
        return [WEEKDAYS[d] for d in days]
    return days


def days_overlap(a: str | tuple[int, ...], b: str | tuple[int, ...]) -> bool:
    """Whether two enabled profiles would compete for the same days.

    Chosen days win over the groups on their own days, so they never overlap
    a group; they overlap other chosen days that share a day. ``all`` overlaps
    every group, and a group overlaps itself.
    """
    if isinstance(a, tuple) or isinstance(b, tuple):
        if isinstance(a, tuple) and isinstance(b, tuple):
            return bool(set(a) & set(b))
        return False
    if DAYS_ALL in (a, b):
        return True
    return a == b


# ── Text and dict formats ────────────────────────────────────────────────────


def _parse_slots(text: str, where: str) -> list[Slot]:
    slots = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        pieces = part.split()
        if len(pieces) != 2:
            raise ScheduleError(f"{where}: '{part}' should be a time and a preset, like 06:30 comfort")
        slots.append(Slot(parse_time(pieces[0]), pieces[1].lower()))
    return slots


def parse_text(text: str) -> list[Profile]:
    """Profiles from the text format; see the module docstring."""
    profiles = []
    for number, raw in enumerate(str(text or "").splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = _LINE.match(line)
        if not match:
            raise ScheduleError(
                f"Line {number}: write it as  name [days]: 00:00 preset, 06:30 preset"
            )
        name = match.group("name").strip()
        profiles.append(
            Profile(
                name=name,
                days=parse_days(match.group("days")),
                enabled=match.group("off") is None,
                slots=_parse_slots(match.group("slots"), f"Line {number}"),
            )
        )
    return profiles


def to_text(profiles: Iterable[Profile]) -> str:
    lines = []
    for profile in profiles:
        days = format_days(profile.days)
        head = profile.name
        if days != DAYS_ALL:
            head += f" [{', '.join(days) if isinstance(days, list) else days}]"
        if not profile.enabled:
            head += " (off)"
        slots = ", ".join(f"{format_time(s.start)} {s.preset}" for s in profile.slots)
        lines.append(f"{head}: {slots}")
    return "\n".join(lines)


def from_dicts(data: Any) -> list[Profile]:
    """Profiles from the stored / service / card shape."""
    if not isinstance(data, (list, tuple)):
        raise ScheduleError("The profiles must be a list")
    profiles = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ScheduleError(f"Profile {index} must be an object")
        slots_data = item.get("slots") or []
        if not isinstance(slots_data, (list, tuple)):
            raise ScheduleError(f"Profile {index}: slots must be a list")
        slots = []
        for slot in slots_data:
            if not isinstance(slot, dict) or "start" not in slot or "preset" not in slot:
                raise ScheduleError(f"Profile {index}: every slot needs a start and a preset")
            slots.append(Slot(parse_time(slot["start"]), str(slot["preset"]).lower()))
        profiles.append(
            Profile(
                name=str(item.get("name", "")).strip(),
                days=parse_days(item.get("days", DAYS_ALL)),
                enabled=bool(item.get("enabled", True)),
                slots=slots,
            )
        )
    return profiles


def slot_dicts(slots: Iterable[Slot]) -> list[dict[str, str]]:
    return [{"start": format_time(s.start), "preset": s.preset} for s in slots]


def to_dicts(profiles: Iterable[Profile]) -> list[dict[str, Any]]:
    return [
        {
            "name": p.name,
            "days": format_days(p.days),
            "enabled": p.enabled,
            "slots": slot_dicts(p.slots),
        }
        for p in profiles
    ]


# ── Validation ───────────────────────────────────────────────────────────────


def validate(profiles: list[Profile], valid_presets: Iterable[str]) -> None:
    """Raise ScheduleError for the first problem found."""
    valid = {p.lower() for p in valid_presets}
    seen: dict[str, str] = {}
    for profile in profiles:
        name = profile.name
        if not name:
            raise ScheduleError("Every profile needs a name")
        if any(c in name for c in FORBIDDEN_NAME_CHARS):
            raise ScheduleError(f"Profile '{name}': a name cannot contain [ ] : # or ,")
        if name.lower() in seen:
            raise ScheduleError(f"There are two profiles called '{name}'")
        seen[name.lower()] = name
        if not profile.slots:
            raise ScheduleError(f"Profile '{name}' has no times")
        previous = -1
        for slot in profile.slots:
            if slot.start <= previous:
                raise ScheduleError(
                    f"Profile '{name}': the times must be in order, each later than the one before"
                )
            previous = slot.start
            if slot.preset not in valid:
                raise ScheduleError(
                    f"Profile '{name}': '{slot.preset}' is not an available preset "
                    f"({', '.join(sorted(valid))})"
                )
        if profile.chosen_days and not profile.days:
            raise ScheduleError(f"Profile '{name}' has no days")

    enabled = [p for p in profiles if p.enabled]
    for i, first in enumerate(enabled):
        for second in enabled[i + 1:]:
            if days_overlap(first.days, second.days):
                raise ScheduleError(
                    f"Profiles '{first.name}' and '{second.name}' are both on for the "
                    "same days; switch one off"
                )


def enable_profile(profiles: list[Profile], name: str) -> list[Profile]:
    """Switch one profile on and every enabled profile it would overlap off."""
    target = find_profile(profiles, name)
    if target is None:
        raise ScheduleError(f"There is no profile called '{name}'")
    result = []
    for profile in profiles:
        if profile is target:
            result.append(Profile(profile.name, profile.days, True, list(profile.slots)))
        elif profile.enabled and days_overlap(profile.days, target.days):
            result.append(Profile(profile.name, profile.days, False, list(profile.slots)))
        else:
            result.append(profile)
    return result


def find_profile(profiles: Iterable[Profile], name: str | None) -> Profile | None:
    if not name:
        return None
    wanted = name.strip().lower()
    return next((p for p in profiles if p.name.lower() == wanted), None)


def default_profiles(valid_presets: Iterable[str]) -> list[Profile]:
    """A sensible first schedule from the presets this owner has."""
    valid = list(valid_presets)
    night = next((p for p in ("sleep", "eco", "home") if p in valid), valid[0])
    day = next((p for p in ("home", "comfort") if p in valid), valid[0])
    return [
        Profile("workday", DAYS_WORKDAYS, True, [Slot(0, night), Slot(390, day), Slot(1350, night)]),
        Profile("weekend", DAYS_WEEKEND, True, [Slot(0, night), Slot(480, day), Slot(1380, night)]),
    ]


# ── Which preset applies when ────────────────────────────────────────────────


def _weekday_is_workday(day: date) -> bool:
    return day.weekday() < 5


class Timeline:
    """Answers what a schedule wants at any time, and when that next changes.

    ``now`` values may be in any timezone; slot times are read in ``tz``, the
    local time of the house. ``day_start`` (minutes) moves the moment one
    schedule day hands over to the next, for night shifts.
    """

    def __init__(
        self,
        profiles: list[Profile],
        tz: tzinfo,
        *,
        is_workday: Callable[[date], bool] | None = None,
        events: Iterable[Event] = (),
        day_start: int = 0,
        valid_presets: Iterable[str] = (),
    ) -> None:
        self.profiles = profiles
        self.tz = tz
        self.is_workday = is_workday or _weekday_is_workday
        self.events = [e for e in events if e.end > e.start]
        self.day_start = day_start
        self.valid_presets = {p.lower() for p in valid_presets}

    # Local calendar ---------------------------------------------------------

    def day_begins(self, day: date) -> datetime:
        """When schedule day ``day`` begins, as an aware UTC time."""
        local = datetime.combine(day, time(0), tzinfo=self.tz) + timedelta(minutes=self.day_start)
        return local.astimezone(timezone.utc)

    def at(self, day: date, minutes: int) -> datetime:
        """Slot time ``minutes`` into schedule day ``day``, as an aware UTC time."""
        local = datetime.combine(day, time(0), tzinfo=self.tz) + timedelta(
            minutes=self.day_start + minutes
        )
        return local.astimezone(timezone.utc)

    def schedule_day(self, moment: datetime) -> tuple[date, int]:
        """The schedule day ``moment`` falls in, and the minutes into it."""
        local = moment.astimezone(self.tz).replace(tzinfo=None) - timedelta(minutes=self.day_start)
        return local.date(), local.hour * 60 + local.minute

    # Profiles ---------------------------------------------------------------

    def _calendar_titles(self, day: date) -> set[str]:
        begins, ends = self.day_begins(day), self.day_begins(day + timedelta(days=1))
        return {
            e.title.strip().lower()
            for e in self.events
            if e.start < ends and e.end > begins
        }

    def profile_for(self, day: date) -> Profile | None:
        titles = self._calendar_titles(day)
        if titles:
            for profile in self.profiles:
                if profile.name.lower() in titles:
                    return profile
        enabled = [p for p in self.profiles if p.enabled]
        weekday = day.weekday()
        for profile in enabled:
            if profile.chosen_days and weekday in profile.days:
                return profile
        group = DAYS_WORKDAYS if self.is_workday(day) else DAYS_WEEKEND
        for profile in enabled:
            if profile.days == group:
                return profile
        for profile in enabled:
            if profile.days == DAYS_ALL:
                return profile
        return None

    # Presets ----------------------------------------------------------------

    def scheduled_preset(self, moment: datetime) -> str | None:
        """What the profiles say, without calendar preset events."""
        day, minutes = self.schedule_day(moment)
        profile = self.profile_for(day)
        if profile is None or not profile.slots:
            return None
        current = None
        for slot in profile.slots:
            if slot.start <= minutes:
                current = slot.preset
        if current is not None:
            return current
        previous = self.profile_for(day - timedelta(days=1))
        if previous is not None and previous.slots:
            return previous.slots[-1].preset
        return profile.slots[-1].preset

    def event_preset(self, moment: datetime) -> str | None:
        """A preset set by a calendar event covering ``moment``, if any."""
        covering = [
            e for e in self.events
            if e.start <= moment < e.end and e.title.strip().lower() in self.valid_presets
        ]
        if not covering:
            return None
        return max(covering, key=lambda e: e.start).title.strip().lower()

    def preset_at(self, moment: datetime) -> str | None:
        return self.event_preset(moment) or self.scheduled_preset(moment)

    def _boundaries(self, after: datetime) -> list[datetime]:
        day, _ = self.schedule_day(after)
        candidates: set[datetime] = set()
        for offset in range(0, HORIZON_DAYS + 1):
            current = day + timedelta(days=offset)
            candidates.add(self.day_begins(current))
            profile = self.profile_for(current)
            if profile is not None:
                for slot in profile.slots:
                    candidates.add(self.at(current, slot.start))
        for event in self.events:
            candidates.add(event.start.astimezone(timezone.utc))
            candidates.add(event.end.astimezone(timezone.utc))
        return sorted(c for c in candidates if c > after)

    def next_change(self, moment: datetime) -> tuple[datetime | None, str | None]:
        """When the preset next differs from the one at ``moment``, and what to."""
        current = self.preset_at(moment)
        for boundary in self._boundaries(moment):
            preset = self.preset_at(boundary)
            if preset != current:
                return boundary, preset
        return None, None

    def today_slots(self, moment: datetime) -> list[Slot]:
        day, _ = self.schedule_day(moment)
        profile = self.profile_for(day)
        return list(profile.slots) if profile else []

    def today_profile(self, moment: datetime) -> Profile | None:
        return self.profile_for(self.schedule_day(moment)[0])
