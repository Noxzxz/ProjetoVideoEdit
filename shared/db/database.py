from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from config.settings import settings

Base = declarative_base()


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(Integer, primary_key=True)
    video_hash = Column(String, nullable=False)
    video_name = Column(String, nullable=False)
    status = Column(String, nullable=False)
    started_at = Column(DateTime, default=datetime.now)
    finished_at = Column(DateTime, nullable=True)
    total_duration_seconds = Column(Float, nullable=True)


class AgentMetric(Base):
    __tablename__ = "agent_metrics"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("pipeline_runs.id"), nullable=False)
    agent_name = Column(String, nullable=False)
    step = Column(String, nullable=False)
    started_at = Column(DateTime, default=datetime.now)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String, nullable=False)
    error_message = Column(String, nullable=True)


def init_db():
    engine = create_engine(f"sqlite:///{settings.sqlite_path}")
    Base.metadata.create_all(engine)
    return engine


Session = sessionmaker()
