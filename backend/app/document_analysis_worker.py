"""T51 explicit one-shot analysis worker: python -m app.document_analysis_worker [--max-jobs N]

Separate from the T49 scanning/deleting worker (app.document_worker). Nothing is
scheduled and nothing runs during API startup. Only the deterministic
MockAnalysisProvider is wired; no real LLM or network call exists.
"""
import argparse

from app.core.config import get_settings
from app.db import create_db_engine, create_session_factory
from app.repositories.document_analyses import SqlAnalysisRepository
from app.routers.documents import get_document_storage
from app.services.analysis_provider import MockAnalysisProvider
from app.services.document_analyses import MAX_JOBS_PER_RUN, AnalysisWorker


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m app.document_analysis_worker")
    parser.add_argument("--max-jobs", type=int, default=MAX_JOBS_PER_RUN, choices=range(1, 101), metavar="1..100")
    args = parser.parse_args(argv)
    settings = get_settings()
    if settings.database is None:
        raise SystemExit("DATABASE_URL is required")
    engine = create_db_engine(settings.database)
    try:
        with create_session_factory(engine)() as session:
            summary = AnalysisWorker(SqlAnalysisRepository(session), get_document_storage(),
                                     MockAnalysisProvider(), max_jobs=args.max_jobs).run()
            return 1 if summary.requeued else 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
