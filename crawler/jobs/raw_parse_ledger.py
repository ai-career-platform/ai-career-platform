"""T153 raw artifact to normalized posting lineage; offline fixture-only.

PostgreSQL connection is supplied explicitly. No migration, HTTP, timer,
scheduler, dispatch or live collection. A transaction covers posting UPSERT,
keyword discovery, and parse status to prevent partial DB lineage.
"""
from __future__ import annotations

from dataclasses import dataclass

from crawler.jobs.fixture_parse_pipeline import parse_stored_detail, PARSER_VERSION
from crawler.jobs.keyword_management import KeywordStore
from crawler.storage.postgres import PostgresPostingStore


@dataclass(frozen=True)
class ParseOutcome:
    parse_id: int
    artifact_id: object
    status: str
    error_code: str | None
    write_result: str | None


class RawParseLedger:
    def __init__(self, connection, files):
        self.connection = connection
        self.files = files

    def process(self, artifact_id, *, parser_version=PARSER_VERSION) -> ParseOutcome:
        if not isinstance(parser_version, str) or not 1 <= len(parser_version) <= 100:
            raise ValueError("parser_version must be 1..100 chars")
        # One transaction covers metadata read, postings UPSERT, discovery and
        # lineage INSERT. Locks raw row to serialize competing processors.
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute("""SELECT artifact_id,keyword_id,kind,source_url,storage_key,sha256
                    FROM crawler_training.raw_artifacts
                    WHERE artifact_id=%s FOR UPDATE""", (artifact_id,))
                row = cur.fetchone()
                if row is None:
                    raise ValueError("Unknown raw artifact")
                raw_id,keyword_id,kind,url,storage_key,sha = row
                if kind != "detail":
                    raise ValueError("Only raw detail artifacts are parseable")
                cur.execute("""SELECT parse_id,validation_status,error_code,write_result
                    FROM crawler_training.raw_parse_results
                    WHERE artifact_id=%s AND parser_version=%s""",
                    (artifact_id,parser_version))
                existing = cur.fetchone()
                if existing is not None:
                    return ParseOutcome(existing[0],artifact_id,existing[1],
                                        existing[2],existing[3])

                result = parse_stored_detail(
                    artifact_id=raw_id,source_url=url,storage_key=storage_key,
                    sha256=sha,files=self.files)
                if result.status == "VALID":
                    posting = result.posting
                    action = PostgresPostingStore(self.connection).upsert(posting)
                    KeywordStore(self.connection).record_discovery(
                        keyword_id,posting.source_code,posting.external_posting_id)
                    values = (artifact_id,parser_version,"VALID",None,
                              posting.source_code,posting.external_posting_id,action)
                else:
                    values = (artifact_id,parser_version,"INVALID",result.error_code,
                              None,None,None)
                cur.execute("""INSERT INTO crawler_training.raw_parse_results
                    (artifact_id,parser_version,validation_status,error_code,
                     source_code,external_posting_id,write_result)
                    VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING parse_id""", values)
                parse_id = cur.fetchone()[0]
                return ParseOutcome(parse_id,artifact_id,values[2],values[3],values[6])
