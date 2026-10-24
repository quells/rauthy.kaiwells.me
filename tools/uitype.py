#!/usr/bin/env python3
"""Type the value of an env var into a named field, via uiclick's AT-SPI helpers.

Refuses to type unless the target field reports FOCUSED after GrabFocus, so
keystrokes can't land in some other window. Never prints the value.

Usage: uitype.py --app Firefox [--enter] "E-Mail" RAUTHY_TEST_USER

Requires ~/.local/bin/uiclick (AT-SPI lookup + Mutter RemoteDesktop key injection).
"""
import argparse, os, sys, time
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader

path = os.path.expanduser("~/.local/bin/uiclick")
loader = SourceFileLoader("uiclick", path)
uiclick = module_from_spec(spec_from_loader("uiclick", loader))
loader.exec_module(uiclick)
import dbus

FOCUSED = 1 << 12  # ATSPI_STATE_FOCUSED


def type_text(text):
    bus = dbus.SessionBus()
    p = bus.get_object(uiclick.RD_DEST, uiclick.RD_PATH).CreateSession(
        dbus_interface=uiclick.RD_IFACE, timeout=uiclick.CALL_TIMEOUT)
    s = dbus.Interface(bus.get_object(uiclick.RD_DEST, p), uiclick.RD_SESSION_IFACE)
    s.Start(timeout=uiclick.CALL_TIMEOUT)
    time.sleep(0.2)
    for ch in text:
        cp = ord(ch)
        sym = cp if 0x20 <= cp <= 0x7e else 0x01000000 + cp
        s.NotifyKeyboardKeysym(dbus.UInt32(sym), True, timeout=uiclick.CALL_TIMEOUT)
        s.NotifyKeyboardKeysym(dbus.UInt32(sym), False, timeout=uiclick.CALL_TIMEOUT)
        time.sleep(0.02)
    time.sleep(0.2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("field")
    ap.add_argument("env_var")
    ap.add_argument("--enter", action="store_true", help="press Enter afterwards")
    a = ap.parse_args()
    text = os.environ.get(a.env_var)
    if not text:
        sys.exit(f"{a.env_var} is not set")
    conn = uiclick.a11y_bus(uiclick.session_bus())
    found = uiclick.find(conn, a.app, a.field)
    if len(found) != 1:
        sys.exit(f"{len(found)} matches for {a.field!r}; need exactly 1")
    app_name, name, node = found[0]
    uiclick.focus(conn, node)
    time.sleep(0.3)
    if not uiclick.state(conn, node) & FOCUSED:
        sys.exit(f"{name!r} did not take focus; not typing")
    type_text(text)
    if a.enter:
        if not uiclick.state(conn, node) & FOCUSED:
            sys.exit(f"{name!r} lost focus after typing; not pressing Enter")
        uiclick.key(uiclick.ENTER)
    print(f"typed {len(text)} chars from {a.env_var} into {name!r} in {app_name}")


if __name__ == "__main__":
    main()
