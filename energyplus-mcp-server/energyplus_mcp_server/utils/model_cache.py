"""Parse each model once per capability call.

A capability check runs several managers, and each used to parse the same IDF
on its own (twelve parses of one model for ``parameter_capabilities``). Within
a ``shared_models()`` scope, ``read_only_idf(path)`` returns one parsed model
per file instead.

Safety rules:

- Only read-only callers use ``read_only_idf`` (capability checks,
  inspections, dry-run plans). Anything that edits and saves a model keeps
  parsing its own fresh copy.
- The cache lives only for the outermost scope (one tool call) and is keyed by
  the resolved path, file size, modification time and loader, so a file that
  changes is parsed again and nothing outlives the call.
- Outside a scope, ``read_only_idf`` simply parses, exactly as before.
- ``derived(model, name, factory)`` memoizes data computed from a shared
  model (such as its schedule graph) for the same scope, under the same
  read-only rule; for any other model it simply computes.
- With ``EPLUS_MCP_VERIFY_SHARED_MODELS=1`` (tests and the equivalence
  harness), leaving the outermost scope re-parses every shared file and fails
  if any shared model was changed in memory.

The scope is a ContextVar, so concurrent tool calls in different threads never
share models.
"""

from __future__ import annotations

import contextlib
import os
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional, Tuple

VERIFY_ENV = "EPLUS_MCP_VERIFY_SHARED_MODELS"

_Key = Tuple[str, int, int, int]


class _Scope:
    """Parsed models and data derived from them, for one capability call."""

    def __init__(self) -> None:
        self.models: Dict[_Key, Tuple[Any, Callable[[str], Any], str]] = {}
        self.shared_ids: set[int] = set()
        self.derived: Dict[Tuple[int, str], Any] = {}


_scope: ContextVar[Optional[_Scope]] = ContextVar("eplus_shared_models", default=None)


def _default_loader(path: str) -> Any:
    from eppy.modeleditor import IDF

    return IDF(path)


@contextlib.contextmanager
def shared_models() -> Iterator[None]:
    """Share read-only parsed models until the outermost scope ends (re-entrant)."""
    if _scope.get() is not None:
        yield
        return
    scope = _Scope()
    token = _scope.set(scope)
    try:
        yield
        if os.environ.get(VERIFY_ENV) == "1":
            _verify_unchanged(scope.models)
    finally:
        _scope.reset(token)


def with_shared_models(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Run ``fn`` inside a ``shared_models()`` scope."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with shared_models():
            return fn(*args, **kwargs)

    return wrapper


def read_only_idf(path: str, loader: Optional[Callable[[str], Any]] = None) -> Any:
    """Parsed model for ``path``; shared within a ``shared_models()`` scope.

    Callers must not modify the returned model.
    """
    load = loader or _default_loader
    scope = _scope.get()
    if scope is None:
        return load(path)
    resolved = str(Path(path).resolve())
    stat = os.stat(resolved)
    key = (resolved, stat.st_size, stat.st_mtime_ns, id(load))
    entry = scope.models.get(key)
    if entry is None:
        entry = (load(resolved), load, resolved)
        scope.models[key] = entry
        scope.shared_ids.add(id(entry[0]))
    return entry[0]


def derived(model: Any, name: str, factory: Callable[[], Any]) -> Any:
    """Data computed from ``model``, computed once per scope for a shared model.

    For a model that is not a shared read-only model of the current scope (for
    example the private copy an applied edit works on) ``factory`` simply runs
    every time. Callers must not modify the returned data.
    """
    scope = _scope.get()
    if scope is None or id(model) not in scope.shared_ids:
        return factory()
    key = (id(model), name)
    if key not in scope.derived:
        scope.derived[key] = factory()
    return scope.derived[key]


def _text(idf: Any) -> Optional[str]:
    idfstr = getattr(idf, "idfstr", None)
    return idfstr() if callable(idfstr) else None


def _verify_unchanged(cache: Dict[_Key, Tuple[Any, Callable[[str], Any], str]]) -> None:
    for idf, load, path in cache.values():
        shared = _text(idf)
        if shared is None:
            continue
        if shared != _text(load(path)):
            raise AssertionError(f"a shared read-only model was modified in memory: {path}")
