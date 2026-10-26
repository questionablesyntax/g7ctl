"""`Operation`: one immutable, inspectable write that `write_state()`
would send -- a literal record of which category-module function to
call and with what arguments, instead of an opaque closure. Introduced
for S1 (the GUI redesign's wave 2 plan, Track S, Projects/g7ctl/redesign/
IMPLEMENTATION-PLAN.md): a step built this way can be logged, compared or
serialized before anything touches the device, which an already-bound
closure can't. Deliberately literal/un-abstracted -- this is S1's scope
only, not S3's later intent semantics (see `field_spec.py`) or S4's
revision-bound job; it exists so *this* step has data behind it, not to
redesign what gets written or when.

Its own module, separate from `state.py` (which originally defined it):
`field_spec.py` (S3) needs `Operation` too, and also needs the category
modules' own `decode_settings()`/similar for knownness, so `state.py` ->
`field_spec.py` -> `state.py` would cycle if `Operation` stayed there --
`state.py` still imports the category modules for its own
not-yet-migrated inline fields, and a field's own module (e.g.
`report_rate.py`) importing `field_spec.py` to build its `FieldSpec`
closes the loop back through here. Splitting `Operation` out breaks it:
every direction now imports `operations.py`, not `state.py`.
"""
from dataclasses import dataclass, field
from typing import Callable

from . import buttons, dock_settings, dpad_options, motion, report_rate, sticks, triggers, vibration
from .session import VendorSession


@dataclass(frozen=True)
class Operation:
    kind: str
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)

    def execute(self, session: VendorSession) -> bytes:
        return _OPERATION_FUNCS[self.kind](session, *self.args, **self.kwargs)

    # Callable too, as `execute()`'s alias -- existing tests (and any
    # other caller) that iterate steps and call `write_fn(session)`
    # directly, from when the second element of a Step was a bare
    # closure, keep working unchanged. "Unchanged library behaviour" is
    # one of S1's own acceptance criteria.
    __call__ = execute


# Registry backing Operation.execute() -- the only place `kind` strings are
# resolved to a real function, so the set of possible operations is closed
# and inspectable, not a dynamic getattr() on an arbitrary name.
_OPERATION_FUNCS: dict[str, Callable[..., bytes]] = {
    "button_remap": buttons.remap,
    "button_unbind": buttons.unbind,
    "continuous_trigger": buttons.set_continuous_trigger,
    "report_rate": report_rate.set_value,
    "dpad_option": dpad_options.set_value,
    "dock_setting": dock_settings.set_value,
    "stick_setting": sticks.set_value,
    "trigger_setting": triggers.set_value,
    "motion_setting": motion.set_value,
    "vibration_setting": vibration.set_value,
}
