# EGL report kiosk

The application runs on a Raspberry Pi with an X11 touchscreen, a serial barcode
reader, and a CUPS printer. `kiosk.ini` defines the display, languages, report host,
printer models, and optional watchdog.

## Install on Raspberry Pi 4 or 5

Copy or unpack this package on the target Raspberry Pi, then run from its folder:

```sh
bash install.sh --check
sudo bash install.sh
sudo reboot
```

Use Raspberry Pi OS Lite with `raspi-config` installed; 64-bit Bookworm is the
recommended baseline for this package. Installation needs Internet access for
APT and Python dependencies, and an existing local user account. By default the
kiosk runs as the user who invoked `sudo`, or `pi` when launched directly as root.
To choose another existing account:

```sh
sudo KIOSK_USER=kioskuser bash install.sh
```

`--check` only validates the board, account and boot files; it changes nothing.
The installer detects Raspberry Pi 4 Model B and Raspberry Pi 5 Model B, copies
the application to `/opt/kiosk`, installs packages, creates a local Python
environment and registers the boot services. It excludes the source `.venv`,
review backups, bytecode and old image caches. On repeat installs, the target's
`kiosk.ini` and log are retained. Provisioning rebuilds `.venv` and installs
dependencies from `requirements.txt` so an in-place copy cannot keep binaries
from a different CPU architecture or Python version. Use the installer with a
source copy when moving the package to another Pi.

Boot files are detected as a pair in `/boot/firmware` or `/boot`. Display setup
keeps `vc4-kms-v3d` and the existing `vc4-kms-dsi-7inch` panel overlay, including
its parameters, and respects `[pi4]`/`[pi5]` sections when checking for missing
settings. Boot edits retain backups. The firmware's conditional sections and
panel requirements are documented in the [Raspberry Pi config reference](https://www.raspberrypi.com/documentation/computers/config_txt.html)
and [overlay reference](https://github.com/raspberrypi/firmware/blob/master/boot/overlays/README).

This provisions the current 800×480 DSI panel rotated to portrait, USB serial
scanner and CUPS printer setup. A different panel needs its own display
configuration. Use a Lite image so a desktop display manager does not compete
with the kiosk's X server. Edit `/opt/kiosk/kiosk.ini` for the target's report
host, printer and working hours before rebooting.

Connect Ethernet with DHCP before the first reboot. First-boot setup configures
the hostname (`rapi4-kiosk9DSI-…` or `rapi5-kiosk9DSI-…`), retains the existing
network/time settings, enables the kiosk and requests a second reboot. It retries
on a later boot if Ethernet has no usable IPv4 address. The existing daily reboot
schedule remains 10:02 Europe/Riga.

Pi 4/5 model fixtures, both boot layouts, conditional display settings and source
copying are covered by offline regression tests. Physical Pi 4 installation,
touch alignment, audio and printing still require validation on the target.

## Running

Use the existing virtual environment:

```sh
/opt/kiosk/.venv/bin/python /opt/kiosk/kiosk_main.py -c /opt/kiosk/kiosk.ini
```

This requires a running X server. `/opt/kiosk/st.sh` starts X and the application;
`start_kiosk.sh` runs the application within an existing X session.
`start_tk.sh` delegates to that launcher. `gui_simm.py` runs the actual hardware
worker with console output instead of a GUI. It is not a hardware simulation.

For the installed systemd service:

```sh
sudo systemctl start kiosk.service
journalctl -u kiosk.service -f
```

At boot, `kiosk-clear-print-jobs.service` removes previous print jobs from every
queue before CUPS, its socket, or its path activation can start. Printer
definitions remain installed. New test pages submitted after cleanup are
preserved across later kiosk and CUPS restarts. The startup printer-reset button
explicitly deletes all CUPS printer definitions when pressed. Set `button_printer_reset =` in `[REPORT]` to disable that reset option.
The configured value `1` selects the second language button.

`--config` is respected. Relative asset and log paths resolve against the
configuration file's directory. The legacy spelling `bc_reader_boudrate` is
preserved for compatibility. Working hours use `HH:MM`; weekdays use 0–6, with
Monday as 0. An overnight shift's early hours belong to the preceding workday.

## Setup scripts

`install.sh` copies and provisions a source package; `preppi.sh` installs packages
and configures an existing `/opt/kiosk` copy. `initkio.sh` performs first-boot setup
and requests a reboot. Run these deliberately as root when provisioning a kiosk.

Boot-config wrappers accept fixture paths as well as real boot files:

```sh
./update_config_txt.sh /path/to/config.txt
./update_cmdline.sh /path/to/cmdline.txt
```

The legacy `update_config.sh` replaces the KMS overlay and updates the command
line beside the given config file. `CMDLINE_FILE` can override its command-line
destination; `update_cmdline.sh` detects the boot directory when no path is given.
All three use
`kiosk_boot_config.py`, retain backups of changed files, preserve file metadata,
and avoid duplicate settings on repeat runs. Other display outputs' `video=`
settings are preserved.

`wait-for-ethernet.sh` leaves link negotiation automatic and limits its total
wait to 180 seconds by default. `eth-speed.service` invokes the alternative
`check-ethernet.sh`, which tries negotiation first and then a 10 Mbps fallback.
`10eth-speed.service` is the original legacy forced-speed alternative. These are
separate provisioning choices; do not enable conflicting Ethernet setup units.

## Review completed 2026-10-02

All 22 original application scripts (9 Python and 13 shell) and 5 service units
were examined. There were no application scripts in `assets/`. Installed
third-party source and generated launchers inside `.venv` were left intact;
`pip check` reported no broken requirements. A shared boot-editing helper,
dependency manifest, and regression checks were added.

Changes include:

- Consistent report-download results for timeouts, connection failures, non-PDF
  responses, and errors writing temporary files. Temporary reports are removed
  after successful or failed processing. PDF and audio subprocesses use argument
  lists rather than interpolated shell commands.
- Complete barcode validation, URL encoding, monotonic debounce, invalid-byte
  handling, and reconnection after scanner disconnection. Production barcode
  values and report access URLs are no longer logged by these scripts.
- Correct printer-install failure handling and default-printer selection. Normal
  startup preserves unrelated printer definitions and completes printer installation without an unsolicited test page or reboot.
- Correct delayed language-button enablement, language selection when waking the
  display, popup icon reuse, animation-cycle reset and timer cancellation,
  explicit ticket duration, and nonfatal unsupported backlight/DPMS operations.
- Configuration validation, corrected defaults, `--config` handling, config-relative
  paths, and actual file logging when requested.
- Stoppable worker retries, scanner closure, watchdog closure, SIGTERM handling,
  and process exit if the worker unexpectedly dies so systemd can restart it.
- Setup fixes for a malformed package name, working-directory assumptions,
  omitted dependencies, unsafe predictable temporary files, duplicate hosts/cron
  entries, early disabling of first-boot setup, and indefinite boot blocking.
  Provisioning now uses its virtual environment without altering global pip
  policy or automatically enabling remote CUPS administration.
- GIFs are loaded from their source images into an in-memory cache. Legacy
  `.pkl` files are retained but ignored; cache files cannot execute code and
  image changes or new dimensions apply at the next launch. Decoding all eight
  current GIFs takes about 9 seconds on this Pi at the configured 290×290 size.

Original files are in `.review-backups/20261002-135003/`, with SHA-256 hashes in
`manifest.json`. `review.patch` contains the complete difference from that
snapshot, including newly added files. There is no Git repository here.

The installed service files for kiosk, firstboot, and Ethernet waiting were
hard-linked to their copies here, so their edits also updated the installed
files. Systemd definitions were reloaded without starting or enabling a service.
At the end of the initial review, the kiosk was disabled and stopped, and CUPS
was active. Live boot settings, network connections, and printer queues were not
changed during that initial validation. The follow-up boot cleanup below was
subsequently installed and verified.

## Print-job cleanup on boot

The installed `kiosk-clear-print-jobs.service` runs once per boot before all three
CUPS activation paths (`cups.service`, `cups.socket`, and `cups.path`). Their
installed drop-ins require successful cleanup before starting CUPS. This also
works when the kiosk GUI is disabled. `RemainAfterExit=yes` prevents a later
CUPS restart from clearing newly queued jobs or test pages again.

`kiosk_clear_print_jobs.py` reads `RequestRoot` and `CacheDir` from
`/etc/cups/cups-files.conf`. While CUPS is stopped, it removes old job control and
document files from all printer queues, including interrupted-write recovery
files. It empties the job caches while retaining the next job ID and file
metadata. Printer definitions, PPDs, and printer caches are preserved. Old stored
job records are cleared along with the spool, including old test-page jobs;
needed test pages should be submitted after boot cleanup. Ordinary printer
initialization no longer cancels those new jobs.

CUPS loads jobs from both its spool and cache; the cleanup handles both, as shown
in the [upstream CUPS job loader](https://github.com/OpenPrinting/cups/blob/master/scheduler/job.c).
The cleaner refuses to modify a live scheduler's spool. A read-only inspection is:

```sh
sudo /usr/bin/python3 /opt/kiosk/kiosk_clear_print_jobs.py --dry-run
journalctl -u kiosk-clear-print-jobs.service
```

The boot rule and all three drop-ins are installed on this computer. After
confirming no pending jobs, CUPS was stopped briefly, the boot rule installed,
and CUPS restarted through the new dependencies. Cleanup succeeded, retaining
next job ID 2; all CUPS units returned to active. The computer was not rebooted.
The kiosk GUI was not started by this follow-up change; it is currently running
but remains disabled for automatic startup. `preppi.sh` also installs the same boot rule when
provisioning another computer.

Backups before this follow-up change are in
`.review-backups/print-startup-20261002-142143/`.

## Validation

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q ./*.py tests
shellcheck ./*.sh
systemd-analyze verify ./*.service
.venv/bin/python -m pip check
```

66 regression tests pass, including the Pi 4/5 installer fixtures added on
2026-10-06. Expected error-path tests log errors and warnings.
ShellCheck, Python compilation, systemd validation, module imports, source GIF
loading, and dependency checks pass.

`tests/gui_smoke.py` also passed against a temporary virtual X server. It exercises
real widgets: initial display, selecting a language while waking from power
save, button debounce, popup reuse, changing icons, explicit ticket duration,
and clean shutdown. Hardware calls are mocked and no worker is started.

```sh
DISPLAY=:99 .venv/bin/python tests/gui_smoke.py
```

A virtual X server must already be running at that display. ShellCheck and Xvfb
were extracted into `/tmp/kiosk-review-tools` for validation; no system packages
were installed for the checks. Real touchscreen alignment, audio, host report
access, and physical printing were not exercised. A successful CUPS submission
means the queue accepted a job; it does not prove that paper was printed.
