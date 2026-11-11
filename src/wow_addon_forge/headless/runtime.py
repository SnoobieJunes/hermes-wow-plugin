"""Headless WoW client simulation runtime (created 2026-11-11).

Purpose:
    Provide a deterministic, hermetic multi-client WoW: Forever 1.60.1 scenario
    runtime in which real addon Lua runs against the pure-Lua environment from
    ``lua_env`` while Python owns the virtual clock, the addon-message network,
    guild/group/instance state, API-index strictness, and SavedVariables.

Invariants owned by this file:
- The virtual clock only moves through ``World.advance``; timers and reordered
  network deliveries run in due-time order on that one clock, never on a wall
  clock, so a scenario is reproducible to the event.
- A scenario may only name events, templates, globals, and namespace members
  the supplied ``ApiIndex`` knows, pre-indexed once per ``World``; anything
  else fails the way a typo against the real client fails, instead of being
  silently invented here.
- Addon messages are delivered as ``CHAT_MSG_ADDON`` only to online recipients
  who registered the prefix, behind the same byte-length, restriction, and
  throttling gates the documented result enums describe.
- SavedVariables cross the Lua/Python boundary only through ``savedvars_io``,
  so a reload restores exactly what the client could have written to disk.
"""

from __future__ import annotations

import heapq
import os
import random
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .. import luavm, tocfile
from ..apidocs import KINDS, SCHEMA_VERSION, ApiIndex
from ..env import FileSystem, RealFileSystem
from .lua_env import install_bootstrap
from .savedvars_io import export_saved_value, import_saved_value

__all__ = [
    "PREFIX_RESULT",
    "RESTRICTION_STATE",
    "RESTRICTION_TYPE",
    "SEND_RESULT",
    "HeadlessError",
    "LuaErrorRecord",
    "SimulatedClient",
    "World",
    "minimal_api_index",
]

# [2026-11-11 T-007] These four tables are the documented WoW: Forever 1.60.1 enum
# values; they seed every World so a custom ApiIndex that omitted an enum cannot
# change the numeric results addon code branches on, while an index that carries
# the enum overlays its values per key and wins.
SEND_RESULT: dict[str, int] = {
    "Success": 0,
    "InvalidPrefix": 1,
    "InvalidMessage": 2,
    "AddonMessageThrottle": 3,
    "InvalidChatType": 4,
    "NotInGroup": 5,
    "TargetRequired": 6,
    "InvalidChannel": 7,
    "ChannelThrottle": 8,
    "GeneralError": 9,
    "NotInGuild": 10,
    "AddOnMessageLockdown": 11,
    "TargetOffline": 12,
}

PREFIX_RESULT: dict[str, int] = {
    "Success": 0,
    "DuplicatePrefix": 1,
    "InvalidPrefix": 2,
    "MaxPrefixes": 3,
}

RESTRICTION_TYPE: dict[str, int] = {
    "Combat": 0,
    "Encounter": 1,
    "ChallengeMode": 2,
    "PvPMatch": 3,
    "Map": 4,
    "Chat": 5,
}

RESTRICTION_STATE: dict[str, int] = {
    "Inactive": 0,
    "Activating": 1,
    "Active": 2,
}

_CORE_ENUMS: dict[str, dict[str, int]] = {
    "SendAddonMessageResult": SEND_RESULT,
    "RegisterAddonMessagePrefixResult": PREFIX_RESULT,
    "AddOnRestrictionType": RESTRICTION_TYPE,
    "AddOnRestrictionState": RESTRICTION_STATE,
}

_CORE_FUNCTIONS: tuple[str, ...] = (
    "C_ChatInfo.SendAddonMessage",
    "C_ChatInfo.RegisterAddonMessagePrefix",
    "C_ChatInfo.IsAddonMessagePrefixRegistered",
    "C_ChatInfo.GetRegisteredAddonMessagePrefixes",
    "C_RestrictedActions.IsAddOnRestrictionActive",
    "C_RestrictedActions.GetAddOnRestrictionState",
    "C_EventUtils.IsEventValid",
    "C_Timer.After",
    "C_Timer.NewTimer",
    "C_Timer.NewTicker",
    "C_UI.Reload",
    "C_GuildInfo.GuildRoster",
    "C_Item.GetItemInfo",
    "CreateFrame",
    "GetTime",
    "GetServerTime",
    "InCombatLockdown",
    "issecretvalue",
    "seterrorhandler",
    "geterrorhandler",
    "IsLoggedIn",
    "IsInGuild",
    "GetRealmName",
    "UnitName",
    "UnitFullName",
    "UnitGUID",
    "UnitIsUnit",
    "UnitIsInMyGuild",
    "GetGuildInfo",
    "GetNumGuildMembers",
    "GetGuildRosterInfo",
    "IsInGroup",
    "IsInRaid",
    "GetNumGroupMembers",
    "IsInInstance",
    "GetInstanceInfo",
    "GetPVPLifetimeStats",
    "GetBuildInfo",
)

_CORE_EVENTS: tuple[str, ...] = (
    "ADDON_LOADED",
    "PLAYER_LOGIN",
    "PLAYER_ENTERING_WORLD",
    "PLAYER_LOGOUT",
    "CHAT_MSG_ADDON",
    "ADDON_RESTRICTION_STATE_CHANGED",
    "GUILD_ROSTER_UPDATE",
    "GROUP_ROSTER_UPDATE",
    "ENCOUNTER_END",
    "BOSS_KILL",
    "PVP_MATCH_COMPLETE",
    "PLAYER_PVP_KILLS_CHANGED",
    "NEW_MOUNT_ADDED",
    "PLAYER_LEVEL_UP",
    "ADDON_ACTION_FORBIDDEN",
    "ADDON_ACTION_BLOCKED",
)

_CORE_TEMPLATES: tuple[str, ...] = (
    "BasicFrameTemplateWithInset",
    "UIPanelButtonTemplate",
    "UIPanelCloseButton",
    "UIPanelScrollFrameTemplate",
    "InputBoxTemplate",
    "BackdropTemplate",
)

_CORE_WIDGETS: dict[str, dict[str, Any]] = {
    "Frame": {"inherits": ["Region"], "methods": []},
    "Button": {"inherits": ["Frame"], "methods": []},
    "CheckButton": {"inherits": ["Button"], "methods": []},
    "EditBox": {"inherits": ["Frame"], "methods": []},
    "ScrollFrame": {"inherits": ["Frame"], "methods": []},
    "StatusBar": {"inherits": ["Frame"], "methods": []},
    "FontString": {"inherits": ["Region"], "methods": []},
    "Texture": {"inherits": ["Region"], "methods": []},
    "Region": {"inherits": ["ScriptObject"], "methods": []},
    "ScriptObject": {"inherits": [], "methods": []},
}

_ALWAYS_NAMESPACES: tuple[str, ...] = (
    "C_ChatInfo",
    "C_RestrictedActions",
    "C_EventUtils",
    "C_Timer",
    "C_UI",
    "C_GuildInfo",
)

# [2026-11-11 T-007] The throttle model is two token buckets refilled from the
# virtual clock: a burst of ten messages is legal, the sustained rate is one per
# second, and advancing scenario time is the only way tokens come back.
_BUCKET_CAPACITY = 10.0
_BUCKET_REFILL_PER_SECOND = 1.0
_MAX_REGISTERED_PREFIXES = 255


class HeadlessError(RuntimeError):
    """Raised for an invalid headless scenario operation.

    Why this exists:
        A scenario bug (firing an event the client does not have, loading a
        folder with no TOC) must be distinguishable from a Lua error inside the
        addon under test, so scenario misuse gets its own error type instead of
        being recorded as addon behaviour.

    Args:
        message: What the scenario did wrong, in one sentence.

    Returns:
        Nothing; this is an exception type.

    Failure modes:
        None at construction.
    """


@dataclass(frozen=True)
class LuaErrorRecord:
    """One Lua error captured from a simulated client.

    Why this exists:
        The real client routes addon errors to an error handler instead of
        aborting the session; scenarios need those errors afterwards as data,
        stamped with scenario time, so a failure can be asserted on exactly.

    Args:
        message: Lua's error message text.
        stack: The Lua stack trace text, or an empty string when unavailable.
        time: Virtual elapsed seconds on the owning ``World`` when the error
            was recorded.

    Returns:
        Nothing; this is a data holder.

    Failure modes:
        None at construction.
    """

    message: str
    stack: str
    time: float


@dataclass
class _ScheduledCall:
    # [2026-11-11 T-007] Cancellation is a flag on the queued item, not a heap
    # removal: timer handles, reload, and logout can all cancel without knowing
    # where the item sits, and advance simply skips a cancelled item it pops.
    owner: SimulatedClient | None
    callback: Callable[[], None]
    cancelled: bool = False

    def __call__(self) -> None:
        if not self.cancelled:
            self.callback()


@dataclass
class _LoadedAddon:
    name: str
    path: str
    toc: tocfile.TocFile


@dataclass
class _TimerHandleState:
    cancelled: bool = False
    scheduled: _ScheduledCall | None = None
    fired: int = 0

    def is_cancelled(self) -> bool:
        return self.cancelled


@dataclass
class _TokenBucket:
    tokens: float = _BUCKET_CAPACITY
    last_refill: float = 0.0


def _minimal_entry(name: str, kind: str) -> dict[str, Any]:
    return {
        "name": name,
        "kind": kind,
        "restricted": False,
        "secret": {"args": None, "returns": False, "conditions": []},
        "deprecated": False,
        "documented": False,
        "source": "minimal",
    }


def _namespace_of(name: str) -> str | None:
    if "." not in name:
        return None
    namespace = name.rsplit(".", 1)[0]
    return namespace or None


def minimal_api_index(
    *,
    extra_functions: Iterable[str] = (),
    extra_events: Iterable[str] = (),
    extra_templates: Iterable[str] = (),
) -> ApiIndex:
    """Build the small hermetic API index a scenario runs on by default.

    Why this exists:
        Most scenarios should not need the synced 12,949-function mirror index
        to exist on disk; this self-contained index carries exactly the core
        WoW: Forever 1.60.1 surface the simulation implements, so addon code is
        still checked against a closed API world while tests stay hermetic.

    Args:
        extra_functions: Additional function names (bare or ``Namespace.Name``)
            the scenario wants treated as documented API.
        extra_events: Additional valid event names.
        extra_templates: Additional valid frame template names.

    Returns:
        An ``ApiIndex`` with ``schema=SCHEMA_VERSION``, ``flavor="forever"``,
        ``build="1.60.1.70888"`` and ``source="minimal"``, holding the core
        functions, events, enums, templates, and widgets plus any extras, in
        the same entry shapes ``apidocs.build_index`` produces.

    Failure modes:
        None for ordinary inputs; a non-iterable extra raises ``TypeError``
        from the iteration that consumes it.
    """
    entries: dict[str, dict[str, dict[str, Any]]] = {kind: {} for kind in KINDS}
    for function_name in dict.fromkeys((*_CORE_FUNCTIONS, *extra_functions)):
        name = str(function_name)
        entry = _minimal_entry(name, "function")
        entry["namespace"] = _namespace_of(name)
        entry["system"] = None
        entry["args"] = []
        entry["returns"] = []
        entry["flags"] = {}
        entry["c_api"] = True
        entries["function"][name] = entry
    for event_name in dict.fromkeys((*_CORE_EVENTS, *extra_events)):
        name = str(event_name)
        entry = _minimal_entry(name, "event")
        entry["system"] = None
        entry["args"] = []
        entry["returns"] = []
        entry["flags"] = {}
        entries["event"][name] = entry
    for short_name, values in _CORE_ENUMS.items():
        entry = _minimal_entry(f"Enum.{short_name}", "enum")
        entry["values"] = dict(values)
        entries["enum"][entry["name"]] = entry
    for template_name in dict.fromkeys((*_CORE_TEMPLATES, *extra_templates)):
        name = str(template_name)
        entry = _minimal_entry(name, "template")
        entry["widget"] = None
        entry["inherits"] = None
        entries["template"][name] = entry
    widgets: dict[str, Any] = {
        widget_name: {
            "inherits": list(widget_data["inherits"]),
            "methods": list(widget_data["methods"]),
        }
        for widget_name, widget_data in _CORE_WIDGETS.items()
    }
    data: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "flavor": "forever",
        "build": "1.60.1.70888",
        "source": "minimal",
        "generated_at": 0.0,
        "documentation_files": 0,
        "counts": {kind: len(entries[kind]) for kind in KINDS},
        "warnings": [],
        "widgets": widgets,
        "entries": entries,
    }
    return ApiIndex(data)


def _mapping_section(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    section = data.get(key)
    return section if isinstance(section, Mapping) else {}


def _kind_entries(data: Mapping[str, Any], kind: str) -> dict[str, Mapping[str, Any]]:
    raw = _mapping_section(_mapping_section(data, "entries"), kind)
    return {str(name): entry for name, entry in raw.items() if isinstance(entry, Mapping)}


def _entry_values(entry: Mapping[str, Any]) -> dict[str, Any]:
    values = entry.get("values")
    if not isinstance(values, Mapping):
        return {}
    return {str(key): value for key, value in values.items()}


def _string_items(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, str)]
    return []


class World:
    """One deterministic simulated realm holding every client in a scenario.

    Why this exists:
        Addon communication only means something between clients sharing a
        clock, a guild, a group, and a network; the world owns that shared
        state once, and pre-indexes the API index once, so each additional
        client is cheap and every client agrees on what exists.

    Args:
        index: The API index strictness resolves against; ``minimal_api_index``
            when ``None``.
        fs: Filesystem seam addon loading reads through; ``RealFileSystem``
            when ``None``.
        realm: Realm name used to build ``Name-Realm`` full names.
        guild_name: The one guild every ranked client belongs to.
        initial_server_time: POSIX server time at elapsed ``0.0``.
        rng_seed: Seed for the deterministic network randomness.
        loss_rate: Fraction of addon-message deliveries dropped, ``0.0``-``1.0``.
        duplicate_rate: Fraction of deliveries duplicated once.
        reorder_max_delay: When positive, each delivery is delayed by a
            uniform random amount up to this many virtual seconds.
        echo_guild_to_sender: Whether a guild addon message is also delivered
            back to its sender, as the real client does by default.

    Returns:
        Nothing; construct, then call ``client`` and ``advance``.

    Failure modes:
        None at construction for a well-formed ``ApiIndex``; a malformed index
        degrades to the core enums, no functions, and no events rather than
        raising, because strictness must fail closed, not crash the harness.
    """

    def __init__(
        self,
        index: ApiIndex | None = None,
        *,
        fs: FileSystem | None = None,
        realm: str = "Forever",
        guild_name: str = "Guildhall",
        initial_server_time: float = 1_800_000_000.0,
        rng_seed: int = 0,
        loss_rate: float = 0.0,
        duplicate_rate: float = 0.0,
        reorder_max_delay: float = 0.0,
        echo_guild_to_sender: bool = True,
    ) -> None:
        self.index: ApiIndex = index if index is not None else minimal_api_index()
        self.fs: FileSystem = fs if fs is not None else RealFileSystem()
        self._fs: FileSystem = self.fs
        self.realm = realm
        self.guild_name = guild_name
        self._initial_server_time = float(initial_server_time)
        self._elapsed = 0.0
        self._rng = random.Random(rng_seed)
        self.loss_rate = float(loss_rate)
        self.duplicate_rate = float(duplicate_rate)
        self.reorder_max_delay = float(reorder_max_delay)
        self.echo_guild_to_sender = echo_guild_to_sender
        self._clients: list[SimulatedClient] = []
        # [2026-11-11 T-007] One heap of (due, sequence, owner, call) drives both
        # C_Timer and network reordering; the sequence number breaks due-time
        # ties in scheduling order, so two timers for the same instant always
        # run in the order addon code created them.
        self._heap: list[tuple[float, int, SimulatedClient | None, _ScheduledCall]] = []
        self._sequence = 0
        self._disabled_events: set[str] = set()
        self._group_members: tuple[str, ...] = ()
        self._group_is_raid = False
        self._preindex()

    def _preindex(self) -> None:
        # [2026-11-11 T-007] Everything a client VM resolves is flattened here,
        # once, into plain sets and dicts; client creation then never walks the
        # 12,949-function index again, which is what keeps it under 5 ms.
        data = self.index.data
        functions = _kind_entries(data, "function")
        self.functions_by_name: Mapping[str, Mapping[str, Any]] = functions
        self._functions_by_name: Mapping[str, Mapping[str, Any]] = functions
        namespaces: set[str] = set(_ALWAYS_NAMESPACES)
        for name, entry in functions.items():
            if not (name.startswith("C_") or "." in name):
                continue
            declared = entry.get("namespace")
            namespace = declared if isinstance(declared, str) and declared else None
            if namespace is None:
                namespace = _namespace_of(name)
            if namespace:
                namespaces.add(namespace)
        self.c_namespaces: set[str] = namespaces
        self._c_namespaces: set[str] = namespaces
        self.valid_events: set[str] = set(_kind_entries(data, "event"))
        self._valid_events: set[str] = self.valid_events
        enums: dict[str, dict[str, Any]] = {
            short: dict(values) for short, values in _CORE_ENUMS.items()
        }
        for name, entry in _kind_entries(data, "enum").items():
            if name.startswith("Enum."):
                short_name = name[len("Enum.") :]
                merged = dict(enums.get(short_name, {}))
                merged.update(_entry_values(entry))
                enums[short_name] = merged
        self.enums_by_short_name: dict[str, dict[str, Any]] = enums
        self._enums_by_short_name: dict[str, dict[str, Any]] = enums
        constants: dict[str, dict[str, Any]] = {}
        for name, entry in _kind_entries(data, "table").items():
            if name.startswith("Constants."):
                constants[name[len("Constants.") :]] = _entry_values(entry)
        self.constants_by_short_name: dict[str, dict[str, Any]] = constants
        self._constants_by_short_name: dict[str, dict[str, Any]] = constants
        self.valid_templates: set[str] = set(_kind_entries(data, "template"))
        self._valid_templates: set[str] = self.valid_templates
        self.widget_methods_by_type: dict[str, set[str]] = self._flatten_widgets(data)
        self._widget_methods_by_type: dict[str, set[str]] = self.widget_methods_by_type

    def _flatten_widgets(self, data: Mapping[str, Any]) -> dict[str, set[str]]:
        widgets = _mapping_section(data, "widgets")
        inherits: dict[str, list[str]] = {}
        direct: dict[str, set[str]] = {}
        for widget_name, raw in widgets.items():
            name = str(widget_name)
            widget_data = raw if isinstance(raw, Mapping) else {}
            inherits[name] = _string_items(widget_data.get("inherits"))
            direct[name] = set(_string_items(widget_data.get("methods")))
        for entry_name, entry in _kind_entries(data, "widget-method").items():
            widget = entry.get("widget")
            if not isinstance(widget, str) or not widget:
                if ":" not in entry_name:
                    continue
                widget, method = entry_name.split(":", 1)
            else:
                method = entry_name.split(":", 1)[1] if ":" in entry_name else ""
            if widget and method:
                direct.setdefault(widget, set()).add(method)
                inherits.setdefault(widget, [])
        flattened: dict[str, set[str]] = {}

        def collect(name: str, visiting: set[str]) -> set[str]:
            if name in flattened:
                return flattened[name]
            if name in visiting:
                return set()
            visiting.add(name)
            methods = set(direct.get(name, set()))
            for parent in inherits.get(name, []):
                methods |= collect(parent, visiting)
            visiting.discard(name)
            flattened[name] = methods
            return methods

        for widget_name in list(direct) + list(inherits):
            collect(widget_name, set())
        return flattened

    @property
    def elapsed(self) -> float:
        """Return virtual seconds since the world was created.

        Why this exists:
            Every clock addon code can read (``GetTime``, timers, throttles)
            derives from this one value, so a scenario controls time by
            advancing it and by nothing else.

        Args:
            None.

        Returns:
            Elapsed virtual seconds; ``0.0`` until ``advance`` is called.

        Failure modes:
            None.
        """
        return self._elapsed

    @property
    def server_time(self) -> int:
        """Return the current simulated server POSIX time.

        Why this exists:
            ``GetServerTime`` and the Lua ``time`` global must agree with
            ``GetTime``; both are the initial server time plus elapsed.

        Args:
            None.

        Returns:
            ``int(initial_server_time + elapsed)``.

        Failure modes:
            None.
        """
        return int(self._initial_server_time + self._elapsed)

    @property
    def clients(self) -> tuple[SimulatedClient, ...]:
        """Return every client created in this world, in creation order.

        Why this exists:
            Scenarios and roster views iterate the same stable order the guild
            roster reports, without exposing the mutable backing list.

        Args:
            None.

        Returns:
            A tuple snapshot of the clients in creation order.

        Failure modes:
            None.
        """
        return tuple(self._clients)

    @property
    def group_members(self) -> tuple[str, ...]:
        """Return the current group as normalised ``Name-Realm`` strings.

        Why this exists:
            Group membership is world state the per-client group globals and
            message routing both read; one normalised view keeps them agreeing.

        Args:
            None.

        Returns:
            The members set by ``set_group``; empty when no group was set.

        Failure modes:
            None.
        """
        return self._group_members

    @property
    def group_is_raid(self) -> bool:
        """Return whether the current group is a raid.

        Why this exists:
            ``IsInRaid`` and raid message routing need the same answer the
            scenario set, separate from mere group membership.

        Args:
            None.

        Returns:
            ``True`` when ``set_group`` was last called with ``raid=True``.

        Failure modes:
            None.
        """
        return self._group_is_raid

    def client(
        self,
        name: str,
        *,
        rank: int | None = 2,
        rank_name: str | None = None,
        level: int = 80,
        class_file: str = "WARRIOR",
        online: bool = True,
    ) -> SimulatedClient:
        """Create one simulated client (one character) in this world.

        Why this exists:
            The single construction path for scenario characters, so each one
            gets a fresh sandboxed Lua VM on the world's shared clock and
            index while carrying its own identity and SavedVariables.

        Args:
            name: Short character name (``"Alice"``) or full ``"Name-Realm"``.
            rank: Guild rank index (0 is guild master), or ``None`` when the
                character is not in the guild.
            rank_name: Guild rank display name; a default is derived from
                ``rank`` when ``None``.
            level: Character level reported on the guild roster.
            class_file: Class file token such as ``"WARRIOR"``.
            online: Whether the character starts online.

        Returns:
            The new ``SimulatedClient``, appended to ``clients``.

        Failure modes:
            Raises ``luavm.LuaVMUnavailableError`` when the embedded Lua 5.1
            VM cannot be created.
        """
        created = SimulatedClient(
            self,
            name,
            rank=rank,
            rank_name=rank_name,
            level=level,
            class_file=class_file,
            online=online,
        )
        self._clients.append(created)
        return created

    def advance(self, seconds: float) -> None:
        """Move the virtual clock forward and run everything due in between.

        Why this exists:
            Scenarios express time passing in one call; timers, tickers, and
            reordered deliveries due inside the interval must fire at their
            own instants, including work those callbacks schedule.

        Args:
            seconds: How far to move the clock, in virtual seconds.

        Returns:
            ``None``; ``elapsed`` has increased by ``seconds``.

        Failure modes:
            Raises ``ValueError`` when ``seconds`` is negative; time never
            runs backwards, because throttle refills and timer ordering are
            only defined forward.
        """
        if seconds < 0:
            raise ValueError(f"advance seconds must be >= 0, got {seconds!r}")
        target = self._elapsed + float(seconds)
        while self._heap and self._heap[0][0] <= target:
            due_time, _seq, _owner, callback = heapq.heappop(self._heap)
            self._elapsed = due_time
            callback()
        self._elapsed = target

    def _schedule(
        self,
        delay: float,
        owner: SimulatedClient | None,
        callback: Callable[[], None],
    ) -> _ScheduledCall:
        return self._schedule_at(self._elapsed + max(0.0, float(delay)), owner, callback)

    def _schedule_at(
        self,
        due_time: float,
        owner: SimulatedClient | None,
        callback: Callable[[], None],
    ) -> _ScheduledCall:
        scheduled = _ScheduledCall(owner=owner, callback=callback)
        self._sequence += 1
        heapq.heappush(
            self._heap,
            (float(due_time), self._sequence, owner, scheduled),
        )
        return scheduled

    def _cancel_owner(self, owner: SimulatedClient) -> None:
        for _due, _seq, item_owner, scheduled in self._heap:
            if item_owner is owner:
                scheduled.cancelled = True

    def full_name_for(self, name: str) -> str:
        """Normalise a character name to ``Name-Realm`` form.

        Why this exists:
            Scenario inputs, whisper targets, and addon payloads mix short and
            full spellings; routing and roster membership compare one form.

        Args:
            name: A short name or an already-full ``Name-Realm`` string.

        Returns:
            ``name`` unchanged when it already contains ``-`` with a realm
            part, otherwise ``f"{name}-{realm}"``.

        Failure modes:
            None.
        """
        short, separator, name_realm = str(name).partition("-")
        if separator and short and name_realm:
            return str(name)
        return f"{name}-{self.realm}"

    def find_client(self, name: str) -> SimulatedClient | None:
        """Find a client by short or full name.

        Why this exists:
            Whisper routing and unit resolution both turn a name a scenario or
            addon supplied into the one client object that bears it.

        Args:
            name: Short name or ``Name-Realm`` full name.

        Returns:
            The first client with that full name, or ``None``.

        Failure modes:
            None; an unknown name gives ``None``.
        """
        wanted = self.full_name_for(name).lower()
        for candidate in self._clients:
            if candidate.full_name.lower() == wanted:
                return candidate
        return None

    def set_group(self, members: Sequence[str], *, raid: bool = False) -> None:
        """Set the shared party or raid membership.

        Why this exists:
            Group globals and group-channel addon messages are meaningless
            without one world-level membership list every client reads.

        Args:
            members: Member names, short or full; normalised to
                ``Name-Realm`` form.
            raid: Whether this group is a raid.

        Returns:
            ``None``; logged-in clients receive ``GROUP_ROSTER_UPDATE`` when
            that event is currently valid.

        Failure modes:
            None for ordinary inputs.
        """
        self._group_members = tuple(dict.fromkeys(self.full_name_for(member) for member in members))
        self._group_is_raid = bool(raid)
        if self.is_event_valid("GROUP_ROSTER_UPDATE"):
            for member_client in list(self._clients):
                if member_client.online and member_client.logged_in:
                    member_client._fire_internal("GROUP_ROSTER_UPDATE")

    def disable_event(self, event_name: str) -> None:
        """Make one event invalid for every client until re-enabled.

        Why this exists:
            Scenarios model client builds where an event does not exist;
            ``IsEventValid`` and event registration must then agree it is gone.

        Args:
            event_name: The event to disable.

        Returns:
            ``None``.

        Failure modes:
            None; disabling an unknown event is harmless.
        """
        self._disabled_events.add(str(event_name))

    def enable_event(self, event_name: str) -> None:
        """Undo a previous ``disable_event`` for one event.

        Why this exists:
            A scenario that removes an event to test a fallback path needs to
            restore the documented event set without rebuilding the world.

        Args:
            event_name: The event to re-enable.

        Returns:
            ``None``.

        Failure modes:
            None; enabling an event that was never disabled is harmless.
        """
        self._disabled_events.discard(str(event_name))

    def is_event_valid(self, event_name: object) -> bool:
        """Return whether an event currently exists in this world.

        Why this exists:
            The Lua bootstrap, ``C_EventUtils.IsEventValid``, and scenario
            ``fire`` calls must all answer from the index minus the events a
            scenario disabled.

        Args:
            event_name: The event name to test.

        Returns:
            ``True`` when the index knows the event and it is not disabled.

        Failure modes:
            None; a non-string name gives ``False``.
        """
        if not isinstance(event_name, str):
            return False
        return event_name in self.valid_events and event_name not in self._disabled_events

    def is_template_valid(self, template_name: object) -> bool:
        """Return whether a frame template exists in this world.

        Why this exists:
            ``CreateFrame`` in the Lua bootstrap asks the bridge before it
            builds a frame, so a template typo fails in simulation exactly
            where it fails in game.

        Args:
            template_name: The template name to test.

        Returns:
            ``True`` when the name is in the pre-indexed template set.

        Failure modes:
            None; a non-string name gives ``False``.
        """
        return isinstance(template_name, str) and template_name in self._valid_templates

    def is_valid_template(self, template_name: object) -> bool:
        """Return whether a frame template exists; alias of ``is_template_valid``.

        Why this exists:
            The bridge key is spelled ``is_valid_template`` while the world
            verb follows ``is_event_valid``; both spellings answer one question.

        Args:
            template_name: The template name to test.

        Returns:
            The same answer as ``is_template_valid``.

        Failure modes:
            None.
        """
        return self.is_template_valid(template_name)

    def add_template(self, name: str) -> None:
        """Allow one additional frame template name in this world.

        Why this exists:
            A test with a custom template needs to extend the closed template
            set deliberately, rather than the simulation accepting any string
            ``CreateFrame`` happens to be handed.

        Args:
            name: The template name to allow.

        Returns:
            ``None``.

        Failure modes:
            None.
        """
        self._valid_templates.add(str(name))

    def has_widget_method(self, widget_type: object, method: object) -> bool:
        """Return whether a widget type has a method, inheritance included.

        Why this exists:
            The Lua widget metatable asks the bridge before inventing a no-op
            stub, and the answer was flattened per type at world creation so
            the check stays a single set lookup per attribute access.

        Args:
            widget_type: Widget type name such as ``"Button"``.
            method: Method name such as ``"SetText"``.

        Returns:
            ``True`` when the flattened method set for the type holds it.

        Failure modes:
            None; unknown types and non-string inputs give ``False``.
        """
        if not isinstance(widget_type, str) or not isinstance(method, str):
            return False
        return method in self.widget_methods_by_type.get(widget_type, set())

    def set_network(
        self,
        *,
        loss_rate: float | None = None,
        duplicate_rate: float | None = None,
        reorder_max_delay: float | None = None,
    ) -> None:
        """Change addon-message network impairment mid-scenario.

        Why this exists:
            A synchronisation addon must survive a network that gets worse
            after it loaded; scenarios tune loss, duplication, and reordering
            without rebuilding the world and losing client state.

        Args:
            loss_rate: New drop fraction, or ``None`` to keep the current one.
            duplicate_rate: New duplication fraction, or ``None`` to keep it.
            reorder_max_delay: New maximum delivery delay in virtual seconds,
                or ``None`` to keep it.

        Returns:
            ``None``; only the named settings change.

        Failure modes:
            None for ordinary inputs.
        """
        if loss_rate is not None:
            self.loss_rate = float(loss_rate)
        if duplicate_rate is not None:
            self.duplicate_rate = float(duplicate_rate)
        if reorder_max_delay is not None:
            self.reorder_max_delay = float(reorder_max_delay)

    def enum_value(self, short_name: str, key: str, fallback: int) -> int:
        """Return one enum value, with the core 1.60.1 value as fallback.

        Why this exists:
            Numeric API results must come from the index the scenario supplied
            when it carries the enum, and from the verified core table when a
            custom index omitted it; one lookup owns that precedence.

        Args:
            short_name: Enum name without the ``Enum.`` prefix.
            key: Member name inside the enum.
            fallback: Value to use when neither source gives a number.

        Returns:
            The member value as an ``int``.

        Failure modes:
            None; a non-numeric stored value falls back.
        """
        value = self.enums_by_short_name.get(short_name, {}).get(key)
        if isinstance(value, bool):
            return fallback
        if isinstance(value, (int, float)):
            return int(value)
        return fallback

    def guild_members(self) -> tuple[SimulatedClient, ...]:
        """Return the guild roster as clients, in creation order.

        Why this exists:
            Every guild view (roster globals, counts, guild message routing)
            derives from the same membership rule: a client whose rank is not
            ``None`` is in the world's one guild.

        Args:
            None.

        Returns:
            Ranked clients in creation order.

        Failure modes:
            None.
        """
        return tuple(client for client in self._clients if client.rank is not None)


def _default_rank_name(rank: int | None) -> str | None:
    if rank is None:
        return None
    if rank == 0:
        return "Guild Master"
    if rank == 1:
        return "Officer"
    if rank == 2:
        return "Member"
    return f"Rank {rank}"


def _folder_name(path: str) -> str:
    cleaned = path.replace("\\", "/").rstrip("/")
    return cleaned.rsplit("/", 1)[-1] if cleaned else ""


def _is_toc_candidate(file_name: str, folder: str) -> bool:
    lowered = file_name.lower()
    if not lowered.endswith(".toc"):
        return False
    stem = lowered[: -len(".toc")]
    base = folder.lower()
    return stem == base or stem.startswith(base + "_") or stem.startswith(base + "-")


class SimulatedClient:
    """One simulated WoW client running real addon Lua in a sandboxed VM.

    Why this exists:
        This is the unit a scenario speaks to: it loads addons, logs in,
        fires events, sends addon messages, and persists SavedVariables, all
        against the strict API world its ``World`` pre-indexed.

    Args:
        world: The owning ``World`` (clock, guild, network, index, filesystem).
        name: Short character name or full ``Name-Realm`` name.
        rank: Guild rank index, or ``None`` when not in the guild.
        rank_name: Guild rank display name; derived from ``rank`` when ``None``.
        level: Character level reported on the guild roster.
        class_file: Class file token such as ``"WARRIOR"``.
        online: Whether the character starts online.

    Returns:
        Nothing; construct through ``World.client``.

    Failure modes:
        Raises ``luavm.LuaVMUnavailableError`` when the embedded Lua 5.1 VM
        cannot be created.
    """

    def __init__(
        self,
        world: World,
        name: str,
        *,
        rank: int | None = 2,
        rank_name: str | None = None,
        level: int = 80,
        class_file: str = "WARRIOR",
        online: bool = True,
    ) -> None:
        self._world = world
        self._fs: FileSystem = world._fs
        raw_name = str(name)
        short, separator, own_realm = raw_name.partition("-")
        if separator and short and own_realm:
            self.name = short
            self.realm = own_realm
        else:
            self.name = raw_name
            self.realm = world.realm
        self.full_name = f"{self.name}-{self.realm}"
        self.rank = rank
        self.rank_name = rank_name if rank_name is not None else _default_rank_name(rank)
        self.level = int(level)
        self.class_file = str(class_file)
        self.online = bool(online)
        self.errors: list[LuaErrorRecord] = []
        self.account_saved_variables: dict[str, Any] = {}
        self.character_saved_variables: dict[str, Any] = {}
        self.registered_prefixes: set[str] = set()
        self.honorable_kills = 0
        self._logged_in = False
        self._loaded_addons: list[_LoadedAddon] = []
        self._active_restrictions: set[int] = set()
        self._client_bucket = _TokenBucket(last_refill=world.elapsed)
        self._prefix_buckets: dict[str, _TokenBucket] = {}
        self._in_instance = False
        self._instance_type = "none"
        self._instance_name = ""
        self._difficulty_id = 0
        self._instance_max_players = 0
        self._instance_id = 0
        self._runtime: Any = None
        self._controller: Any = None
        self._make_timer_handle: Any = None
        self._stub_cache: dict[str, Callable[..., Any]] = {}
        self._init_vm()

    @property
    def world(self) -> World:
        """Return the world this client belongs to.

        Why this exists:
            Scenario helpers holding only a client still need the shared clock
            and network the client was created on.

        Args:
            None.

        Returns:
            The owning ``World``.

        Failure modes:
            None.
        """
        return self._world

    @property
    def runtime(self) -> Any:
        """Return this client's Lua 5.1 runtime.

        Why this exists:
            Advanced scenarios inspect Lua globals through the same VM addon
            code ran in, instead of a copy whose state could disagree.

        Args:
            None.

        Returns:
            The ``lupa.lua51`` runtime created for this client.

        Failure modes:
            None.
        """
        return self._runtime

    @property
    def controller(self) -> Any:
        """Return the Lua bootstrap controller for this client.

        Why this exists:
            The controller is the handle that fires events and reads raw
            globals past strictness; exposing it keeps diagnostics on the
            same seam the runtime itself uses.

        Args:
            None.

        Returns:
            The controller table returned by ``install_bootstrap``.

        Failure modes:
            None.
        """
        return self._controller

    @property
    def logged_in(self) -> bool:
        """Return whether this client has completed login.

        Why this exists:
            World broadcasts and PvP notifications only reach logged-in
            clients; one predicate keeps that rule in one place.

        Args:
            None.

        Returns:
            ``True`` after ``login`` and before ``logout``.

        Failure modes:
            None.
        """
        return self._logged_in

    @property
    def loaded_addons(self) -> tuple[str, ...]:
        """Return the names of addons loaded into this client, in load order.

        Why this exists:
            Reload must replay exactly this list, and scenarios asserting a
            load happened should not have to reach into private state.

        Args:
            None.

        Returns:
            Addon folder names in load order.

        Failure modes:
            None.
        """
        return tuple(addon.name for addon in self._loaded_addons)

    def _record_error(self, message: Any, stack: Any = "") -> None:
        self.errors.append(
            LuaErrorRecord(
                message=str(message),
                stack="" if stack is None else str(stack),
                time=float(self._world.elapsed),
            )
        )

    def _default_for(self, field_info: Mapping[str, Any]) -> Any:
        if field_info.get("nilable") is True:
            return None
        type_name = field_info.get("type")
        if not isinstance(type_name, str):
            return None
        if type_name == "bool":
            return False
        if type_name in ("number", "luaIndex", "time_t", "fileID"):
            return 0
        if type_name in ("string", "cstring", "stringView"):
            return ""
        if type_name == "table":
            return self._runtime.table()
        short = type_name[len("Enum.") :] if type_name.startswith("Enum.") else type_name
        if short in self._world.enums_by_short_name:
            return 0
        return None

    def _make_stub(self, full_name: str, entry: Mapping[str, Any]) -> Callable[..., Any]:
        cached = self._stub_cache.get(full_name)
        if cached is not None:
            return cached
        raw_returns = entry.get("returns")
        returns: list[Mapping[str, Any]] = (
            [item for item in raw_returns if isinstance(item, Mapping)]
            if isinstance(raw_returns, (list, tuple))
            else []
        )

        def stub(*_args: Any) -> Any:
            # [2026-11-11 T-034] A documented secret return is opaque only while
            # a restriction regime is active. Unrestricted calls keep the typed default.
            secret = entry.get("secret")
            if (
                isinstance(secret, Mapping)
                and secret.get("returns") is True
                and self._active_restrictions
                and self._controller is not None
            ):
                return self._controller.make_secret()
            # [2026-11-11 T-007] Defaults are built per call, not once, so a
            # table default is a fresh Lua table each time; addon code that
            # writes into a returned table must not poison the next caller.
            if not returns:
                return None
            values = tuple(self._default_for(item) for item in returns)
            if len(values) == 1:
                return values[0]
            return values

        self._stub_cache[full_name] = stub
        return stub

    def _resolve_c_member(self, namespace: Any, key: Any) -> Any:
        if not isinstance(namespace, str) or not isinstance(key, str):
            return None
        full_name = f"{namespace}.{key}"
        entry = self._world.functions_by_name.get(full_name)
        if entry is None:
            return None
        return self._make_stub(full_name, entry)

    def _resolve_global(self, key: Any) -> tuple[bool, Any]:
        if not isinstance(key, str) or "." in key:
            return (False, None)
        entry = self._world.functions_by_name.get(key)
        if entry is None:
            return (False, None)
        return (True, self._make_stub(key, entry))

    def _resolve_enum(self, key: Any) -> Any:
        if not isinstance(key, str):
            return None
        values = self._world.enums_by_short_name.get(key)
        if values is None:
            return None
        return import_saved_value(self._runtime, dict(values))

    def _resolve_constants(self, key: Any) -> Any:
        if not isinstance(key, str):
            return None
        values = self._world.constants_by_short_name.get(key)
        if values is None:
            return None
        return import_saved_value(self._runtime, dict(values))

    def _init_vm(self) -> None:
        # [2026-11-11 T-007] The VM is rebuilt whole on reload: strictness, the
        # frame registry, and every Lua global live inside it, so nothing from
        # the previous session can leak into the reloaded one except the
        # SavedVariables Python flushed first.
        runtime = luavm.new_runtime(sandbox=True)
        self._runtime = runtime
        self._stub_cache = {}
        bridge = runtime.table()
        bridge["get_time"] = lambda: self._world.elapsed
        bridge["get_server_time"] = lambda: self._world.server_time
        bridge["is_valid_event"] = self._world.is_event_valid
        bridge["is_valid_template"] = self._world.is_template_valid
        bridge["has_widget_method"] = self._world.has_widget_method
        bridge["record_error"] = self._record_error
        bridge["resolve_c_member"] = self._resolve_c_member
        bridge["resolve_global"] = self._resolve_global
        bridge["resolve_enum"] = self._resolve_enum
        bridge["resolve_constants"] = self._resolve_constants
        controller = install_bootstrap(runtime, bridge)
        self._controller = controller
        # [2026-11-11 T-007] The timer-handle factory is Lua so handle methods
        # are plain Lua functions: `handle:Cancel()` passes the handle as the
        # first argument, exactly as colon syntax in addon code expects, and
        # the Python callbacks underneath never see that implicit argument.
        self._make_timer_handle = runtime.execute(
            "return function(cancel_cb, is_cancelled_cb)\n"
            "    return {\n"
            "        Cancel = function(self) cancel_cb() end,\n"
            "        IsCancelled = function(self) return is_cancelled_cb() end,\n"
            "    }\n"
            "end"
        )
        self._install_globals(controller)
        self._install_namespaces(controller, runtime)
        controller.arm_strict_globals()

    def _install_globals(self, controller: Any) -> None:
        globals_to_install: dict[str, Callable[..., Any]] = {
            "InCombatLockdown": self._global_in_combat_lockdown,
            "IsLoggedIn": self._global_is_logged_in,
            "IsInGuild": self._global_is_in_guild,
            "GetRealmName": self._global_get_realm_name,
            "UnitName": self._global_unit_name,
            "UnitFullName": self._global_unit_full_name,
            "UnitGUID": self._global_unit_guid,
            "UnitIsUnit": self._global_unit_is_unit,
            "UnitIsInMyGuild": self._global_unit_is_in_my_guild,
            "GetGuildInfo": self._global_get_guild_info,
            "GetNumGuildMembers": self._global_get_num_guild_members,
            "GetGuildRosterInfo": self._global_get_guild_roster_info,
            "IsInGroup": self._global_is_in_group,
            "IsInRaid": self._global_is_in_raid,
            "GetNumGroupMembers": self._global_get_num_group_members,
            "IsInInstance": self._global_is_in_instance,
            "GetInstanceInfo": self._global_get_instance_info,
            "GetPVPLifetimeStats": self._global_get_pvp_lifetime_stats,
            "GetBuildInfo": self._global_get_build_info,
        }
        for global_name, function in globals_to_install.items():
            controller.set_global_function(global_name, function)

    def _install_namespaces(self, controller: Any, runtime: Any) -> None:
        # [2026-11-11 T-007] Namespace functions are dot functions in WoW, so
        # each Python callback below receives exactly the arguments addon code
        # wrote inside the parentheses; there is no implicit self to discard.
        real_methods: dict[str, dict[str, Callable[..., Any]]] = {
            "C_ChatInfo": {
                "SendAddonMessage": self._chat_send_addon_message,
                "RegisterAddonMessagePrefix": self._chat_register_prefix,
                "IsAddonMessagePrefixRegistered": self._chat_is_prefix_registered,
                "GetRegisteredAddonMessagePrefixes": self._chat_get_prefixes,
            },
            "C_RestrictedActions": {
                "IsAddOnRestrictionActive": self._restriction_is_active,
                "GetAddOnRestrictionState": self._restriction_state,
            },
            "C_EventUtils": {
                "IsEventValid": self._event_utils_is_valid,
            },
            "C_Timer": {
                "After": self._timer_after,
                "NewTimer": self._timer_new_timer,
                "NewTicker": self._timer_new_ticker,
            },
            "C_UI": {
                "Reload": self._ui_reload,
            },
            "C_GuildInfo": {
                "GuildRoster": self._guild_info_roster,
            },
        }
        for namespace in sorted(self._world.c_namespaces):
            methods_table = runtime.table()
            for method_name, function in real_methods.get(namespace, {}).items():
                methods_table[method_name] = function
            controller.install_namespace(namespace, methods_table)

    def _resolve_unit(self, unit: Any) -> SimulatedClient | None:
        if not isinstance(unit, str):
            return None
        token = unit.strip()
        if token.lower() in ("player", "self"):
            return self
        found = self._world.find_client(token)
        if found is not None:
            return found
        lowered = token.lower()
        # [2026-11-11 T-007] Group unit tokens resolve against the world's one
        # group list, so UnitName("party1") and message routing can never
        # disagree about who the first group member is.
        for prefix in ("party", "raid"):
            if lowered.startswith(prefix) and lowered[len(prefix) :].isdigit():
                position = int(lowered[len(prefix) :])
                members = self._world.group_members
                if 1 <= position <= len(members):
                    return self._world.find_client(members[position - 1])
                return None
        return None

    def _in_group(self) -> bool:
        return self.full_name in self._world.group_members

    def _global_in_combat_lockdown(self, *_args: Any) -> bool:
        combat = self._world.enum_value("AddOnRestrictionType", "Combat", 0)
        return combat in self._active_restrictions

    def _global_is_logged_in(self, *_args: Any) -> bool:
        return self._logged_in

    def _global_is_in_guild(self, *_args: Any) -> bool:
        return self.rank is not None

    def _global_get_realm_name(self, *_args: Any) -> str:
        return self.realm

    def _global_unit_name(self, unit: Any = None, *_args: Any) -> Any:
        resolved = self._resolve_unit(unit)
        if resolved is None:
            return None
        return (resolved.name, resolved.realm)

    def _global_unit_full_name(self, unit: Any = None, *_args: Any) -> Any:
        resolved = self._resolve_unit(unit)
        if resolved is None:
            return None
        return (resolved.name, resolved.realm)

    def _global_unit_guid(self, unit: Any = None, *_args: Any) -> Any:
        resolved = self._resolve_unit(unit)
        if resolved is None:
            return None
        # [2026-11-11 T-007] GUIDs are minted from creation order, never from a
        # hash: they stay identical on every run of the same scenario, which is
        # what a test comparing GUID strings across a reload relies on.
        serial = list(self._world.clients).index(resolved) + 1
        return f"Player-1-{serial:08X}"

    def _global_unit_is_unit(self, first: Any = None, second: Any = None) -> bool:
        left = self._resolve_unit(first)
        right = self._resolve_unit(second)
        return left is not None and left is right

    def _global_unit_is_in_my_guild(self, unit: Any = None, *_args: Any) -> bool:
        resolved = self._resolve_unit(unit)
        return self.rank is not None and resolved is not None and resolved.rank is not None

    def _global_get_guild_info(self, unit: Any = None, *_args: Any) -> Any:
        resolved = self._resolve_unit(unit) if unit is not None else self
        if resolved is None or resolved.rank is None:
            return None
        return (
            self._world.guild_name,
            resolved.rank_name,
            resolved.rank,
            resolved.realm,
        )

    def _global_get_num_guild_members(self, *_args: Any) -> tuple[int, int, int]:
        members = self._world.guild_members()
        online_count = sum(1 for member in members if member.online)
        return (len(members), online_count, online_count)

    def _global_get_guild_roster_info(self, index: Any = None, *_args: Any) -> Any:
        try:
            position = int(index)
        except (TypeError, ValueError):
            return None
        members = self._world.guild_members()
        if position < 1 or position > len(members):
            return None
        member = members[position - 1]
        # [2026-11-11 T-007] The tuple mirrors the documented roster layout in
        # full, including the tail fields addons read positionally; returning a
        # short tuple would shift nothing here but break every multi-assign.
        return (
            member.full_name,
            member.rank_name,
            member.rank,
            member.level,
            member.class_file,
            "",
            "",
            "",
            member.online,
            0,
            member.class_file,
            0,
            0,
            False,
            False,
            0,
            self._global_unit_guid(member.full_name),
        )

    def _global_is_in_group(self, *_args: Any) -> bool:
        return self._in_group()

    def _global_is_in_raid(self, *_args: Any) -> bool:
        return self._in_group() and self._world.group_is_raid

    def _global_get_num_group_members(self, *_args: Any) -> int:
        if not self._in_group():
            return 0
        return len(self._world.group_members)

    def _global_is_in_instance(self, *_args: Any) -> tuple[bool, str]:
        return (self._in_instance, self._instance_type)

    def _global_get_instance_info(self, *_args: Any) -> tuple[Any, ...]:
        return (
            self._instance_name,
            self._instance_type,
            self._difficulty_id,
            "",
            self._instance_max_players,
            0,
            False,
            self._instance_id,
            self._instance_max_players,
            None,
        )

    def _global_get_pvp_lifetime_stats(self, *_args: Any) -> tuple[int, int]:
        return (self.honorable_kills, 0)

    def _global_get_build_info(self, *_args: Any) -> tuple[str, str, str, int]:
        build = str(self._world.index.data.get("build", "1.60.1.70888"))
        parts = build.split(".")
        version = ".".join(parts[:3]) if len(parts) >= 3 else build
        build_number = parts[3] if len(parts) >= 4 else ""
        interface = 16001
        if len(parts) >= 3 and all(part.isdigit() for part in parts[:3]):
            interface = int(parts[0]) * 10000 + int(parts[1]) * 100 + int(parts[2])
        return (version, build_number, "Nov 11 2026", interface)

    def _restriction_id_for(self, regime: Any) -> int | None:
        if isinstance(regime, bool):
            return None
        if isinstance(regime, int):
            candidate = regime
        elif isinstance(regime, float) and regime.is_integer():
            candidate = int(regime)
        elif isinstance(regime, str):
            names: dict[str, int] = {}
            enum_table = self._world.enums_by_short_name.get("AddOnRestrictionType", {})
            for key, value in enum_table.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    names[str(key).lower()] = int(value)
            for key, value in RESTRICTION_TYPE.items():
                names.setdefault(key.lower(), value)
            resolved = names.get(regime.strip().lower())
            return resolved
        else:
            return None
        return candidate if candidate in RESTRICTION_TYPE.values() else None

    def _restriction_is_active(self, regime: Any = None, *_args: Any) -> bool:
        if regime is None:
            return bool(self._active_restrictions)
        resolved = self._restriction_id_for(regime)
        return resolved is not None and resolved in self._active_restrictions

    def _restriction_state(self, regime: Any = None, *_args: Any) -> int:
        active_value = self._world.enum_value("AddOnRestrictionState", "Active", 2)
        inactive_value = self._world.enum_value("AddOnRestrictionState", "Inactive", 0)
        return active_value if self._restriction_is_active(regime) else inactive_value

    def _event_utils_is_valid(self, event_name: Any = None, *_args: Any) -> bool:
        return isinstance(event_name, str) and self._world.is_event_valid(event_name)

    def _ui_reload(self, *_args: Any) -> None:
        self.reload()

    def _guild_info_roster(self, *_args: Any) -> None:
        # [2026-11-11 T-007] The real request is asynchronous, but the headless
        # roster is already authoritative in Python, so the update event fires
        # immediately on the requesting client and nowhere else.
        if self._world.is_event_valid("GUILD_ROSTER_UPDATE"):
            self._fire_internal("GUILD_ROSTER_UPDATE", False)

    def _coerce_delay(self, value: Any) -> float:
        if isinstance(value, bool) or value is None:
            return 0.0
        number = float(value)
        return max(0.0, number)

    def _fire_timer(self, state: _TimerHandleState, callback: Any, handle: Any) -> None:
        if state.cancelled:
            return
        state.fired += 1
        self._controller.call_protected(callback, handle)

    def _new_timer_handle(self, state: _TimerHandleState) -> Any:
        def cancel() -> None:
            state.cancelled = True
            if state.scheduled is not None:
                state.scheduled.cancelled = True

        def is_cancelled() -> bool:
            return state.cancelled

        return self._make_timer_handle(cancel, is_cancelled)

    def _timer_after(self, seconds: Any = None, callback: Any = None) -> None:
        delay = self._coerce_delay(seconds)
        controller = self._controller

        def run() -> None:
            controller.call_protected(callback)

        self._world._schedule(delay, self, run)

    def _timer_new_timer(self, seconds: Any = None, callback: Any = None) -> Any:
        delay = self._coerce_delay(seconds)
        state = _TimerHandleState()
        handle = self._new_timer_handle(state)

        def run() -> None:
            self._fire_timer(state, callback, handle)
            state.cancelled = True

        state.scheduled = self._world._schedule(delay, self, run)
        return handle

    def _timer_new_ticker(
        self, seconds: Any = None, callback: Any = None, iterations: Any = None
    ) -> Any:
        interval = self._coerce_delay(seconds)
        if interval <= 0.0:
            # [2026-11-11 T-007] A zero-length ticker would reschedule itself at
            # the same virtual instant forever inside one advance call; raising
            # here matches the client refusing a non-positive ticker interval.
            raise ValueError("C_Timer.NewTicker requires a positive interval")
        max_iterations: int | None = None
        if iterations is not None:
            max_iterations = int(iterations)
        state = _TimerHandleState()
        handle = self._new_timer_handle(state)

        def tick() -> None:
            if state.is_cancelled():
                return
            self._fire_timer(state, callback, handle)
            if state.is_cancelled():
                return
            if max_iterations is not None and state.fired >= max_iterations:
                state.cancelled = True
                return
            state.scheduled = self._world._schedule(interval, self, tick)

        state.scheduled = self._world._schedule(interval, self, tick)
        return handle

    def _send_result(self, key: str) -> int:
        return self._world.enum_value("SendAddonMessageResult", key, SEND_RESULT[key])

    def _prefix_result(self, key: str) -> int:
        short = "RegisterAddonMessagePrefixResult"
        return self._world.enum_value(short, key, PREFIX_RESULT[key])

    def _refill_bucket(self, bucket: _TokenBucket) -> None:
        now = self._world.elapsed
        gained = (now - bucket.last_refill) * _BUCKET_REFILL_PER_SECOND
        if gained > 0.0:
            bucket.tokens = min(_BUCKET_CAPACITY, bucket.tokens + gained)
        bucket.last_refill = now

    def _prefix_bucket(self, prefix: str) -> _TokenBucket:
        bucket = self._prefix_buckets.get(prefix)
        if bucket is None:
            bucket = _TokenBucket(last_refill=self._world.elapsed)
            self._prefix_buckets[prefix] = bucket
        return bucket

    def _chat_register_prefix(self, prefix: Any = None, *_args: Any) -> int:
        if not isinstance(prefix, str):
            return self._prefix_result("InvalidPrefix")
        if not 1 <= len(prefix.encode("utf-8")) <= 16:
            return self._prefix_result("InvalidPrefix")
        if prefix in self.registered_prefixes:
            return self._prefix_result("DuplicatePrefix")
        if len(self.registered_prefixes) >= _MAX_REGISTERED_PREFIXES:
            return self._prefix_result("MaxPrefixes")
        self.registered_prefixes.add(prefix)
        return self._prefix_result("Success")

    def _chat_is_prefix_registered(self, prefix: Any = None, *_args: Any) -> bool:
        return isinstance(prefix, str) and prefix in self.registered_prefixes

    def _chat_get_prefixes(self, *_args: Any) -> Any:
        return import_saved_value(self._runtime, sorted(self.registered_prefixes))

    def _recipients_for(
        self, channel: str, target_full: str | None
    ) -> tuple[list[SimulatedClient] | None, int]:
        world = self._world
        if channel == "GUILD":
            if self.rank is None:
                return (None, self._send_result("NotInGuild"))
            recipients = [
                member
                for member in world.guild_members()
                if member is not self or world.echo_guild_to_sender
            ]
            return (recipients, self._send_result("Success"))
        if channel == "WHISPER":
            if target_full is None:
                return (None, self._send_result("TargetRequired"))
            target_client = world.find_client(target_full)
            if target_client is None or not target_client.online:
                return (None, self._send_result("TargetOffline"))
            return ([target_client], self._send_result("Success"))
        if channel in ("PARTY", "RAID", "INSTANCE_CHAT"):
            if channel == "RAID" and not (self._in_group() and world.group_is_raid):
                return (None, self._send_result("NotInGroup"))
            if channel == "PARTY" and not self._in_group():
                return (None, self._send_result("NotInGroup"))
            if channel == "INSTANCE_CHAT" and not (self._in_group() or self._in_instance):
                return (None, self._send_result("NotInGroup"))
            recipients = []
            if world.group_members:
                for member_name in world.group_members:
                    member = world.find_client(member_name)
                    if member is not None:
                        recipients.append(member)
            else:
                recipients = [candidate for candidate in world.clients if candidate._in_instance]
            return (recipients, self._send_result("Success"))
        if channel == "CHANNEL":
            return (None, self._send_result("InvalidChannel"))
        return (None, self._send_result("InvalidChatType"))

    def _deliver_addon_message(
        self,
        recipient: SimulatedClient,
        prefix: str,
        message: str,
        channel: str,
        target_argument: str,
    ) -> None:
        world = self._world
        sender_full = self.full_name

        def deliver_once() -> None:
            # [2026-11-11 T-007] Registration and online state are re-checked at
            # delivery time, not send time: a reordered copy that lands after
            # the recipient logged out (or reloaded and dropped the prefix)
            # must vanish exactly as it would on the wire.
            if not recipient.online:
                return
            if prefix not in recipient.registered_prefixes:
                return
            if not world.is_event_valid("CHAT_MSG_ADDON"):
                return
            recipient._fire_internal(
                "CHAT_MSG_ADDON",
                prefix,
                message,
                channel,
                sender_full,
                target_argument,
                0,
                0,
                "",
                0,
            )

        # [2026-11-11 T-007] Loss, duplication, and delay are drawn per
        # recipient copy from the world's one seeded generator, so a scenario
        # seed reproduces the same wire behaviour for every client.
        if world.loss_rate > 0.0 and world._rng.random() < world.loss_rate:
            return
        copies = 1
        if world.duplicate_rate > 0.0 and world._rng.random() < world.duplicate_rate:
            copies = 2
        for _copy in range(copies):
            if world.reorder_max_delay > 0.0:
                delay = world._rng.uniform(0.0, world.reorder_max_delay)
                if delay > 0.0:
                    world._schedule(delay, recipient, deliver_once)
                    continue
            deliver_once()

    def _chat_send_addon_message(
        self,
        prefix: Any = None,
        message: Any = None,
        chat_type: Any = None,
        target: Any = None,
    ) -> int:
        # [2026-11-11 T-007] Byte counts, not character counts, gate prefix and
        # message: the wire format is bytes, so a 9-character prefix of two-byte
        # letters is already too long even though it looks short in Lua.
        if not isinstance(prefix, str) or not 1 <= len(prefix.encode("utf-8")) <= 16:
            return self._send_result("InvalidPrefix")
        if not isinstance(message, str) or len(message.encode("utf-8")) > 255:
            return self._send_result("InvalidMessage")
        if self._active_restrictions:
            return self._send_result("AddOnMessageLockdown")
        channel = str(chat_type).strip().upper() if isinstance(chat_type, str) else ""
        target_full: str | None = None
        if isinstance(target, str) and target.strip():
            target_full = self._world.full_name_for(target.strip())
        elif isinstance(target, (int, float)) and not isinstance(target, bool):
            target_client = self._resolve_unit(str(target))
            target_full = target_client.full_name if target_client is not None else None
        recipients, failure = self._recipients_for(channel, target_full)
        if recipients is None:
            return failure
        client_bucket = self._client_bucket
        prefix_bucket = self._prefix_bucket(prefix)
        self._refill_bucket(client_bucket)
        self._refill_bucket(prefix_bucket)
        if client_bucket.tokens < 1.0 or prefix_bucket.tokens < 1.0:
            return self._send_result("AddonMessageThrottle")
        client_bucket.tokens -= 1.0
        prefix_bucket.tokens -= 1.0
        target_argument = target_full if target_full is not None else self.full_name
        for recipient in recipients:
            self._deliver_addon_message(recipient, prefix, message, channel, target_argument)
        return self._send_result("Success")

    def _fire_internal(self, event: str, *args: Any) -> None:
        self._controller.fire_event(event, *args)

    def _find_toc(self, addon_dir: str) -> tuple[str, tocfile.TocFile]:
        folder = _folder_name(addon_dir)
        try:
            entries = self._fs.list_dir(addon_dir)
        except OSError as exc:
            raise HeadlessError(
                f"cannot load addon from {addon_dir!r}: folder cannot be listed: {exc}"
            ) from exc
        candidates = sorted(
            name
            for name in entries
            if self._fs.is_file(self._fs.join(addon_dir, name)) and _is_toc_candidate(name, folder)
        )
        if not candidates:
            raise HeadlessError(
                f"cannot load addon from {addon_dir!r}: no TOC named after its folder {folder!r}"
            )
        parsed: list[tuple[str, tocfile.TocFile]] = []
        for candidate in candidates:
            try:
                text = self._fs.read_text(self._fs.join(addon_dir, candidate))
            except OSError as exc:
                raise HeadlessError(
                    f"cannot load addon from {addon_dir!r}: TOC {candidate!r} cannot be read: {exc}"
                ) from exc
            parsed.append((candidate, tocfile.parse_toc(text)))
        # [2026-11-11 T-007] The TOC choice mirrors env detection: an Interface
        # match for this client wins, then the base folder TOC, then the first
        # candidate; loading and detection must never read different addons.
        client_interface = 16001
        for candidate_name, candidate_toc in parsed:
            if client_interface in candidate_toc.interface:
                return (candidate_name, candidate_toc)
        base_name = f"{folder}.toc".lower()
        for candidate_name, candidate_toc in parsed:
            if candidate_name.lower() == base_name:
                return (candidate_name, candidate_toc)
        return parsed[0]

    def _restore_saved_variable(self, var: str, store: dict[str, Any]) -> None:
        if var in store:
            value = import_saved_value(self._runtime, store[var])
            self._controller.raw_set_global(var, value)

    def load_addon(self, path: str | os.PathLike[str], *, login: bool = True) -> str:
        """Load one addon folder into this client the way the game client does.

        Why this exists:
            The honest test of an addon is its real TOC order, real saved
            variables, and the real ``...`` arguments; this is the one path
            that replays all three into the Lua VM.

        Args:
            path: The addon folder, as the world's filesystem understands it.
            login: When true (the default) and the client is not yet logged
                in, complete login after the addon loads.

        Returns:
            The addon name, which is its folder name.

        Failure modes:
            Raises ``HeadlessError`` when the folder cannot be listed, has no
            TOC named after it, has an unreadable TOC, or lists a Lua file
            that cannot be read. A Lua compile or runtime failure inside an
            addon file is recorded in ``errors`` and loading continues with
            the next file, as the client's error handler allows it to.
        """
        addon_dir = os.fsdecode(path)
        addon_name = _folder_name(addon_dir)
        _toc_name, loaded_toc = self._find_toc(addon_dir)
        allowed_globals: list[str] = list(loaded_toc.all_saved_variables)
        if loaded_toc.headers.get("X-Forge-Bridge") == "1":
            inbox = f"{addon_name}_Inbox"
            if inbox not in allowed_globals:
                allowed_globals.append(inbox)
        for var in allowed_globals:
            self._controller.allow_nil_global(var)
        for saved_var in loaded_toc.saved_variables:
            self._restore_saved_variable(saved_var, self.account_saved_variables)
        for saved_var in loaded_toc.saved_variables_per_character:
            self._restore_saved_variable(saved_var, self.character_saved_variables)
        declared = set(loaded_toc.all_saved_variables)
        for var in allowed_globals:
            if var not in declared:
                if var in self.account_saved_variables:
                    self._restore_saved_variable(var, self.account_saved_variables)
                elif var in self.character_saved_variables:
                    self._restore_saved_variable(var, self.character_saved_variables)
        record = _LoadedAddon(name=addon_name, path=addon_dir, toc=loaded_toc)
        for position, existing in enumerate(self._loaded_addons):
            if existing.name == addon_name:
                self._loaded_addons[position] = record
                break
        else:
            self._loaded_addons.append(record)
        # [2026-11-11 T-007] One fresh namespace table per load, shared by every
        # file of this addon and by no other addon: that sharing boundary is
        # exactly the contract `local addonName, ns = ...` relies on.
        namespace_table = self._runtime.table()
        for relative_file in loaded_toc.files:
            if not relative_file.lower().endswith(".lua"):
                continue
            file_path = self._fs.join(addon_dir, *relative_file.split("/"))
            try:
                source = self._fs.read_text(file_path)
            except OSError as exc:
                raise HeadlessError(
                    f"cannot load addon {addon_name!r}: listed file "
                    f"{relative_file!r} cannot be read: {exc}"
                ) from exc
            chunk_name = f"{addon_name}/{relative_file}"
            self._controller.run_addon_chunk(
                source,
                chunk_name,
                addon_name,
                namespace_table,
            )
        if self._world.is_event_valid("ADDON_LOADED"):
            self._fire_internal("ADDON_LOADED", addon_name, False)
        if login and not self._logged_in:
            self.login(is_reload=False)
        return addon_name

    def login(self, *, is_reload: bool = False) -> None:
        """Log this character in and fire the login event sequence.

        Why this exists:
            Most addons do their real work on ``PLAYER_LOGIN`` and
            ``PLAYER_ENTERING_WORLD``; a scenario needs that exact sequence,
            with the reload flag the second event carries.

        Args:
            is_reload: Whether this login follows a UI reload rather than a
                fresh login.

        Returns:
            ``None``; the client is online and logged in.

        Failure modes:
            None of its own; Lua errors inside event handlers are recorded in
            ``errors`` by the protected event dispatch.
        """
        self._logged_in = True
        self.online = True
        if self._world.is_event_valid("PLAYER_LOGIN"):
            self._fire_internal("PLAYER_LOGIN")
        if self._world.is_event_valid("PLAYER_ENTERING_WORLD"):
            self._fire_internal("PLAYER_ENTERING_WORLD", not is_reload, is_reload)

    def _flush_one(self, var: str, store: dict[str, Any]) -> None:
        value = self._controller.raw_get_global(var)
        exported = export_saved_value(value, var_name=var)
        # [2026-11-11 T-007] A nil saved variable is removed from the store, not
        # stored as an explicit None: the client writes no line for it, and a
        # later restore must see the same "never set" state.
        if exported is None:
            store.pop(var, None)
        else:
            store[var] = exported

    def flush_saved_variables(self) -> None:
        """Snapshot every loaded addon's SavedVariables into Python stores.

        Why this exists:
            Reload and logout both persist state the way the client writes it
            to disk; doing the strict export here means unserialisable state
            fails at flush time, with the variable named, not at next login.

        Args:
            None.

        Returns:
            ``None``; ``account_saved_variables`` and
            ``character_saved_variables`` hold the exported plain data.

        Failure modes:
            Raises ``SavedVariablesError`` when a saved value holds something
            the client could not write (a function, a cycle, a non-finite
            number).
        """
        for addon in list(self._loaded_addons):
            for var in addon.toc.saved_variables:
                self._flush_one(var, self.account_saved_variables)
            for var in addon.toc.saved_variables_per_character:
                self._flush_one(var, self.character_saved_variables)

    def reload(self) -> None:
        """Reload the UI: persist state, rebuild the VM, replay every addon.

        Why this exists:
            ``/reload`` is where SavedVariables and load-time registration bugs
            surface; the simulation reproduces its whole contract, including
            that addon code must register its message prefixes again because
            the fresh VM starts with none.

        Args:
            None.

        Returns:
            ``None``; the client is logged in again with ``is_reload`` set on
            its entering-world event, and its throttle buckets keep their
            state on the unchanged world clock.

        Failure modes:
            Raises ``SavedVariablesError`` from the flush when state cannot be
            persisted, and ``HeadlessError`` when an addon folder that loaded
            before can no longer be read.
        """
        self.flush_saved_variables()
        self._world._cancel_owner(self)
        paths = [addon.path for addon in self._loaded_addons]
        self._loaded_addons = []
        self.registered_prefixes.clear()
        self._logged_in = False
        self._init_vm()
        for addon_path in paths:
            self.load_addon(addon_path, login=False)
        self.login(is_reload=True)

    def logout(self) -> None:
        """Log this character out, persisting state and stopping its timers.

        Why this exists:
            An offline guild member must stop receiving messages and stop
            running timers, while the state it saved must survive for a later
            login on the same client object.

        Args:
            None.

        Returns:
            ``None``; the client is offline and no longer logged in. A valid
            ``PLAYER_LOGOUT`` event is fired before state is flushed, so
            addons can do their own logout bookkeeping.

        Failure modes:
            Raises ``SavedVariablesError`` from the flush when state cannot be
            persisted.
        """
        if self._logged_in and self._world.is_event_valid("PLAYER_LOGOUT"):
            self._fire_internal("PLAYER_LOGOUT")
        self.flush_saved_variables()
        self._world._cancel_owner(self)
        self.online = False
        self._logged_in = False

    def set_restriction(self, regime: str | int, active: bool = True) -> None:
        """Activate or lift an addon-restriction regime on this client.

        Why this exists:
            WoW: Forever restricts addon sends and secret values during combat,
            encounters, Mythic+, PvP matches, and restricted maps; scenarios
            toggle those regimes here to prove addons queue and recover cleanly.

        Args:
            regime: Regime name (for example ``"Combat"`` or ``"Encounter"``)
                or its ``Enum.AddOnRestrictionType`` integer.
            active: ``True`` to activate the regime, ``False`` to lift it.

        Returns:
            ``None``; fires ``ADDON_RESTRICTION_STATE_CHANGED(type, state)``
            when that event is valid in this world.

        Failure modes:
            Raises ``ValueError`` when ``regime`` does not name a known
            ``AddOnRestrictionType``.
        """
        regime_id = self._restriction_id_for(regime)
        if regime_id is None:
            raise ValueError(f"unknown addon restriction regime: {regime!r}")
        if active:
            self._active_restrictions.add(regime_id)
            state_val = self._world.enum_value("AddOnRestrictionState", "Active", 2)
        else:
            self._active_restrictions.discard(regime_id)
            state_val = self._world.enum_value("AddOnRestrictionState", "Inactive", 0)
        if self._world.is_event_valid("ADDON_RESTRICTION_STATE_CHANGED"):
            self._fire_internal("ADDON_RESTRICTION_STATE_CHANGED", regime_id, state_val)

    def set_rank(self, rank: int | None, rank_name: str | None = None) -> None:
        """Change this character's guild rank (or remove them from the guild).

        Why this exists:
            Trust rules re-evaluate rank at reduce time so demoting a member
            stops later officer records from applying; scenarios drive promotions
            and demotions through this method.

        Args:
            rank: New rank index (``0`` is Guild Master), or ``None`` for unguilded.
            rank_name: Optional display name; derived from ``rank`` when ``None``.

        Returns:
            ``None``; fires ``GUILD_ROSTER_UPDATE(true)`` on logged-in guildmates.

        Failure modes:
            None.
        """
        self.rank = rank
        self.rank_name = rank_name if rank_name is not None else _default_rank_name(rank)
        if self._world.is_event_valid("GUILD_ROSTER_UPDATE"):
            for member in list(self._world.clients):
                if member.online and member.logged_in:
                    member._fire_internal("GUILD_ROSTER_UPDATE", True)

    def set_instance(
        self,
        *,
        in_instance: bool,
        instance_type: str = "none",
        name: str = "",
        difficulty_id: int = 0,
        max_players: int = 0,
        instance_id: int = 0,
    ) -> None:
        """Set this character's instance state for ``IsInInstance`` / ``GetInstanceInfo``.

        Why this exists:
            Participation tracking checks instance type and IDs on world entry
            and encounter events; scenarios configure that state here.

        Args:
            in_instance: Returned as the first value of ``IsInInstance()``.
            instance_type: ``"none"``, ``"party"``, ``"raid"``, ``"pvp"``, or ``"arena"``.
            name: Zone/instance name returned by ``GetInstanceInfo()``.
            difficulty_id: Numeric difficulty ID.
            max_players: Instance player cap.
            instance_id: Instance map ID.

        Returns:
            ``None``.

        Failure modes:
            None.
        """
        self._in_instance = bool(in_instance)
        self._instance_type = str(instance_type)
        self._instance_name = str(name)
        self._difficulty_id = int(difficulty_id)
        self._instance_max_players = int(max_players)
        self._instance_id = int(instance_id)

    def set_pvp_kills(self, honorable_kills: int) -> None:
        """Update lifetime honourable kills and fire ``PLAYER_PVP_KILLS_CHANGED``.

        Why this exists:
            World-PvP participation tracking reads honourable-kill deltas from
            ``GetPVPLifetimeStats`` when ``PLAYER_PVP_KILLS_CHANGED`` fires.

        Args:
            honorable_kills: New lifetime honourable-kill count.

        Returns:
            ``None``.

        Failure modes:
            None.
        """
        self.honorable_kills = int(honorable_kills)
        if (
            self.online
            and self._logged_in
            and self._world.is_event_valid("PLAYER_PVP_KILLS_CHANGED")
        ):
            self._fire_internal("PLAYER_PVP_KILLS_CHANGED")

    def fire(self, event: str, *args: Any) -> None:
        """Fire a game event on this client's registered frames.

        Why this exists:
            Scenarios drive addon behaviour by firing documented client events
            with controlled payloads.

        Args:
            event: Literal event name; must be valid in ``world``.
            *args: Payload arguments passed after ``(frame, event)`` to ``OnEvent``.

        Returns:
            ``None``.

        Failure modes:
            Raises ``HeadlessError`` when ``event`` is not valid in ``world``.
        """
        if not self._world.is_event_valid(event):
            raise HeadlessError(f"cannot fire unknown or disabled event {event!r}")
        self._fire_internal(event, *args)

    def slash(self, text: str) -> bool:
        """Invoke a slash command line such as ``"/gh post hello"``.

        Why this exists:
            Addons expose user entry points through ``SLASH_*`` globals and
            ``SlashCmdList``; scenarios and ``wow_check`` exercise them here.

        Args:
            text: Full slash line starting with ``/``.

        Returns:
            ``True`` when a matching ``SlashCmdList`` handler was found and
            invoked, ``False`` otherwise.

        Failure modes:
            None raised; errors inside the slash handler are recorded in ``errors``.
        """
        return bool(self._controller.run_slash(text))

    def registered_slash_commands(self) -> list[str]:
        """Return every slash command token registered in ``SlashCmdList``, sorted.

        Why this exists:
            ``wow_check`` stage 5 invokes every slash command an addon registered
            with an empty argument to verify none crash on first open.

        Args:
            None.

        Returns:
            Sorted list of slash tokens (for example ``["/gh", "/guildhall"]``).

        Failure modes:
            None.
        """
        lua_list = self._controller.list_slash_commands()
        return [str(item) for item in lua_list.values()]

    def run_lua(self, lua_source: str, *, chunk_name: str = "scenario.lua") -> Any:
        """Compile and run a Lua expression or chunk in this client's VM.

        Why this exists:
            Scenario assertions inspect addon state and exercise strict API
            errors directly inside the client's Lua 5.1 environment; expression
            shorthand (``"1 + 1"``) is tried first and multi-statement chunks
            fall back cleanly.

        Args:
            lua_source: A Lua expression or statement block.
            chunk_name: File/chunk label used in compile and runtime messages.

        Returns:
            The first return value of the expression or chunk (as lupa presents
            it), or ``None`` when nothing is returned.

        Failure modes:
            Raises ``luavm.LuaChunkError`` when the source fails to compile or
            raises an unhandled Lua error.
        """
        as_expr = f"return {lua_source}"
        if luavm.check_syntax(self._runtime, as_expr, chunk_name) is None:
            return luavm.run_chunk_value(self._runtime, as_expr, chunk_name)
        return luavm.run_chunk_value(self._runtime, lua_source, chunk_name)

    def eval(self, lua_source: str) -> Any:
        """Run ``lua_source`` in this client's VM (SPEC-PLUGIN §6 scenario API).

        Why this exists:
            Named in ``docs/SPEC-PLUGIN.md`` §6 as the scenario evaluation entry
            point; delegates to ``run_lua``.

        Args:
            lua_source: A Lua expression or statement block.

        Returns:
            The first return value of the expression or chunk.

        Failure modes:
            Raises ``luavm.LuaChunkError`` on compile or runtime failure.
        """
        return self.run_lua(lua_source)
