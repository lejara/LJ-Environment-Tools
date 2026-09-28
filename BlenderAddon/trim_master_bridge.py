"""Optional integration with the LJ Trim Master extension.

Trim Master transforms UVs into trim-sheet space only inside exported files, by
hooking Blender's FBX operator. That hook cannot see through our duplicate-and-
apply step: the copies we export are unknown to its registry. So we ask it to
transform the originals *before* duplicating, and the copies inherit the result.

Soft dependency - when Trim Master is not installed or not enabled this is a
no-op, and nothing here imports it at load time.
"""

import sys
from contextlib import contextmanager


def _export_hook():
    """Trim Master's ``export_hook`` module, if it is loaded.

    An extension's package name depends on the repository it was installed
    from (``bl_ext.user_default.lj_trim_master``), and a legacy add-on install
    is plain ``lj_trim_master``, so match on the suffix.
    """
    for name, module in list(sys.modules.items()):
        if module is None:
            continue
        if name == "lj_trim_master.export_hook" or name.endswith(".lj_trim_master.export_hook"):
            # `uv_transform_applied` + `commit` are the core every build has;
            # `external_export` only exists in newer ones, see `_external_export`.
            if hasattr(module, "uv_transform_applied") and hasattr(module, "commit"):
                return module
    return None


class _Session:
    def __init__(self, plan):
        self.plan = plan
        self.succeeded = False

    @property
    def count(self):
        return self.plan.count if self.plan is not None else 0


@contextmanager
def _external_export(hook, context, report, apply_modifiers):
    """``hook.external_export``, rebuilt for Trim Master builds that predate it."""
    external = getattr(hook, "external_export", None)
    if external is not None:
        with external(context, report, apply_modifiers, selection_only=True) as session:
            yield session
        return
    with hook.uv_transform_applied(context, report, apply_modifiers, True) as plan:
        session = _Session(plan)
        yield session
    if session.succeeded:
        hook.commit(context, plan)


def is_available():
    return _export_hook() is not None


class _NoSession:
    def __init__(self):
        self.succeeded = False
        self.count = 0


@contextmanager
def _bypassed(hook):
    """Keep Trim Master's FBX ``execute`` hook out of the exports inside.

    Without this, turning support off would still transform UVs whenever the
    originals themselves are exported (Apply Transforms off), because the hook
    sees them selected. Older Trim Master builds have no ``bypass``; their
    re-entrancy guard does the same job.
    """
    bypass = getattr(hook, "bypass", None)
    if bypass is not None:
        with bypass():
            yield
        return
    hook._depth += 1
    try:
        yield
    finally:
        hook._depth -= 1


@contextmanager
def trim_uvs_applied(context, report, apply_modifiers, enabled=True):
    """Yield a session; set ``session.succeeded = True`` once the file is written.

    With *enabled* False the export behaves as if Trim Master were not
    installed: no UVs are transformed and no slot is marked exported.
    """
    hook = _export_hook()
    if hook is None:
        yield _NoSession()
        return
    if not enabled:
        with _bypassed(hook):
            yield _NoSession()
        return
    with _external_export(hook, context, report, apply_modifiers) as session:
        yield session
