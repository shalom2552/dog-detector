"""Small Tk canvas widgets: the big animated status indicator and the tiny dot."""

import tkinter as tk


class StatusIndicator:
    """Large indicator above the status card. Always animating; visibility toggles only.

    spin()          → spinning amber arc  (working / starting up)
    show_dot(color) → solid filled circle (green=live, red=stopped)
    """
    def __init__(self, parent, bg):
        self.canvas = tk.Canvas(parent, width=80, height=80,
                                bg=bg, highlightthickness=0)
        self._spinning = False
        self._angle    = 0

        self._bg_ring = self.canvas.create_oval(
            10, 10, 70, 70, outline="#8b93a7", width=5, state="hidden")
        self._arc = self.canvas.create_arc(
            10, 10, 70, 70, start=0, extent=80,
            style="arc", outline="#f0b429", width=5, state="hidden")
        self._dot = self.canvas.create_oval(
            25, 25, 55, 55, fill="#e5484d", outline="", state="hidden")

        self._tick()  # always runs — no start/stop needed

    def _tick(self):
        if self._spinning:
            self._angle = (self._angle - 6) % 360
            self.canvas.itemconfigure(self._arc, start=self._angle)
        self.canvas.after(15, self._tick)

    def spin(self):
        self._spinning = True
        self.canvas.itemconfigure(self._dot,     state="hidden")
        self.canvas.itemconfigure(self._bg_ring, state="normal")
        self.canvas.itemconfigure(self._arc,     state="normal")

    def show_dot(self, color):
        self._spinning = False
        self.canvas.itemconfigure(self._dot, fill=color, state="normal")
        self.canvas.itemconfigure(self._bg_ring, state="hidden")
        self.canvas.itemconfigure(self._arc,     state="hidden")


class StatusDot:
    """Tiny colored dot inside the status card."""
    def __init__(self, parent, bg):
        self.canvas = tk.Canvas(parent, width=14, height=14,
                                bg=bg, highlightthickness=0)
        self._oval = self.canvas.create_oval(2, 2, 12, 12, fill="#8b93a7", outline="")

    def set_color(self, color):
        self.canvas.itemconfigure(self._oval, fill=color)
