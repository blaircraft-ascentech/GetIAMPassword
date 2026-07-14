# RDS IAM Auth Token GUI (Tkinter) — Work Plan

## Context

A small cross-platform desktop helper for generating RDS IAM database auth tokens without hand-typing `aws rds generate-db-auth-token` commands. The workflow: paste temporary credentials copied from the AWS access portal, pick a region and an RDS endpoint discovered from the account, enter the IAM DB username, and get the token either on the clipboard or in a dialog.

Requirements:

- Runs on **Windows, macOS, and Linux**.
- Installable with **uv or pip** (packaging files included in the project).
- Local **git repo** now; GitHub remote added later.

## Project layout

```
op-9099/
├── pyproject.toml          # packaging — installable via pip/uv
├── README.md               # install + usage instructions
├── .gitignore              # standard Python ignores
├── plan.md                 # this file
├── TODO.txt                # action checklist
└── src/
    └── rds_token_gui/
        ├── __init__.py
        └── app.py          # the entire Tkinter app + main()
```

- `pyproject.toml`: hatchling build backend, `requires-python = ">=3.9"`, single dependency `boto3`. Entry point under **`[project.gui-scripts]`** (`rds-token-gui = "rds_token_gui.app:main"`) so Windows launches it without a console window; on macOS/Linux it behaves like a normal script.
- Install paths documented in README: `uv tool install .` / `uvx --from . rds-token-gui` / `pip install .`, plus dev run via `uv run rds-token-gui`.
- tkinter is stdlib (bundled with python.org installers on Windows/macOS); README notes Linux needs the distro package (`sudo apt install python3-tk`). The dev box currently lacks it.

## Git

`git init` in the project directory, then one initial commit ("Add RDS IAM auth token GUI") once the files are written and verified. No remote configured yet.

## UI layout (single window, top to bottom)

1. **Credentials** — multiline `tk.Text` box labeled "Paste credentials from AWS access portal". Parser extracts `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` via one regex tolerant of all three portal formats (bash `export X="v"`, PowerShell `$env:X="v"`, cmd `set X=v`), with or without quotes:
   `(AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN)\s*=\s*"?([^"\s]+)"?`
2. **Region** — `ttk.Combobox` prefilled with common regions, editable, default `ca-central-1`.
3. **DB username** — `ttk.Entry` for the RDS IAM database username.
4. **Clipboard checkbox** — `tk.BooleanVar`, "Copy token to clipboard", default checked.
5. **"Load databases" button** — validates that all three credential values parsed (error dialog naming any missing variable if not), builds a boto3 session with the pasted creds + region, then populates:
6. **Database dropdown** — `ttk.Combobox` (readonly) listed from:
   - `rds.describe_db_instances` → instance endpoints (`Endpoint.Address` / `Endpoint.Port`), skipping instances with no endpoint yet (still creating);
   - `rds.describe_db_clusters` → Aurora cluster writer endpoints (`Endpoint` / `Port`).
   Display string: `<identifier>  (<engine>)  <address>:<port>`; a dict maps display string → `(hostname, port)`. Use paginators so accounts with >100 DBs are fully listed.
7. **"Generate token" button** — enabled once a DB is selected.

## Token generation

Boto3 equivalent of the CLI command — no subprocess, no AWS CLI dependency (keeps it cross-platform):

```python
token = rds_client.generate_db_auth_token(
    DBHostname=hostname, Port=port, DBUsername=username, Region=region)
```

- Validates username is non-empty first.
- Checkbox ticked → `root.clipboard_clear(); root.clipboard_append(token)` + status label "Token copied to clipboard (valid 15 min)". Tk's clipboard works on all three OSes with no extra dependency; on Linux/X11 the content is lost if the app closes before pasting, so the status label says to paste before closing.
- Unticked → popup `tk.Toplevel` with the token in a readonly `tk.Text` (selectable/copyable — better than `messagebox`, which can't be copied from) plus a Close button.

## Error handling

- All AWS calls wrapped; `ClientError`/`EndpointConnectionError`/`NoCredentialsError` → `messagebox.showerror` with the AWS error message (e.g. expired portal creds → the ExpiredToken message tells the user to re-paste).
- AWS calls (`describe_*`) run in a `threading.Thread` with results marshalled back via `root.after`, so the UI doesn't freeze on slow networks; buttons disabled while a call is in flight.

## Verification

1. `sudo apt install python3-tk`, then `python3 -c "import tkinter"` passes (needed on the Linux dev box only).
2. `uv run rds-token-gui` (and `pip install .` into a scratch venv to prove the packaging) launches the window.
3. Paste a real credential block from the access portal, keep `ca-central-1`, click **Load databases** — dropdown fills with the account's RDS instances.
4. Select a DB, enter an IAM username, generate with checkbox ticked → paste the clipboard somewhere and confirm it's a signed `<host>:<port>/?Action=connect&DBUser=...&X-Amz-...` token string.
5. Repeat with checkbox unticked → token appears in the popup and is selectable.
6. Negative tests: missing session token in the paste → clear error naming the variable; expired creds → AWS error surfaced in a dialog.
7. `git log` shows the initial commit; `git status` clean.
