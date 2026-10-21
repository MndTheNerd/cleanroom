---
description: Show or install the optional add-ons (JPlag + Java, ScanCode Toolkit) chosen when the plugin was enabled.
argument-hint: "[status | install jplag | install scancode [path-to-zip-or-whl] | install all]"
---

Add-ons live in `${CLAUDE_PLUGIN_DATA}/tools`. Your install-time choices: JPlag = `${user_config.install_jplag}`,
ScanCode = `${user_config.install_scancode}`, ScanCode offline source = `${user_config.scancode_source}`.
To change them, open `/plugin`, select cleanroom, and edit its options. They are also shown in `/config`.

- `status` (default): `python "${CLAUDE_PLUGIN_ROOT}/scripts/install_tools.py" --dest "${CLAUDE_PLUGIN_DATA}/tools" --status`
  If an install is running, show the last lines of `${CLAUDE_PLUGIN_DATA}/tools/install.log`.
- `install jplag`: `install_tools.py --dest "${CLAUDE_PLUGIN_DATA}/tools" --jplag`
- `install scancode [path]`: `install_tools.py --dest "${CLAUDE_PLUGIN_DATA}/tools" --scancode [--scancode-source "<path>"]`
- `install all`: both flags.

Run installs in the background (they download ~150 MB each) and tell the user when they finish.

What each add-on is needed for:
- **JPlag**: `/cleanroom:verify` requires two independent similarity checks. Without JPlag, verify FAILS unless config
  `jplag_jar` and `java` point at your own copies.
- **ScanCode**: the final license scan in `/cleanroom:swap` FAILS without it, unless config `scancode` points at your own install.
- **Docker** is not an add-on the plugin can install (it needs admin rights, and WSL2 on Windows). If
  `status` shows `"docker": false`, tell the user to install Docker Desktop or Docker Engine. The build stage refuses to run without it.
