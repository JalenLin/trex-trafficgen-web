"""TRex STL Python profiles, run inside a TRex worker process.

A profile is Python code: loading one executes it. Profiles are only read from
directories the server operator controls (see profiles.py); this module assumes
the path has already been vetted.

Profiles take parameters two ways:
  - TRex 3.x: get_streams(self, port_id, direction, tunables, **kwargs) parses
    `tunables` (a list like ["--size", "64"]) with argparse inside.
  - older:    get_streams(self, direction=0, size=64, ...) keyword arguments.
"""
import argparse
import hashlib
import importlib.util
import inspect
import os
import sys

_SKIP = {"self", "port_id", "direction", "tunables", "kwargs"}


class _Captured(Exception):
    def __init__(self, parser):
        super().__init__()
        self.parser = parser


def _load_module(path: str):
    # A unique module name per file: profiles in different folders often share
    # names (bench.py), and importlib would otherwise hand back the cached one.
    name = "trexgui_profile_" + hashlib.sha1(path.encode()).hexdigest()[:12]
    basedir = os.path.dirname(path)
    sys.path.insert(0, basedir)  # profiles may import helpers next to them
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(basedir)


def _argparse_parser(register):
    """Run get_streams just far enough to grab the argparse parser it builds."""
    original = (argparse.ArgumentParser.parse_args, argparse.ArgumentParser.parse_known_args)

    def grab(self, *args, **kwargs):
        raise _Captured(self)

    argparse.ArgumentParser.parse_args = grab
    argparse.ArgumentParser.parse_known_args = grab
    try:
        register.get_streams(port_id=0, direction=0, tunables=[])
    except _Captured as c:
        return c.parser
    finally:
        argparse.ArgumentParser.parse_args, argparse.ArgumentParser.parse_known_args = original
    return None  # no argparse: the profile ignores its tunables


def _option(action) -> dict:
    flag = max(action.option_strings, key=len)
    if isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
        kind = "bool"
    elif action.choices:
        kind = "choice"
    elif action.type in (int, float):
        kind = "number"
    else:
        kind = "text"
    default = action.default
    help_text = (action.help or "").replace("%(default)s", str(default))
    return {
        "name": action.dest,
        "flag": flag,
        "kind": kind,
        "default": default if isinstance(default, (bool, int, float)) or default is None else str(default),
        "choices": [str(c) for c in action.choices] if action.choices else None,
        "help": " ".join(help_text.split()),
        "store_false": isinstance(action, argparse._StoreFalseAction),
    }


def info(path: str) -> dict:
    module = _load_module(path)
    register = module.register()
    doc = (module.__doc__ or type(register).__doc__ or "").strip()
    params = inspect.signature(register.get_streams).parameters
    if "tunables" in params:
        parser = _argparse_parser(register)
        options = [_option(a) for a in (parser._actions if parser else [])
                   if a.option_strings and not isinstance(a, argparse._HelpAction)]
        return {"style": "argparse", "doc": doc[:3000], "options": options,
                "description": (parser.description or "") if parser else ""}
    options = []
    for name, p in params.items():
        if name in _SKIP or p.kind in (p.VAR_KEYWORD, p.VAR_POSITIONAL):
            continue
        d = None if p.default is inspect.Parameter.empty else p.default
        kind = "bool" if isinstance(d, bool) else "number" if isinstance(d, (int, float)) else "text"
        options.append({"name": name, "flag": name, "kind": kind, "default": d if isinstance(d, (bool, int, float)) or d is None else str(d),
                        "choices": None, "help": "", "store_false": False})
    return {"style": "kwargs", "doc": doc[:3000], "options": options, "description": ""}


def load_streams(path: str, port_id: int, values: dict) -> list:
    """The profile's streams for one port, with the user's parameter values."""
    meta = info(path)
    module = _load_module(path)
    register = module.register()
    direction = port_id % 2  # what TRex console passes: even ports are "client" side
    given = {o["name"]: o for o in meta["options"]}
    if meta["style"] == "argparse":
        tunables = []
        for name, value in values.items():
            opt = given.get(name)
            if opt is None or value is None or value == "":
                continue
            if opt["kind"] == "bool":
                if bool(value) != (opt["default"] is True):  # only pass the flag to change the default
                    tunables.append(opt["flag"])
            else:
                tunables += [opt["flag"], str(value)]
        streams = register.get_streams(port_id=port_id, direction=direction, tunables=tunables)
    else:
        kwargs = {}
        for name, value in values.items():
            opt = given.get(name)
            if opt is None or value is None or value == "":
                continue
            d = opt["default"]
            kwargs[name] = type(d)(value) if isinstance(d, (int, float)) and not isinstance(d, bool) else value
        params = inspect.signature(register.get_streams).parameters
        extra = {k: v for k, v in (("port_id", port_id), ("direction", direction)) if k in params or any(
            p.kind == p.VAR_KEYWORD for p in params.values())}
        streams = register.get_streams(**extra, **kwargs)
    if hasattr(streams, "get_streams"):  # some profiles return an STLProfile
        streams = streams.get_streams()
    if not isinstance(streams, list):
        streams = [streams]
    return streams
