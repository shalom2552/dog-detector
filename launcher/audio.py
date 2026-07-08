"""Play the alert sound on the client machine (Windows MCI, else mpg123)."""

import os
import subprocess

from paths import NO_WINDOW, SOUND_PATH


def _mci(cmd):
    """Send one MCI command; return (ok, error_text)."""
    import ctypes
    err = ctypes.windll.winmm.mciSendStringW(cmd, None, 0, None)
    if err == 0:
        return True, ""
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.winmm.mciGetErrorStringW(err, buf, len(buf))
    return False, f"MCI error {err}: {buf.value or 'unknown'} [{cmd}]"


def _short_path(path):
    """8.3 short name — MCI chokes on some long/non-ASCII paths."""
    import ctypes
    buf = ctypes.create_unicode_buffer(260)
    n = ctypes.windll.kernel32.GetShortPathNameW(path, buf, 260)
    return buf.value if 0 < n < 260 else path


def _play_mci(path):
    """Play via winmm MCI; return None on success, else error text."""
    import ctypes
    # mpegvideo is DirectShow-based: without COM initialized on this thread, open
    # fails with MCI error 277 ("problem initializing MCI").
    ctypes.windll.ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
    try:
        ok, err = _mci(f'open "{path}" type mpegvideo alias snd')
        if not ok:
            # mpegvideo rejects some mp3s; a typeless open lets MCI pick the
            # device from the file extension instead.
            ok, err = _mci(f'open "{path}" alias snd')
        if not ok:
            return err
        ok, err = _mci('play snd wait')
        _mci('close snd')
        return None if ok else err
    finally:
        ctypes.windll.ole32.CoUninitialize()


def _play_powershell(path):
    """WPF MediaPlayer via PowerShell; return None on success, else error text."""
    uri = path.replace("'", "''")
    script = (
        "Add-Type -AssemblyName PresentationCore;"
        "$p = New-Object System.Windows.Media.MediaPlayer;"
        f"$p.Open([Uri]::new('{uri}'));"
        "$p.Play();"
        "for ($i = 0; $i -lt 50 -and -not $p.NaturalDuration.HasTimeSpan; $i++)"
        "  { Start-Sleep -Milliseconds 100 };"
        "if (-not $p.NaturalDuration.HasTimeSpan) { exit 1 };"
        "Start-Sleep -Seconds ([int]$p.NaturalDuration.TimeSpan.TotalSeconds + 1);"
        "$p.Close();"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW)
        if r.returncode == 0:
            return None
        return f"powershell exit {r.returncode}: {(r.stderr or '').strip()[:200]}"
    except Exception as e:
        return f"powershell fallback failed: {e!r}"


def play_sound():
    """Play the alert. Return None on success, else a short error message."""
    if not os.path.exists(SOUND_PATH):
        return f"sound file not found: {SOUND_PATH}"
    if os.name == "nt":
        err = _play_mci(_short_path(SOUND_PATH))
        if err is None:
            return None
        ps_err = _play_powershell(SOUND_PATH)
        if ps_err is None:
            return None
        return f"{err}; {ps_err}"
    try:
        subprocess.Popen(["mpg123", "-q", SOUND_PATH])
        return None
    except FileNotFoundError:
        return "mpg123 not installed"
