# rds-token-gui
<img width="560" height="437" alt="image" src="https://github.com/user-attachments/assets/041656af-4b53-4fb4-bcf6-f2ed88687cc8" />


A small cross-platform (Windows / macOS / Linux) Tkinter desktop app that
generates **RDS IAM database authentication tokens** without hand-typing
`aws rds generate-db-auth-token`.

Workflow:

1. Paste the temporary credentials copied from the AWS access portal.
2. Pick a region (defaults to `ca-central-1`).
3. Click **Load databases** to discover RDS instances and Aurora clusters in
   the account.
4. Pick a database, enter the IAM DB username, and generate the token — copied
   to the clipboard or shown in a dialog.

The token is the boto3 equivalent of:

```
aws --region <region> rds generate-db-auth-token \
    --hostname <db-endpoint> --port <db-port> --username <iam-db-username>
```

## Requirements

- Python 3.9+
- `boto3` (installed automatically)
- **Tkinter** — bundled with the official python.org installers on Windows and
  macOS. On Linux it ships as a separate OS package:

  ```
  sudo apt install python3-tk        # Debian / Ubuntu
  sudo dnf install python3-tkinter   # Fedora / RHEL
  ```

## Install

With [uv](https://docs.astral.sh/uv/):

```
# Install as a persistent tool
uv tool install .

# Or run once without installing
uvx --from . rds-token-gui
```

With pip:

```
pip install .
rds-token-gui
```

## Run from source (development)

```
uv run rds-token-gui
# or
python -m rds_token_gui.app
```

## Usage notes

- The credential box accepts the bash (`export X="..."`), PowerShell
  (`$env:X="..."`) and cmd (`set X=...`) formats — paste whichever block the
  access portal gives you.
- Auth tokens are valid for roughly 15 minutes.
- When copying to the clipboard on Linux/X11, paste the token before closing
  the app — the clipboard is owned by the running process there.
- Credentials are only held in memory for the session and never written to
  disk.
