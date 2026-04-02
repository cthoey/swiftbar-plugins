# SwiftBar Plugins

SwiftBar plugins for machine and workflow status items on macOS.

## Requirements

- macOS
- [SwiftBar](https://github.com/swiftbar/SwiftBar)
- Apple Container CLI for `apple-container.15s.py`
- Apple Silicon plus `iSMC` for the temperature monitor

## Included

- `plugins/disk-space.1m.sh`: APFS-aware disk space monitor for the internal drive plus mounted local volumes, with low-space alerts in the dropdown.
- `plugins/temperature.15s.py`: Apple Silicon temperature monitor backed by `iSMC`, with CPU, GPU, battery, and hottest-sensor details in the dropdown.
- `plugins/apple-container.15s.py`: Apple Container overview with system, start/stop/restart, prune, logs, and per-container lifecycle actions.
- `plugins/cpu-memory.5s.sh`: live CPU and memory monitor for macOS with top CPU and RAM processes in the dropdown, including friendly labels for Codex autonomous supervisors and workers.
- `plugins/codex-runner.15s.py`: Continuum monitor for [Continuum for Codex](https://github.com/cthoey/continuum-codex), with top-bar worker counts, per-project status, low-overhead timing signals, recent log context, and quick start/restart/stop/log actions.

## Setup

1. Clone this repo anywhere on your Mac.

```bash
git clone <your-repo-url>
cd swiftbar-plugins
```

2. Install SwiftBar on macOS.

```bash
brew install --cask swiftbar
```

3. Launch SwiftBar and set the plugin folder to this repo's `plugins/` directory.

```text
/path/to/swiftbar-plugins/plugins
```

4. Make sure the plugin files are executable.

```bash
chmod +x plugins/*
```

5. Install the Apple Silicon temperature helper if you want the temperature plugin to use the vendored `iSMC` path.

```bash
./scripts/install-ismc.sh
```

## Repository Layout

```text
plugins/
  apple-container.15s.py
  codex-runner.15s.py
  cpu-memory.5s.sh
  disk-space.1m.sh
  temperature.15s.py
scripts/
  install-ismc.sh
vendor/
  ismc/
    README.md
```

## Notes

- SwiftBar plugin filenames follow `{name}.{interval}.{ext}`, so `cpu-memory.5s.sh` refreshes every 5 seconds.
- `plugins/codex-runner.15s.py` is a monitor for [Continuum for Codex](https://github.com/cthoey/continuum-codex).
- It reads runner state from `CONTINUUM_RUNNER_ROOT` first, then from `~/.config/continuum/config.toml`, then falls back to `RELAY_RUNNER_ROOT` and `CODEX_RUNNER_ROOT` for compatibility. If none are set, it defaults to `~/continuum-runner`.
- The plugin reads `projects.json`, per-project `status.json`, `codex.log`, `docs/codex-progress.md`, and lightweight restart marker files from the configured Continuum runner root.
- `Start project`, `Restart project`, `Stop after pass`, and `Stop now` are thin wrappers around the Continuum runner scripts `launch_project.sh`, `restart_project.sh`, `stop_project.sh`, and `stop_now_project.sh`. Those scripts carry the actual detached/service-aware behavior.
- The Continuum top bar shows how many autonomous workers are actively running and appends short
  summaries such as `1 restart pending`, `2 restarts pending`, stale, waiting, blocked, or failed
  counts when relevant.
- In each project dropdown, the plugin shows low-overhead time signals derived from existing files:
  supervisor start and age from the supervisor pidfile, current pass start and age from
  `status.json`, last worker activity from `codex.log` mtime, and last progress checkpoint from
  `docs/codex-progress.md` mtime when that file exists. Every timestamp is shown in local time with
  a human-readable relative age such as `6s ago` or `3m ago`.
- Each project dropdown also exposes direct actions for `Tail codex.log`, `Tail supervisor log`,
  `Open project folder`, `Open runner folder`, `Open status.json`, `Open codex.log`, `Open restart state`,
  and `Open codex-progress.md` when those files exist.
- If a graceful restart has been requested but the current pass is still finishing, the Continuum
  dropdown shows a restart-pending line sourced from the runner's lightweight
  `restart.<project>.json` marker file.
- Continuum manages sleep prevention itself in the runner on macOS. SwiftBar inherits that behavior
  automatically because it launches projects through the runner scripts rather than managing power
  state itself.
- The shell plugins use built-in macOS tools such as `df`, `diskutil`, `plutil`, `top`, `ps`, `sort`, `head`, and `uptime`.
- The CPU/memory plugin derives friendly process labels for known Codex runner commands, such as
  `codex-supervisor[MMXDecomp]` and `codex-worker[MMXDecomp]`, so active autonomous jobs are easier
  to identify in the dropdown.
- `scripts/install-ismc.sh` downloads the official `iSMC` release, verifies its checksum, and installs it into `vendor/ismc/iSMC`.
- `plugins/temperature.15s.py` prefers `vendor/ismc/iSMC` and falls back to `iSMC` or `ismc` on `PATH`, so a Homebrew install works too.
- The `iSMC` binary is not checked into the repo. It is installed locally into `vendor/ismc/` by the helper script.
- Third-party tools keep their own licenses and trust model. This repo only contains the wrapper scripts and installer logic.

## Contributing

See `CONTRIBUTING.md`.

## License

MIT. See `LICENSE`.
