from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

from sqlalchemy import create_engine, text


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit and migrate wildcard customer entitlements to explicit customer grants."
    )
    parser.add_argument(
        "--dsn",
        default=os.getenv("TENANT_CATALOG_DSN", "").strip(),
        help="Postgres SQLAlchemy DSN. Defaults to TENANT_CATALOG_DSN.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("audit", help="Show wildcard vs explicit entitlement counts.")

    export_parser = subparsers.add_parser(
        "export-template",
        help="Export distinct wildcard tenant+agent pairs into a CSV template for customer mapping.",
    )
    export_parser.add_argument(
        "--output",
        required=True,
        help="CSV output path.",
    )

    apply_parser = subparsers.add_parser(
        "apply",
        help="Apply explicit grants from CSV. Optionally remove matching wildcard grants.",
    )
    apply_parser.add_argument(
        "--mapping-file",
        required=True,
        help="CSV with columns: tenant_id,agent_id,customer_id",
    )
    apply_parser.add_argument(
        "--drop-wildcards",
        action="store_true",
        help="Delete wildcard '*' rows for tenant+agent pairs present in mapping file.",
    )
    apply_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and count changes without writing.",
    )

    args = parser.parse_args()

    if not args.dsn:
        raise SystemExit("DSN is required. Set --dsn or TENANT_CATALOG_DSN.")

    engine = create_engine(args.dsn, future=True)
    if args.command == "audit":
        _audit(engine)
        return 0
    if args.command == "export-template":
        _export_template(engine, Path(args.output))
        return 0
    if args.command == "apply":
        _apply_mapping(
            engine=engine,
            mapping_file=Path(args.mapping_file),
            dry_run=bool(args.dry_run),
            drop_wildcards=bool(args.drop_wildcards),
        )
        return 0
    raise SystemExit(f"Unsupported command: {args.command}")


def _audit(engine) -> None:
    with engine.connect() as conn:
        totals = conn.execute(
            text(
                """
                select
                    count(*) as total_rows,
                    count(*) filter (where customer_id = '*') as wildcard_rows,
                    count(*) filter (where customer_id <> '*') as explicit_rows
                from customer_agent_entitlements
                """
            )
        ).one()
        wildcard_pairs = conn.execute(
            text(
                """
                select count(*)
                from (
                    select tenant_id, agent_id
                    from customer_agent_entitlements
                    where customer_id = '*'
                    group by tenant_id, agent_id
                ) as q
                """
            )
        ).scalar_one()
        explicit_customers = conn.execute(
            text(
                """
                select count(*)
                from (
                    select tenant_id, customer_id
                    from customer_agent_entitlements
                    where customer_id <> '*'
                    group by tenant_id, customer_id
                ) as q
                """
            )
        ).scalar_one()

    print("entitlement_audit:")
    print(f"  total_rows: {int(totals.total_rows)}")
    print(f"  wildcard_rows: {int(totals.wildcard_rows)}")
    print(f"  explicit_rows: {int(totals.explicit_rows)}")
    print(f"  wildcard_tenant_agent_pairs: {int(wildcard_pairs)}")
    print(f"  explicit_tenant_customer_pairs: {int(explicit_customers)}")


def _export_template(engine, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                select tenant_id, agent_id
                from customer_agent_entitlements
                where customer_id = '*'
                group by tenant_id, agent_id
                order by tenant_id, agent_id
                """
            )
        ).all()

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["tenant_id", "agent_id", "customer_id"])
        writer.writeheader()
        for tenant_id, agent_id in rows:
            writer.writerow(
                {
                    "tenant_id": str(tenant_id),
                    "agent_id": str(agent_id),
                    "customer_id": "",
                }
            )
    print(f"template_written: {output_path} ({len(rows)} rows)")


def _apply_mapping(*, engine, mapping_file: Path, dry_run: bool, drop_wildcards: bool) -> None:
    mappings = _load_mapping_rows(mapping_file)
    if not mappings:
        print("no_rows_loaded")
        return

    unique_pairs = {(tenant_id, agent_id) for tenant_id, agent_id, _ in mappings}
    explicit_count = len(mappings)
    wildcard_drop_count = len(unique_pairs) if drop_wildcards else 0

    if dry_run:
        print("dry_run_summary:")
        print(f"  explicit_grants_to_upsert: {explicit_count}")
        print(f"  wildcard_pairs_to_drop: {wildcard_drop_count}")
        return

    with engine.begin() as conn:
        for tenant_id, agent_id, customer_id in mappings:
            conn.execute(
                text(
                    """
                    insert into customer_agent_entitlements (tenant_id, customer_id, agent_id, created_at)
                    values (:tenant_id, :customer_id, :agent_id, now())
                    on conflict (tenant_id, customer_id, agent_id) do nothing
                    """
                ),
                {"tenant_id": tenant_id, "customer_id": customer_id, "agent_id": agent_id},
            )

        if drop_wildcards:
            for tenant_id, agent_id in unique_pairs:
                conn.execute(
                    text(
                        """
                        delete from customer_agent_entitlements
                        where tenant_id = :tenant_id
                          and agent_id = :agent_id
                          and customer_id = '*'
                        """
                    ),
                    {"tenant_id": tenant_id, "agent_id": agent_id},
                )

    print("apply_summary:")
    print(f"  explicit_grants_upserted: {explicit_count}")
    print(f"  wildcard_pairs_dropped: {wildcard_drop_count}")


def _load_mapping_rows(path: Path) -> list[tuple[str, str, str]]:
    if not path.exists():
        raise SystemExit(f"Mapping file not found: {path}")

    rows: list[tuple[str, str, str]] = []
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"tenant_id", "agent_id", "customer_id"}
        missing = required.difference(set(reader.fieldnames or []))
        if missing:
            raise SystemExit(f"Missing required CSV columns: {sorted(missing)}")

        for index, raw in enumerate(reader, start=2):
            tenant_id = str(raw.get("tenant_id", "")).strip()
            agent_id = str(raw.get("agent_id", "")).strip()
            customer_id = str(raw.get("customer_id", "")).strip()
            if not tenant_id or not agent_id or not customer_id:
                continue
            if customer_id == "*":
                raise SystemExit(f"Invalid customer_id '*' in mapping file at line {index}")
            rows.append((tenant_id, agent_id, customer_id))

    deduped = sorted(set(rows))
    return deduped


if __name__ == "__main__":
    raise SystemExit(main())

