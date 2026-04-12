class SkipEntryError(Exception):
    """Signals that the current CSV entry should be skipped after repeated failures."""
