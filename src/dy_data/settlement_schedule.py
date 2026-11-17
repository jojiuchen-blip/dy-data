"""Rollout switch for month-close ownership of formal settlement fees."""

import os


MONTHLY_FEE_DEFERRED = "monthly_fee_deferred"


def monthly_settlement_enabled() -> bool:
    return os.getenv("SETTLEMENT_MONTHLY_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
