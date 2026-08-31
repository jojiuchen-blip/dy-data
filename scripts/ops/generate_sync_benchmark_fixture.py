from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path


FIXTURE_PROTOCOL = "dydata-sync-benchmark-v1"


@dataclass(frozen=True)
class FixtureConfig:
    days: int = 30
    stores: int = 100
    orders_per_day: int = 1000
    seed: int = 58

    def validate(self) -> None:
        for name, value in asdict(self).items():
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{name} must be an integer")
        if self.days <= 0 or self.stores <= 0 or self.orders_per_day <= 0:
            raise ValueError("days, stores and orders_per_day must be positive")
        if self.days > 3660 or self.stores > 100_000 or self.orders_per_day > 10_000_000:
            raise ValueError("fixture scale exceeds the bounded generator contract")


@dataclass(frozen=True)
class FixtureManifest:
    protocol: str
    row_count: int
    partition_count: int
    sha256: str
    config: dict[str, int]

    def as_json(self) -> dict[str, object]:
        return asdict(self)


def _canonical_line(row: dict[str, object]) -> bytes:
    return (
        json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def generate_fixture(
    output_dir: Path | str,
    config: FixtureConfig,
    *,
    overwrite: bool = False,
) -> FixtureManifest:
    """Write a deterministic JSONL fixture and its checksum manifest."""

    config.validate()
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    data_path = directory / "orders.jsonl"
    manifest_path = directory / "manifest.json"
    if not overwrite and (data_path.exists() or manifest_path.exists()):
        raise FileExistsError("fixture output already exists; pass overwrite explicitly")

    digest = hashlib.sha256()
    row_count = 0
    start = date(2026, 1, 1)
    with data_path.open("wb") as handle:
        for day_index in range(config.days):
            business_date = start + timedelta(days=day_index)
            for store_index in range(config.stores):
                for order_index in range(config.orders_per_day):
                    paid_amount = 1000 + (
                        (day_index + 1) * 101
                        + (store_index + 1) * 29
                        + (order_index + 1) * 17
                        + config.seed
                    ) % 90_000
                    verified = (
                        (order_index + store_index + day_index + config.seed) % 5
                    ) != 0
                    row = {
                        "business_date": business_date.isoformat(),
                        "coupon_id": (
                            f"coupon-{day_index:04d}-{store_index:06d}-{order_index:08d}"
                        ),
                        "order_id": (
                            f"order-{day_index:04d}-{store_index:06d}-{order_index:08d}"
                        ),
                        "paid_amount_cent": paid_amount,
                        "store_id": f"store-{store_index:06d}",
                        "verified": verified,
                        "verified_amount_cent": paid_amount if verified else 0,
                    }
                    encoded = _canonical_line(row)
                    handle.write(encoded)
                    digest.update(encoded)
                    row_count += 1

    manifest = FixtureManifest(
        protocol=FIXTURE_PROTOCOL,
        row_count=row_count,
        partition_count=config.days * config.stores,
        sha256=digest.hexdigest(),
        config={key: int(value) for key, value in sorted(asdict(config).items())},
    )
    manifest_path.write_text(
        json.dumps(manifest.as_json(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a deterministic synthetic sync benchmark fixture."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--stores", type=int, default=100)
    parser.add_argument("--orders-per-day", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=58)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manifest = generate_fixture(
        args.output_dir,
        FixtureConfig(
            days=args.days,
            stores=args.stores,
            orders_per_day=args.orders_per_day,
            seed=args.seed,
        ),
        overwrite=args.overwrite,
    )
    print(json.dumps(manifest.as_json(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
