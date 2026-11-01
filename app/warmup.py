from datetime import datetime, timezone

from . import config


def daily_limit(added_at, now=None):
    """Geometric ramp from WARMUP_START to IP_DAILY_MAX over WARMUP_DAYS."""
    now = now or datetime.now(timezone.utc)
    day = max(0, (now - added_at).days)
    if day >= config.WARMUP_DAYS:
        return config.IP_DAILY_MAX
    ratio = day / config.WARMUP_DAYS
    return max(1, int(config.WARMUP_START * (config.IP_DAILY_MAX / config.WARMUP_START) ** ratio))
