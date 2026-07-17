# liteVDM

A lightweight virtual desktop manager for Windows 10 and Windows 11.

VDM provides a small, always-on-top strip of live desktop previews. Use it to switch desktops, move windows between them, create or close desktops, and restore apps saved for each desktop.

## Features

- Live preview pane for each Windows virtual desktop
- One-click desktop switching
- Context menus for moving one window or every window from another desktop
- Double-click restore for apps previously open on a desktop
- Middle-click desktop removal and a button for creating desktops
- Automatic local session snapshots

## Requirements

- Windows 10 or Windows 11
- Python 3.10 or newer

## Install and run

```powershell
py -3.10 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python vdm.py
```

Alternatively, after installing the dependencies, run `vdm.cmd`.

## Controls

| Input | Action |
| --- | --- |
| Left-click a preview | Switch to that desktop |
| Double-click a preview | Restore its saved apps |
| Right-click a preview | Move windows to it or close it |
| Middle-click a preview | Close that desktop |
| Drag the strip | Move the manager |
| Click `+` | Create a desktop |

## Local data and privacy

VDM writes `sessions.json` beside the script. It contains full executable paths for apps saved on each desktop, so it is intentionally ignored by Git. Delete the file at any time to clear saved sessions; VDM will recreate it when needed.

No telemetry or network service is used.

## Security

VDM launches only executable paths recorded from the current user's open
windows, and only when the user double-clicks a desktop preview to restore its
saved apps. Treat `sessions.json` as private local data and do not share it.

Please report suspected vulnerabilities privately as described in
[`SECURITY.md`](SECURITY.md).

## License

MIT. See [`LICENSE`](LICENSE).
