# Contributing Guide

Thank you for considering contributing to Firmware Toolkit bY yak.

## Quick Start
1. Fork the repository
2. Create a virtualenv (Python 3.10+)
3. Install dependencies: `pip install -r requirements.txt`
4. Run the GUI: `./run-gui.sh`

## Code Style
- Keep changes focused; avoid unrelated reformatting of the 2000+ line `app.py` unless performing a targeted refactor.
- Prefer small helper functions over adding more monolithic blocks.
- For shell scripts:
  - `set -euo pipefail` at top
  - Lowercase helper function names
  - Use long options where practical

## Adding Features
1. Open an issue describing the enhancement / use-case.
2. Include security implications (firmware modification can brick devices).
3. Provide test scenario (sample firmware layout or synthetic binary offsets).

## Internationalization (i18n)
- Add new keys to `_STRINGS` dict in `app.py`
- Use `_('key_name')` everywhere for user-facing text.

## Consent / Safety
- Any feature that writes / patches binary images must check `self.require('patch', 'need_consent_patch')`.
- External tool invocation must guard with `'external'` if expanded.

## Desktop Integration
- Keep `.desktop` file minimal; icon name must remain `firmware_toolkit_yak`.

## Versioning
- Update `VERSION` (semantic versioning) when:
  - Patch: bug fixes only
  - Minor: new features, backwards compatible
  - Major: breaking changes / workflow changes

## Submitting a PR
1. Rebase on latest `main`
2. Run a lint (optional): `ruff check .` if installed
3. Provide before/after screenshots if GUI changes
4. Reference related issues

## Security
- Do not include vendor proprietary blobs.
- If discovering a vulnerability in shipped scripts or parsing logic, email the maintainer before public disclosure (if sensitive).

## License
By contributing you agree your code is released under the MIT License of this project.

Happy hacking!
