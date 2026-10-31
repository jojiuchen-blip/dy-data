"""The shared per-direction confirmation amount contract, in integer cents."""
from collections.abc import Mapping


def statement_confirmable_amounts(*, promotion_net_fee_cent: int, management_net_fee_cent: int,
                                  frozen_by_direction: Mapping[int, int]) -> dict[str, int]:
    """Keep promotion credits signed; management confirmations cannot be negative."""
    return {"PROMOTION": promotion_net_fee_cent - frozen_by_direction.get(1, 0),
        "MANAGEMENT": max(management_net_fee_cent - frozen_by_direction.get(2, 0), 0)}
