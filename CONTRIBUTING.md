# Contributing

Issues and pull requests are welcome.

## Guidelines

- Keep plugins small, readable, and self-contained.
- Prefer built-in macOS tools when they are reliable enough.
- Keep SwiftBar output responsive. Avoid expensive calls in `refreshOnOpen` paths.
- Do not check in local machine state, vendored binaries, or generated cache files.
- If a plugin depends on a third-party tool, document installation and trust implications in `README.md`.

## Development

- Make scripts executable with `chmod +x`.
- Validate plugins by running them directly before testing them in SwiftBar.
- For Python plugins, avoid generating `__pycache__` entries inside `plugins/`.
