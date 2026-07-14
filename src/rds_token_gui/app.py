"""Tkinter GUI for generating RDS IAM database authentication tokens.

Paste temporary credentials copied from the AWS access portal, pick a region
and an RDS endpoint discovered from the account, enter the IAM DB username, and
get a signed auth token either on the clipboard or in a dialog.
"""

from __future__ import annotations

import re
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

# Matches the three credential variables in bash (`export X="v"`),
# PowerShell (`$env:X="v"`) and cmd (`set X=v`) formats, quoted or not.
_CRED_RE = re.compile(
    r"(AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN)"
    r"\s*=\s*\"?([^\"\s]+)\"?"
)

_REQUIRED_KEYS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")

# Common regions offered in the editable combobox; user can type any other.
_REGIONS = [
    "ca-central-1",
    "us-east-1",
    "us-east-2",
    "us-west-1",
    "us-west-2",
    "eu-west-1",
    "eu-west-2",
    "eu-central-1",
    "ap-southeast-1",
    "ap-southeast-2",
    "ap-northeast-1",
]

_DEFAULT_REGION = "ca-central-1"


def parse_credentials(text: str) -> dict[str, str]:
    """Extract AWS credential variables from a pasted access-portal block."""
    return {key: value for key, value in _CRED_RE.findall(text)}


def discover_databases(session: boto3.session.Session) -> dict[str, tuple[str, int]]:
    """Return a mapping of display string -> (hostname, port).

    Combines standalone RDS instances and Aurora cluster writer endpoints.
    """
    rds = session.client("rds")
    results: dict[str, tuple[str, int]] = {}

    # Standalone instance endpoints.
    for page in rds.get_paginator("describe_db_instances").paginate():
        for db in page.get("DBInstances", []):
            endpoint = db.get("Endpoint")
            if not endpoint:  # instance still being created has no endpoint yet
                continue
            address = endpoint.get("Address")
            port = endpoint.get("Port")
            if not address or port is None:
                continue
            identifier = db.get("DBInstanceIdentifier", "?")
            engine = db.get("Engine", "?")
            label = f"{identifier}  ({engine})  {address}:{port}"
            results[label] = (address, int(port))

    # Aurora cluster writer endpoints.
    for page in rds.get_paginator("describe_db_clusters").paginate():
        for cluster in page.get("DBClusters", []):
            address = cluster.get("Endpoint")
            port = cluster.get("Port")
            if not address or port is None:
                continue
            identifier = cluster.get("DBClusterIdentifier", "?")
            engine = cluster.get("Engine", "?")
            label = f"{identifier}  ({engine} cluster)  {address}:{port}"
            results[label] = (address, int(port))

    return results


class RdsTokenApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.databases: dict[str, tuple[str, int]] = {}
        self._busy = False

        root.title("RDS IAM Auth Token Generator")
        root.minsize(560, 0)

        frame = ttk.Frame(root, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        row = 0

        # 1. Credentials paste box.
        ttk.Label(
            frame, text="Paste credentials from AWS access portal:"
        ).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        self.creds_text = tk.Text(frame, height=6, width=64, wrap="none")
        self.creds_text.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(2, 8))
        row += 1

        # 2. Region.
        ttk.Label(frame, text="Region:").grid(row=row, column=0, sticky="w")
        self.region_var = tk.StringVar(value=_DEFAULT_REGION)
        self.region_combo = ttk.Combobox(
            frame, textvariable=self.region_var, values=_REGIONS
        )
        self.region_combo.grid(row=row, column=1, sticky="ew", pady=2)
        row += 1

        # 3. DB username.
        ttk.Label(frame, text="IAM DB username:").grid(row=row, column=0, sticky="w")
        self.username_var = tk.StringVar()
        self.username_entry = ttk.Entry(frame, textvariable=self.username_var)
        self.username_entry.grid(row=row, column=1, sticky="ew", pady=2)
        row += 1

        # 4. Clipboard checkbox (default checked).
        self.clipboard_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frame, text="Copy token to clipboard", variable=self.clipboard_var
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 4))
        row += 1

        # 5. Load databases button.
        self.load_button = ttk.Button(
            frame, text="Load databases", command=self.on_load_databases
        )
        self.load_button.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(4, 8))
        row += 1

        # 6. Database dropdown.
        ttk.Label(frame, text="Database:").grid(row=row, column=0, sticky="w")
        self.db_var = tk.StringVar()
        self.db_combo = ttk.Combobox(
            frame, textvariable=self.db_var, state="readonly", values=[]
        )
        self.db_combo.grid(row=row, column=1, sticky="ew", pady=2)
        self.db_combo.bind("<<ComboboxSelected>>", lambda _e: self._sync_generate_state())
        row += 1

        # 7. Generate token button.
        self.generate_button = ttk.Button(
            frame,
            text="Generate token",
            command=self.on_generate_token,
            state="disabled",
        )
        self.generate_button.grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=(8, 4)
        )
        row += 1

        # Status label.
        self.status_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.status_var, foreground="#0a6").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )

    # -- helpers ---------------------------------------------------------

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.load_button.configure(state=state)
        self._sync_generate_state()

    def _sync_generate_state(self) -> None:
        can_generate = (
            not self._busy and bool(self.db_var.get()) and bool(self.databases)
        )
        self.generate_button.configure(
            state="normal" if can_generate else "disabled"
        )

    def _get_credentials_or_warn(self) -> dict[str, str] | None:
        creds = parse_credentials(self.creds_text.get("1.0", "end"))
        missing = [key for key in _REQUIRED_KEYS if key not in creds]
        if missing:
            messagebox.showerror(
                "Missing credentials",
                "Could not find the following in the pasted text:\n\n"
                + "\n".join(missing),
            )
            return None
        return creds

    def _build_session(self, creds: dict[str, str], region: str) -> boto3.session.Session:
        return boto3.session.Session(
            aws_access_key_id=creds["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=creds["AWS_SECRET_ACCESS_KEY"],
            aws_session_token=creds["AWS_SESSION_TOKEN"],
            region_name=region,
        )

    # -- load databases --------------------------------------------------

    def on_load_databases(self) -> None:
        creds = self._get_credentials_or_warn()
        if creds is None:
            return
        region = self.region_var.get().strip() or _DEFAULT_REGION

        self.status_var.set("Loading databases…")
        self._set_busy(True)

        def worker() -> None:
            try:
                session = self._build_session(creds, region)
                databases = discover_databases(session)
            except (ClientError, BotoCoreError, NoCredentialsError) as exc:
                self.root.after(0, self._on_load_error, exc)
            except Exception as exc:  # pragma: no cover - unexpected
                self.root.after(0, self._on_load_error, exc)
            else:
                self.root.after(0, self._on_load_success, databases)

        threading.Thread(target=worker, daemon=True).start()

    def _on_load_success(self, databases: dict[str, tuple[str, int]]) -> None:
        self._set_busy(False)
        self.databases = databases
        labels = sorted(databases)
        self.db_combo.configure(values=labels)
        if labels:
            self.db_var.set(labels[0])
            self.status_var.set(f"Found {len(labels)} database(s).")
        else:
            self.db_var.set("")
            self.status_var.set("No RDS databases found in this region.")
        self._sync_generate_state()

    def _on_load_error(self, exc: Exception) -> None:
        self._set_busy(False)
        self.status_var.set("")
        messagebox.showerror("Failed to load databases", _format_error(exc))

    # -- generate token --------------------------------------------------

    def on_generate_token(self) -> None:
        creds = self._get_credentials_or_warn()
        if creds is None:
            return
        username = self.username_var.get().strip()
        if not username:
            messagebox.showerror(
                "Missing username", "Enter the IAM DB username first."
            )
            return
        label = self.db_var.get()
        if label not in self.databases:
            messagebox.showerror("No database", "Select a database first.")
            return

        hostname, port = self.databases[label]
        region = self.region_var.get().strip() or _DEFAULT_REGION

        try:
            session = self._build_session(creds, region)
            token = session.client("rds").generate_db_auth_token(
                DBHostname=hostname,
                Port=port,
                DBUsername=username,
                Region=region,
            )
        except (ClientError, BotoCoreError, NoCredentialsError) as exc:
            messagebox.showerror("Failed to generate token", _format_error(exc))
            return
        except Exception as exc:  # pragma: no cover - unexpected
            messagebox.showerror("Failed to generate token", _format_error(exc))
            return

        if self.clipboard_var.get():
            self.root.clipboard_clear()
            self.root.clipboard_append(token)
            self.status_var.set(
                "Token copied to clipboard (valid ~15 min). "
                "Paste it before closing this window."
            )
        else:
            self._show_token_popup(token)

    def _show_token_popup(self, token: str) -> None:
        popup = tk.Toplevel(self.root)
        popup.title("RDS auth token")
        popup.transient(self.root)

        container = ttk.Frame(popup, padding=12)
        container.grid(row=0, column=0, sticky="nsew")
        popup.columnconfigure(0, weight=1)
        popup.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)

        ttk.Label(
            container, text="Auth token (valid ~15 min) — select and copy:"
        ).grid(row=0, column=0, sticky="w")

        text = tk.Text(container, height=8, width=72, wrap="char")
        text.grid(row=1, column=0, sticky="nsew", pady=(4, 8))
        text.insert("1.0", token)
        text.configure(state="disabled")

        ttk.Button(container, text="Close", command=popup.destroy).grid(
            row=2, column=0, sticky="e"
        )
        self.status_var.set("Token generated.")


def _format_error(exc: Exception) -> str:
    if isinstance(exc, ClientError):
        error = exc.response.get("Error", {})
        code = error.get("Code", "ClientError")
        message = error.get("Message", str(exc))
        return f"{code}: {message}"
    return str(exc)


def main() -> None:
    root = tk.Tk()
    RdsTokenApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
