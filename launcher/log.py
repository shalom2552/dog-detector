"""LogManager: stream docker-compose logs into the Tk text widget (thread-safe)."""

import subprocess
import threading
from paths import NO_WINDOW, REPO_DIR


def _clean_line(line):
    """Strip the docker-compose service prefix from a log line."""
    parts = line.split("|", 1)
    is_prefix = len(parts) > 1 and "dog-detector" in parts[0]
    return parts[1].strip() if is_prefix else line.strip()


class LogManager:
    """Manage the docker-compose log-streaming subprocess and GUI display."""

    def __init__(self, app, log_text_widget):
        self.app = app
        self.log_text = log_text_widget
        self.thread = None
        self.proc = None
        self._stopping = False

    def append(self, line):
        """Append a log line to the widget, capping the buffer at 600 lines."""
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        if int(self.log_text.index("end-1c").split(".")[0]) > 600:
            self.log_text.delete("1.0", "200.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def clear(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def start_stream(self):
        """Start a background thread reading `docker compose logs -f`."""
        if self.thread and self.thread.is_alive():
            return
        self._stopping = False

        def job():
            args = ["docker", "compose", "logs", "-f", "--tail=200"]
            try:
                # encoding is required: app logs contain UTF-8 emoji (🐶 🟢 🔴).
                # Without it Windows decodes as cp1252 and the reader thread dies.
                self.proc = subprocess.Popen(
                    args, cwd=REPO_DIR, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                    errors="replace", bufsize=1, creationflags=NO_WINDOW)
            except Exception as e:
                self.app.after(0, self.append, f"Error starting logs: {e}")
                return

            try:
                for line in self.proc.stdout:
                    clean = _clean_line(line)
                    if clean:
                        self.app.after(0, self.append, clean)
            except Exception as e:  # a daemon thread must never fail invisibly
                self.app.after(0, self.append, f"[log stream error: {e}]")
            finally:
                self.proc = None

            if not self._stopping:
                self.app.after(0, self.append, "[log stream ended — retrying]")

        self.thread = threading.Thread(target=job, daemon=True)
        self.thread.start()

    def stop_stream(self):
        """Terminate the log-streaming subprocess."""
        self._stopping = True
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=1)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None
