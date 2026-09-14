"""Surface installer boundaries; hardware operation is tested separately."""
import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "configs/airootfs/usr/share/omarchy-iso"))
sys.modules.setdefault("orchestrator.archinstall_adapter", types.ModuleType("orchestrator.archinstall_adapter"))
from orchestrator import phases_impl as phases, surface_laptop8

MANIFEST = ROOT / "configs/aarch64/platforms.json"
SURFACE = next(x for x in json.loads(MANIFEST.read_text())["platforms"] if x["id"] == "microsoft-surface-laptop8")


class SurfaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ctx = types.SimpleNamespace(target=self.root, username="jim", defer_provisioning=False, encrypt=False,
                                         is_protected=False, omarchy_install={"boot": {"esp_mount": "/boot"}})

    def test_match_requires_both_hardware_identity_fields(self):
        dmi = self.root / "dmi"
        dmi.mkdir()
        (dmi / "product_name").write_text("Surface Laptop 13.8in 8th Ed Snapdragon\n")
        (dmi / "sys_vendor").write_text("Microsoft Corporation\n")
        with mock.patch.object(phases.platform, "machine", return_value="aarch64"), mock.patch.object(phases, "DMI_ID_ROOT", dmi), mock.patch.object(phases, "AARCH64_PLATFORM_MANIFEST", MANIFEST):
            self.assertEqual(phases._current_aarch64_platform()["id"], SURFACE["id"])
            (dmi / "sys_vendor").write_text("another manufacturer\n")
            self.assertIsNone(phases._current_aarch64_platform())

    def test_efi_fallback_copies_arm_binary_without_variable_access(self):
        binary = self.root / "usr/share/limine/BOOTAA64.EFI"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"ARM EFI test fixture")
        with mock.patch.object(phases.platform, "machine", return_value="aarch64"), mock.patch.object(phases, "_read_efibootmgr", side_effect=AssertionError("NVRAM accessed")), mock.patch.object(phases, "_register_limine_efi_entry", side_effect=AssertionError("NVRAM written")):
            phases._install_limine_efi(self.ctx, esp_mount="/boot", disk=Path("/dev/fixture"), part=1, removable=True, register_entry=False)
        self.assertEqual((self.root / "boot/EFI/BOOT/BOOTAA64.EFI").read_bytes(), binary.read_bytes())
        self.assertIn("/boot/EFI/BOOT/BOOTAA64.EFI", (self.root / "etc/pacman.d/hooks/99-omarchy-limine.hook").read_text())

    def test_surface_installs_snapshot_and_boot_tools_without_runtime_dependencies(self):
        # The ARM runtime has Asahi dependencies and does not pull in this
        # UEFI boot stack. System setup needs snapper before it can finish.
        with mock.patch.object(phases, "_current_aarch64_platform", return_value=SURFACE), mock.patch.object(Path, "read_text", return_value=""), mock.patch.object(phases, "_early_packages", return_value=[]):
            packages = phases._runtime_package_list(self.ctx)
        self.assertLessEqual({"snapper", "limine-mkinitcpio-hook", "limine-snapper-sync"}, set(packages))

    def test_other_removable_installs_keep_their_registration_behavior(self):
        binary = self.root / "usr/share/limine/BOOTAA64.EFI"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"ARM EFI test fixture")
        with mock.patch.object(phases.platform, "machine", return_value="aarch64"), mock.patch.object(phases, "_register_limine_efi_entry") as register:
            phases._install_limine_efi(self.ctx, esp_mount="/boot", disk=Path("/dev/fixture"), part=1, removable=True)
        register.assert_called_once_with(Path("/dev/fixture"), 1, "\\EFI\\BOOT\\BOOTAA64.EFI", pre_state=None)

    def test_surface_keeps_graphical_unlock_on_the_local_console(self):
        dtb = self.root / "boot/dtbs" / SURFACE["boot"]["dtb"]
        dtb.parent.mkdir(parents=True)
        dtb.write_bytes(b"test device tree")
        with mock.patch.object(phases, "_current_aarch64_platform", return_value=SURFACE), mock.patch.object(phases, "AARCH64_PLATFORM_MANIFEST", MANIFEST):
            phases._configure_aarch64_platform_boot(self.ctx)
        dropin = self.root / "etc/limine-entry-tool.d/80-omarchy-aarch64-platform.conf"
        result = subprocess.run([
            "bash", "-c", 'declare -A KERNEL_CMDLINE=([default]="quiet splash"); source "$1"; printf "%s\\n" "${KERNEL_CMDLINE[default]}"',
            "bash", str(dropin),
        ], check=True, text=True, capture_output=True)
        arguments = result.stdout.split()
        self.assertIn("console=tty0", arguments)
        self.assertIn("plymouth.ignore-serial-consoles", arguments)
        self.assertIn("splash", arguments)
        self.assertNotIn("plymouth.ignore-show-splash", arguments)
        self.assertNotIn("plymouth.enable=0", arguments)

    def test_surface_uses_linux_entry_for_external_device_tree(self):
        template = self.root / "template"
        template.mkdir()
        (template / "default.conf").write_text('ESP_PATH="/boot"\nKERNEL_CMDLINE[default]+="@@CMDLINE@@"\n')
        (template / "limine.conf").write_text('/Omarchy\n')
        with mock.patch.object(phases, "_current_aarch64_platform", return_value=SURFACE), mock.patch.object(phases, "_limine_template", side_effect=lambda ctx, name: template / name), mock.patch.object(phases.arch, "has_uefi", return_value=True, create=True):
            phases._write_limine_defaults(self.ctx, "root=UUID=fixture", esp_mount="/boot", enable_uki=True)
        self.assertIn("ENABLE_UKI=no", (self.root / "etc/default/limine").read_text())

    def test_deferred_user_flow_stops_before_disk_cleanup(self):
        self.ctx.defer_provisioning = True
        with mock.patch.object(phases, "_is_surface_laptop8", return_value=True), mock.patch.object(phases.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "creating the user"):
                phases.prepare_live(self.ctx)
        run.assert_not_called()

    def test_missing_firmware_stops_system_configuration(self):
        data = self.root / surface_laptop8.DATA
        data.mkdir(parents=True)
        (data / "hyprland.lua").touch()
        with self.assertRaisesRegex(RuntimeError, "firmware missing"):
            surface_laptop8.configure_system(self.ctx)
        self.assertFalse((self.root / "etc/systemd/system").exists())

    def test_user_overrides_are_repeatable_and_keep_personal_config(self):
        data = self.root / surface_laptop8.DATA
        data.mkdir(parents=True)
        for name, text in {"hyprland.lua": "-- display settings\n", "monitors.lua": "-- menu-controlled panel scale\n", "uwsm-env": "export GALLIUM_DRIVER=llvmpipe\n", "console-login.sh": "# guarded console startup\n"}.items():
            (data / name).write_text(text)
        home = self.root / "home/jim"
        hypr = home / ".config/hypr/hyprland.lua"
        hypr.parent.mkdir(parents=True)
        bootstrap = 'dofile((os.getenv("OMARCHY_PATH") or "/usr/share/omarchy") .. "/default/hypr/bootstrap.lua")'
        original = '-- personal settings\n' + bootstrap + '\nrequire("default.hypr.omarchy")\n'
        hypr.write_text(original)
        with mock.patch.object(surface_laptop8.subprocess, "run"):
            surface_laptop8.configure_user(self.ctx)
            first = {p.relative_to(home): p.read_bytes() for p in home.rglob("*") if p.is_file()}
            surface_laptop8.configure_user(self.ctx)
            second = {p.relative_to(home): p.read_bytes() for p in home.rglob("*") if p.is_file()}
        self.assertEqual(first, second)
        self.assertEqual((home / ".config/hypr/monitors.lua").read_bytes(), (data / "monitors.lua").read_bytes())
        self.assertIn("-- personal settings", hypr.read_text())
        self.assertLess(hypr.read_text().index(bootstrap), hypr.read_text().index("package.loaded"))
        self.assertLess(hypr.read_text().index("package.loaded"), hypr.read_text().index('require("default.hypr.omarchy")'))
        # Repair the previous candidate too: its bootstrap erased the guard,
        # so both the stock and Surface startup paths launched the bar.
        old_prelude = '-- Surface bring-up: validated startup excludes monitor/power automation.\npackage.loaded["default.hypr.autostart"] = true\n'
        hypr.write_text(old_prelude + original)
        with mock.patch.object(surface_laptop8.subprocess, "run"):
            surface_laptop8.configure_user(self.ctx)
        self.assertEqual(hypr.read_bytes(), first[Path(".config/hypr/hyprland.lua")])

    def test_console_autologin_requires_encryption_and_an_existing_owner(self):
        dropin = self.root / "etc/systemd/system/getty@tty1.service.d/autologin.conf"
        for encrypted, deferred in [(True, False), (False, False), (True, True)]:
            with self.subTest(encrypted=encrypted, deferred=deferred):
                dropin.parent.mkdir(parents=True, exist_ok=True)
                dropin.write_text("stale autologin setting\n")
                self.ctx.encrypt = encrypted
                self.ctx.defer_provisioning = deferred
                surface_laptop8.configure_console_login(self.ctx)
                if encrypted and not deferred:
                    self.assertIn("--autologin jim", dropin.read_text())
                    self.assertIn("ExecStart=\nExecStart=", dropin.read_text())
                else:
                    self.assertFalse(dropin.exists())
        self.assertFalse((self.root / "etc/systemd/system/getty@tty2.service.d").exists())

    def test_console_autologin_rejects_root_and_unit_file_injection(self):
        self.ctx.encrypt = True
        for username in ["root", "", "jim\nExecStart=/usr/bin/false", "jim%u"]:
            with self.subTest(username=username):
                self.ctx.username = username
                with self.assertRaisesRegex(RuntimeError, "non-root username"):
                    surface_laptop8.configure_console_login(self.ctx)
                self.assertFalse((self.root / "etc/systemd/system/getty@tty1.service.d").exists())


if __name__ == "__main__":
    unittest.main()
