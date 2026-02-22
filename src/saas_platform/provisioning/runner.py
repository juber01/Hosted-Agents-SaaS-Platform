from __future__ import annotations

import argparse
import time

from saas_platform.api.main import create_app
from saas_platform.config import Settings, get_settings
from saas_platform.provisioning.worker import process_next_job


def run_worker_once(settings: Settings) -> bool:
    app = create_app(settings)
    ctx = app.state.ctx
    return process_next_job(
        queue=ctx.queue,
        catalog=ctx.catalog,
        default_max_attempts=settings.provisioning_job_max_attempts,
        retry_base_seconds=settings.provisioning_retry_base_seconds,
    )


def run_worker_forever(settings: Settings) -> None:
    app = create_app(settings)
    ctx = app.state.ctx

    while True:
        processed = process_next_job(
            queue=ctx.queue,
            catalog=ctx.catalog,
            default_max_attempts=settings.provisioning_job_max_attempts,
            retry_base_seconds=settings.provisioning_retry_base_seconds,
        )
        if not processed:
            time.sleep(max(settings.provisioning_worker_poll_seconds, 1))


def main() -> int:
    parser = argparse.ArgumentParser(description="Hosted Agents SaaS provisioning worker")
    parser.add_argument("--once", action="store_true", help="Process a single job and exit")
    args = parser.parse_args()

    settings = get_settings()
    if args.once:
        run_worker_once(settings=settings)
        return 0

    run_worker_forever(settings=settings)
    return 0

