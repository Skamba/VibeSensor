"""Updater subsystem package.

``manager.py`` remains the public entry point (facade), while focused
modules own each concern:

Module topology
---------------
- **Facade**: ``manager.py`` — public ``UpdateManager`` API for routes and
  runtime lifecycle.  Update workflow orchestration is inlined in
  ``_run_update_inner()``.
- **Validation**: ``validation.py`` — runtime prerequisite checks for tools,
  privileges, rollback storage, and disk space before update orchestration.
- **Services**: ``manager.py`` — backend restart scheduling and runtime update
  lifecycle orchestration.
- **Operations**: ``installer.py`` (install/rollback), ``wifi.py`` (Wi-Fi
  connect/restore, diagnostics, network constants), ``releases.py``
  (GitHub release discovery), ``runner.py`` (process execution and
  command helpers), ``firmware_release_fetcher.py`` (GitHub firmware HTTP
  discovery/download), ``firmware_bundle.py`` (firmware bundle filesystem
  validation/extraction/metadata), ``firmware_types.py`` (firmware cache
  and release payload types), ``firmware_cache.py`` (thin public cache
  facade plus CLI entry points), ``esp_flash_manager.py`` (ESP flash
  orchestration), ``esp_flash_types.py`` (ESP flash contracts/state), and
  ``esp_serial.py`` / ``esp_flash_runner.py`` (serial discovery and flash
  process execution helpers).
- **State**: ``status.py`` (progress tracking, persistent state store,
  and runtime detail collection), ``models.py`` (data models).
"""
