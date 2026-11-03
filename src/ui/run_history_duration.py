# -*- coding: utf-8 -*-
"""Format run duration text and its speed color from the same value."""


def history_duration(duration_seconds, tokens: dict) -> tuple[str, str | None]:
    if duration_seconds is None:
        return "", None
    ds = duration_seconds
    if ds < 60:
        text = f"{ds:.0f}s"
    elif ds < 3600:
        minutes = int(ds // 60)
        seconds = int(ds % 60)
        text = f"{minutes}m{seconds:02d}s"
    else:
        hours = int(ds // 3600)
        minutes = int((ds % 3600) // 60)
        text = f"{hours}h{minutes:02d}m"
    key = "fast" if ds < 30 else "medium" if ds < 300 else "slow"
    return text, tokens[key]
