from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from saas_platform.domain.interfaces import ProvisioningQueue, TenantCatalog, UsageMeter
from saas_platform.domain.models import ProvisioningJob, Tenant, UsageEvent


class Base(DeclarativeBase):
    pass


class TenantRow(Base):
    __tablename__ = "tenants"

    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    plan: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProvisioningJobRow(Base):
    __tablename__ = "provisioning_jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    step: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
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
    def __init__(self, dsn: str) -> None:
        self.engine = create_engine(dsn, future=True, pool_pre_ping=True)
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


class PostgresProvisioningQueue(ProvisioningQueue):
    def __init__(self, session_factory: PostgresSessionFactory) -> None:
        self._sf = session_factory

    def enqueue(self, job: ProvisioningJob) -> None:
        now = datetime.now(timezone.utc)
        with self._sf.session() as session:
            row = ProvisioningJobRow(
                job_id=job.job_id,
                tenant_id=job.tenant_id,
                step=job.step,
                state="queued",
                retries=job.retries,
                error=job.error,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.commit()

    def claim_next(self) -> ProvisioningJob | None:
        with self._sf.session() as session:
            stmt = (
                select(ProvisioningJobRow)
                .where(ProvisioningJobRow.state == "queued")
                .order_by(ProvisioningJobRow.created_at)
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
                state=row.state,
                retries=row.retries,
                error=row.error,
            )

    def mark_done(self, job_id: str) -> None:
        with self._sf.session() as session:
            row = session.get(ProvisioningJobRow, job_id)
            if row is None:
                return
            row.state = "done"
            row.updated_at = datetime.now(timezone.utc)
            session.commit()

    def mark_failed(self, job_id: str, error: str) -> None:
        with self._sf.session() as session:
            row = session.get(ProvisioningJobRow, job_id)
            if row is None:
                return
            row.state = "failed"
            row.retries += 1
            row.error = error[:500]
            row.updated_at = datetime.now(timezone.utc)
            session.commit()


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
                created_at=datetime.now(timezone.utc),
            )
            session.merge(row)
            session.commit()
