from datetime import datetime

from sqlalchemy.orm import Session as SqlSession

from shared.db.database import AgentMetric, PipelineRun, init_db


class AnalyticsRepository:
    def __init__(self):
        self.engine = init_db()

    def create_run(self, video_hash: str, video_name: str) -> int:
        with SqlSession(self.engine) as session:
            run = PipelineRun(
                video_hash=video_hash,
                video_name=video_name,
                status="RUNNING",
                started_at=datetime.now(),
            )
            session.add(run)
            session.commit()
            return run.id

    def mark_run_done(self, run_id: int, total_duration: float) -> None:
        with SqlSession(self.engine) as session:
            run = session.get(PipelineRun, run_id)
            if run:
                run.status = "DONE"
                run.finished_at = datetime.now()
                run.total_duration_seconds = total_duration
                session.commit()

    def mark_run_failed(self, run_id: int, error: str) -> None:
        with SqlSession(self.engine) as session:
            run = session.get(PipelineRun, run_id)
            if run:
                run.status = "FAILED"
                run.finished_at = datetime.now()
                session.commit()

    def log_metric(
        self,
        run_id: int,
        agent_name: str,
        step: str,
        started_at: datetime,
        finished_at: datetime,
        status: str,
        error_message: str | None = None,
    ) -> None:
        with SqlSession(self.engine) as session:
            metric = AgentMetric(
                run_id=run_id,
                agent_name=agent_name,
                step=step,
                started_at=started_at,
                finished_at=finished_at,
                status=status,
                error_message=error_message,
            )
            session.add(metric)
            session.commit()

    def get_run_history(self, limit: int = 20) -> list[PipelineRun]:
        with SqlSession(self.engine) as session:
            return (
                session.query(PipelineRun)
                .order_by(PipelineRun.started_at.desc())
                .limit(limit)
                .all()
            )
