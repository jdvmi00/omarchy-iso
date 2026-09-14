"""Temporary settings for the validated Surface Laptop 8 bring-up desktop.

The caller must match the exact Surface platform first. These are installed
under /etc and the new user's home; packaged Omarchy defaults are not edited.
"""

from pathlib import Path
import re
import shutil
import subprocess


PACKAGE = "omarchy-surface-laptop8-bringup"
DATA = Path("usr/share/omarchy-surface-laptop8")


def configure_system(ctx):
    data = ctx.target / DATA
    if not (data / "hyprland.lua").is_file():
        raise RuntimeError(f"{PACKAGE} missing from target")
    # The Qualcomm blobs used in step 05 are packaged. Do not activate the
    # untested Windows DSP/Wi-Fi blobs preserved separately in this package.
    for name in ("gen80100_sqe.fw", "gen80100_gmu.bin"):
        path = ctx.target / "usr/lib/firmware/qcom" / name
        if not path.is_file() or not path.stat().st_size:
            raise RuntimeError(f"Surface GPU firmware missing: {path}")

    logind = ctx.target / "etc/systemd/logind.conf.d/80-surface-laptop8-bringup.conf"
    logind.parent.mkdir(parents=True, exist_ok=True)
    logind.write_text("[Login]\nHandleLidSwitch=ignore\nHandleLidSwitchExternalPower=ignore\nHandleLidSwitchDocked=ignore\nIdleAction=ignore\n")
    # Display blanking, suspend and hibernation need separate hardware tests.
    units = ctx.target / "etc/systemd/system"
    units.mkdir(parents=True, exist_ok=True)
    for unit in ("sleep.target", "suspend.target", "hibernate.target", "hybrid-sleep.target", "suspend-then-hibernate.target", "sddm.service"):
        dest = units / unit
        if dest.is_symlink():
            dest.unlink()
        elif dest.exists():
            raise RuntimeError(f"Refusing to replace existing unit: {dest}")
        dest.symlink_to("/dev/null")
    # Keep the tested console-to-UWSM path. Final user setup below enables
    # autologin only when disk unlock already authenticates the owner.
    display_manager = units / "display-manager.service"
    if display_manager.is_symlink():
        display_manager.unlink()
    autologin = units / "getty@tty1.service.d/autologin.conf"
    autologin.unlink(missing_ok=True)
    wants = units / "getty.target.wants"
    wants.mkdir(exist_ok=True)
    getty = wants / "getty@tty1.service"
    if not getty.exists() and not getty.is_symlink():
        getty.symlink_to("/usr/lib/systemd/system/getty@.service")


def configure_user(ctx):
    if ctx.defer_provisioning:
        raise RuntimeError("Surface bring-up requires creating the user during installation")
    home = ctx.target / "home" / ctx.username
    data = ctx.target / DATA
    hypr = home / ".config/hypr"
    hypr.mkdir(parents=True, exist_ok=True)
    # Keep the fixed panel mode in the normal file edited by the display menu.
    # A later hard-coded Surface scale would undo each menu change on reload.
    shutil.copy2(data / "monitors.lua", hypr / "monitors.lua")
    shutil.copy2(data / "hyprland.lua", hypr / "surface-laptop8.lua")
    config = hypr / "hyprland.lua"
    text = config.read_text()
    prelude = '-- Surface bring-up: validated startup excludes monitor/power automation.\npackage.loaded["default.hypr.autostart"] = true\n'
    defaults = 'require("default.hypr.omarchy")'
    if text.count(defaults) != 1:
        raise RuntimeError("Surface bring-up requires one Omarchy defaults import")
    # Bootstrap clears default.hypr modules on every load. Suppress autostart
    # afterwards, immediately before defaults import it, including on reload.
    # Also relocate the prelude written by earlier installer candidates.
    text = text.replace(prelude, "")
    text = text.replace(defaults, prelude + defaults, 1)
    load = 'require("hypr.surface-laptop8")'
    if load not in text:
        text = text.rstrip() + "\n\n" + load + "\n"
    config.write_text(text)

    uwsm = home / ".config/uwsm/env"
    uwsm.parent.mkdir(parents=True, exist_ok=True)
    _append_once(uwsm, (data / "uwsm-env").read_text())
    # Both shells are used by Omarchy installations. The guard restricts
    # startup to the physical login console, never an SSH or terminal shell.
    login = (data / "console-login.sh").read_text()
    for name in (".bash_profile", ".zprofile"):
        _append_once(home / name, login)
    awake = home / ".local/state/omarchy/indicators/stay-awake"
    awake.parent.mkdir(parents=True, exist_ok=True)
    awake.touch()
    subprocess.run(["arch-chroot", str(ctx.target), "chown", "-R", f"{ctx.username}:{ctx.username}", f"/home/{ctx.username}"], check=True)
    configure_console_login(ctx)


def configure_console_login(ctx):
    autologin = ctx.target / "etc/systemd/system/getty@tty1.service.d/autologin.conf"
    if not ctx.encrypt or ctx.defer_provisioning:
        autologin.unlink(missing_ok=True)
        return
    # Match the normal encrypted install's login behavior, using the console
    # path already tested on Surface instead of introducing a display manager.
    if ctx.username == "root" or not re.fullmatch(r"[a-z_][a-z0-9_-]*\$?", ctx.username):
        raise RuntimeError("Surface autologin requires a valid non-root username")
    autologin.parent.mkdir(parents=True, exist_ok=True)
    autologin.write_text(
        "[Service]\n"
        "ExecStart=\n"
        f"ExecStart=-/usr/bin/agetty --autologin {ctx.username} --noreset --noclear - $TERM\n"
    )


def _append_once(path, text):
    previous = path.read_text() if path.exists() else ""
    if text.strip() not in previous:
        path.write_text(previous.rstrip() + "\n\n" + text.rstrip() + "\n")
