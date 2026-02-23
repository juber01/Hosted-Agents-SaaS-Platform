from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from saas_platform.domain.interfaces import PlanCatalog, ProvisioningQueue, TenantCatalog, UsageMeter
from saas_platform.domain.models import (
    Plan,
    PlanLimits,
    ProvisioningJob,
    Tenant,
    TenantBillingRecord,
    TenantUsageSummary,
    UsageEvent,
)


class Base(DeclarativeBase):
    pass


class TenantRow(Base):
    __tablename__ = "tenants"

    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    plan: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PlanRow(Base):
    __tablename__ = "plans"

    plan_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    monthly_messages: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_token_cap: Mapped[int] = mapped_column(Integer, nullable=False)
    max_agents: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProvisioningJobRow(Base):
    __tablename__ = "provisioning_jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    step: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UsageEventRow(Base):
    __tablename__ = "usage_events"

    request_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_estimate: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PostgresSessionFactory:
    def __init__(
        self,
        dsn: str,
        *,
        pool_size: int = 3,
        max_overflow: int = 0,
        pool_timeout_seconds: int = 10,
        pool_recycle_seconds: int = 900,
    ) -> None:
        self.engine = create_engine(
            dsn,
            future=True,
            pool_pre_ping=True,
            pool_size=max(pool_size, 1),
            max_overflow=max(max_overflow, 0),
            pool_timeout=max(pool_timeout_seconds, 1),
            pool_recycle=max(pool_recycle_seconds, 30),
        )
        self._sessionmaker = sessionmaker(bind=self.engine, class_=Session, autoflush=False, autocommit=False)

    def create_all(self) -> None:
        Base.metadata.create_all(bind=self.engine)

    def session(self) -> Session:
        return self._sessionmaker()


class PostgresTenantCatalog(TenantCatalog):
    def __init__(self, session_factory: PostgresSessionFactory) -> None:
        self._sf = session_factory

    def upsert_tenant(self, tenant: Tenant) -> None:
        with self._sf.session() as session:
            row = session.get(TenantRow, tenant.tenant_id)
            if row is None:
                row = TenantRow(
                    tenant_id=tenant.tenant_id,
                    name=tenant.name,
                    plan=tenant.plan,
                    status=tenant.status,
                    created_at=tenant.created_at,
                )
                session.add(row)
            else:
                row.name = tenant.name
                row.plan = tenant.plan
                row.status = tenant.status
            session.commit()

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        with self._sf.session() as session:
            row = session.get(TenantRow, tenant_id)
            if row is None:
                return None
            return Tenant(
                tenant_id=row.tenant_id,
                name=row.name,
                plan=row.plan,
                status=row.status,
                created_at=row.created_at,
            )


class PostgresPlanCatalog(PlanCatalog):
    def __init__(self, session_factory: PostgresSessionFactory) -> None:
        self._sf = session_factory

    def upsert_plan(self, plan: Plan) -> None:
        with self._sf.session() as session:
            row = session.get(PlanRow, plan.plan_id)
            if row is None:
                row = PlanRow(
                    plan_id=plan.plan_id,
                    display_name=plan.display_name,
                    monthly_messages=plan.limits.monthly_messages,
                    monthly_token_cap=plan.limits.monthly_token_cap,
                    max_agents=plan.limits.max_agents,
                    active=plan.active,
                    created_at=plan.created_at,
                )
                session.add(row)
            else:
                row.display_name = plan.display_name
                row.monthly_messages = plan.limits.monthly_messages
                row.monthly_token_cap = plan.limits.monthly_token_cap
                row.max_agents = plan.limits.max_agents
                row.active = plan.active
            session.commit()

    def get_plan(self, plan_id: str) -> Plan | None:
        with self._sf.session() as session:
            row = session.get(PlanRow, plan_id)
            if row is None:
                return None
            return Plan(
                plan_id=row.plan_id,
                display_name=row.display_name,
                limits=PlanLimits(
                    monthly_messages=row.monthly_messages,
                    monthly_token_cap=row.monthly_token_cap,
                    max_agents=row.max_agents,
                ),
                active=bool(row.active),
                created_at=row.created_at,
            )

    def list_plans(self) -> list[Plan]:
        with self._sf.session() as session:
            rows = session.execute(select(PlanRow).order_by(PlanRow.plan_id)).scalars().all()
            return [
                Plan(
                    plan_id=row.plan_id,
                    display_name=row.display_name,
                    limits=PlanLimits(
                        monthly_messages=row.monthly_messages,
                        monthly_token_cap=row.monthly_token_cap,
                        max_agents=row.max_agents,
                    ),
                    active=bool(row.active),
                    created_at=row.created_at,
                )
                for row in rows
            ]


class PostgresProvisioningQueue(ProvisioningQueue):
    def __init__(self, session_factory: PostgresSessionFactory) -> None:
        self._sf = session_factory

    def enqueue(self, job: ProvisioningJob) -> None:
        now = datetime.now(timezone.utc)
        idempotency_key = job.idempotency_key or job.job_id
        with self._sf.session() as session:
            exists = session.execute(
                select(ProvisioningJobRow.job_id).where(ProvisioningJobRow.idempotency_key == idempotency_key)
            ).scalar_one_or_none()
            if exists:
                return
            row = ProvisioningJobRow(
                job_id=job.job_id,
                idempotency_key=idempotency_key,
                tenant_id=job.tenant_id,
                step=job.step,
                state="queued",
                retries=job.retries,
                max_attempts=max(job.max_attempts, 1),
                error=job.error,
                available_at=job.available_at,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.commit()

    def claim_next(self) -> ProvisioningJob | None:
        with self._sf.session() as session:
            stmt = (
                select(ProvisioningJobRow)
                .where(
                    ProvisioningJobRow.state == "queued",
                    ProvisioningJobRow.available_at <= datetime.now(timezone.utc),
                )
                .order_by(ProvisioningJobRow.available_at, ProvisioningJobRow.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            row = session.execute(stmt).scalar_one_or_none()
            if row is None:
                return None
            row.state = "running"
            row.updated_at = datetime.now(timezone.utc)
            session.commit()
            return ProvisioningJob(
                job_id=row.job_id,
                tenant_id=row.tenant_id,
                step=row.step,
                idempotency_key=row.idempotency_key,
                state=row.state,
                retries=row.retries,
                max_attempts=row.max_attempts,
                error=row.error,
                created_at=row.created_at,
                available_at=row.available_at,
            )

    def mark_done(self, job_id: str) -> None:
        with self._sf.session() as session:
            row = session.get(ProvisioningJobRow, job_id)
            if row is None:
                return
            row.state = "done"
            row.updated_at = datetime.now(timezone.utc)
            session.commit()

    def mark_retry(self, job_id: str, error: str, retry_in_seconds: int) -> None:
        with self._sf.session() as session:
            row = session.get(ProvisioningJobRow, job_id)
            if row is None:
                return
            row.state = "queued"
            row.retries += 1
            row.error = error[:500]
            row.available_at = datetime.now(timezone.utc) + timedelta(seconds=max(retry_in_seconds, 0))
            row.updated_at = datetime.now(timezone.utc)
            session.commit()

    def mark_dead_letter(self, job_id: str, error: str) -> None:
        with self._sf.session() as session:
            row = session.get(ProvisioningJobRow, job_id)
            if row is None:
                return
            row.state = "dead_letter"
            row.retries += 1
            row.error = error[:500]
            row.updated_at = datetime.now(timezone.utc)
            session.commit()

    def get_job(self, job_id: str) -> ProvisioningJob | None:
        with self._sf.session() as session:
            row = session.get(ProvisioningJobRow, job_id)
            if row is None:
                return None
            return ProvisioningJob(
                job_id=row.job_id,
                tenant_id=row.tenant_id,
                step=row.step,
                idempotency_key=row.idempotency_key,
                state=row.state,
                retries=row.retries,
                max_attempts=row.max_attempts,
                error=row.error,
                created_at=row.created_at,
                available_at=row.available_at,
            )


class PostgresUsageMeter(UsageMeter):
    def __init__(self, session_factory: PostgresSessionFactory) -> None:
        self._sf = session_factory

    def record(self, event: UsageEvent) -> None:
        with self._sf.session() as session:
            row = UsageEventRow(
                request_id=event.request_id,
                tenant_id=event.tenant_id,
                agent_id=event.agent_id,
                model=event.model,
                latency_ms=event.latency_ms,
                tokens_in=event.tokens_in,
                tokens_out=event.tokens_out,
                cost_estimate=event.cost_estimate,
                created_at=event.created_at,
            )
            session.merge(row)
            session.commit()

    def summarize_tenant_month(self, tenant_id: str, month: str) -> TenantUsageSummary:
        start, end = _month_bounds(month)
        with self._sf.session() as session:
            stmt = select(
                func.count(UsageEventRow.request_id),
                func.coalesce(func.sum(UsageEventRow.tokens_in + UsageEventRow.tokens_out), 0),
                func.coalesce(func.sum(UsageEventRow.cost_estimate), 0.0),
            ).where(
                UsageEventRow.tenant_id == tenant_id,
                UsageEventRow.created_at >= start,
                UsageEventRow.created_at < end,
            )
            messages_used, tokens_used, cost_estimate = session.execute(stmt).one()
            return TenantUsageSummary(
                tenant_id=tenant_id,
                month=month,
                messages_used=int(messages_used or 0),
                tokens_used=int(tokens_used or 0),
                cost_estimate=float(cost_estimate or 0.0),
            )

    def summarize_all_tenants_month(self, month: str) -> list[TenantBillingRecord]:
        start, end = _month_bounds(month)
        with self._sf.session() as session:
            stmt = (
                select(
                    UsageEventRow.tenant_id,
                    func.count(UsageEventRow.request_id).label("messages_used"),
                    func.coalesce(func.sum(UsageEventRow.tokens_in + UsageEventRow.tokens_out), 0).label(
                        "tokens_used"
                    ),
                    func.coalesce(func.sum(UsageEventRow.cost_estimate), 0.0).label("cost_estimate"),
                )
                .where(UsageEventRow.created_at >= start, UsageEventRow.created_at < end)
                .group_by(UsageEventRow.tenant_id)
                .order_by(UsageEventRow.tenant_id)
            )
            rows = session.execute(stmt).all()
            return [
                TenantBillingRecord(
                    tenant_id=str(tenant_id),
                    month=month,
                    messages_used=int(messages_used or 0),
                    tokens_used=int(tokens_used or 0),
                    cost_estimate=float(cost_estimate or 0.0),
                )
                for tenant_id, messages_used, tokens_used, cost_estimate in rows
            ]


def _month_bounds(month: str) -> tuple[datetime, datetime]:
    start = datetime.strptime(month, "%Y-%m").replace(tzinfo=timezone.utc)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end
