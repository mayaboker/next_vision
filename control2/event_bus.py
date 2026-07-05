"""
Minimal synchronous publish/subscribe Event.

Used to pass values across the serailcontroler <-> control2 boundary without
either side importing the other's classes. Subscribers are plain callables;
``fire`` invokes each with the given ``*args`` / ``**kwargs``.
"""


class Event:
    def __init__(self):
        self._subscribers = []

    def subscribe(self, callback):
        """Register a callable to be invoked on every fire()."""
        self._subscribers.append(callback)

    def unsubscribe(self, callback):
        """Remove a previously registered callable (no-op if absent)."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def fire(self, *args, **kwargs):
        """Invoke every subscriber with the given arguments."""
        # Iterate a copy so a subscriber may (un)subscribe during dispatch.
        for callback in list(self._subscribers):
            callback(*args, **kwargs)
