"""Opt-in Windows desktop shortcut for the dashboard. Nothing is created on install; the user runs
`/agent-scorecard:scorecard shortcut` once."""
import os
import subprocess
import sys
from pathlib import Path

from . import config, icon

LAUNCHER = '''"""Starts the Agent Scorecard dashboard of the currently installed plugin version."""
import runpy
import sys
from pathlib import Path

scripts = Path(Path(__file__).with_name("plugin_root.txt").read_text(encoding="utf-8").strip())
sys.path.insert(0, str(scripts))
sys.argv = [str(scripts / "dashboard.pyw")]
runpy.run_path(sys.argv[0], run_name="__main__")
'''

# Paths travel through environment variables, so no quoting of user paths inside the script
POWERSHELL = r"""
$desktop = if ($env:AS_DESKTOP) { $env:AS_DESKTOP } else { [Environment]::GetFolderPath('Desktop') }
$link = Join-Path $desktop 'Agent Scorecard.lnk'
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($link)
$s.TargetPath = $env:AS_PYTHONW
$s.Arguments = '"' + $env:AS_LAUNCHER + '"'
$s.WorkingDirectory = $env:AS_DATA
$s.IconLocation = $env:AS_ICON
$s.Description = 'Agent Scorecard dashboard'
$s.Save()
Write-Output $link
"""


def create(scripts_dir: Path, desktop: Path | None = None) -> Path:
    """Creates 'Agent Scorecard.lnk' on the desktop (or in `desktop`, used by tests)."""
    if sys.platform != "win32":
        raise OSError("windows_only")
    data = config.data_dir()
    config.remember_plugin_root(scripts_dir)
    launcher = data / "Agent Scorecard.pyw"
    launcher.write_text(LAUNCHER, encoding="utf-8")
    ico = data / "agent-scorecard.ico"
    icon.write_ico(ico)
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    env = {**os.environ, "AS_PYTHONW": str(pythonw if pythonw.exists() else sys.executable),
           "AS_LAUNCHER": str(launcher), "AS_DATA": str(data), "AS_ICON": f"{ico},0",
           "AS_DESKTOP": str(desktop) if desktop else ""}
    # CREATE_NO_WINDOW: otherwise Windows flashes a console window and takes focus from the user's app
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                             "-Command", POWERSHELL], capture_output=True, text=True, env=env, timeout=60,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode != 0:
        raise OSError(result.stderr.strip() or "shortcut_failed")
    return Path(result.stdout.strip().splitlines()[-1])
