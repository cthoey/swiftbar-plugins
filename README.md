# SwiftBar Plugins

SwiftBar plugins for machine and workflow status items on macOS.

## Requirements

- macOS
- [SwiftBar](https://github.com/swiftbar/SwiftBar)
- Apple Container CLI for `apple-container.15s.py`
- Apple Silicon plus `iSMC` for the temperature monitor

## Included

- `plugins/temperature.15s.py`: Apple Silicon temperature monitor backed by `iSMC`, with CPU, GPU, battery, and hottest-sensor details in the dropdown.
- `plugins/apple-container.15s.py`: Apple Container overview with system, start/stop/restart, prune, logs, and per-container lifecycle actions.
- `plugins/cpu-memory.5s.sh`: live CPU and memory monitor for macOS with top CPU and RAM processes in the dropdown.

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
  cpu-memory.5s.sh
  temperature.15s.py
scripts/
  install-ismc.sh
vendor/
  ismc/
    README.md
```

## Notes

- SwiftBar plugin filenames follow `{name}.{interval}.{ext}`, so `cpu-memory.5s.sh` refreshes every 5 seconds.
- The plugin uses built-in macOS tools only: `top`, `ps`, `sort`, `head`, and `uptime`.
- `scripts/install-ismc.sh` downloads the official `iSMC` release, verifies its checksum, and installs it into `vendor/ismc/iSMC`.
- `plugins/temperature.15s.py` prefers `vendor/ismc/iSMC` and falls back to `iSMC` or `ismc` on `PATH`, so a Homebrew install works too.
- The `iSMC` binary is not checked into the repo. It is installed locally into `vendor/ismc/` by the helper script.
- Third-party tools keep their own licenses and trust model. This repo only contains the wrapper scripts and installer logic.

## Contributing

See `CONTRIBUTING.md`.

## License

MIT. See `LICENSE`.
