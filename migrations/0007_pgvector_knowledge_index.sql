BEGIN;
DO $predecessor$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM flowpilot.schema_migrations WHERE migration_id='0006_knowledge_document_facts') THEN
  RAISE EXCEPTION '0007 requires 0006' USING ERRCODE='55000';
 END IF;
END $predecessor$;
INSERT INTO flowpilot.schema_migrations(migration_id,content_digest)
VALUES('0007_pgvector_knowledge_index','sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2')
ON CONFLICT(migration_id) DO UPDATE SET content_digest=EXCLUDED.content_digest
WHERE flowpilot.schema_migrations.content_digest=EXCLUDED.content_digest;
DO $digest$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM flowpilot.schema_migrations WHERE migration_id='0007_pgvector_knowledge_index' AND content_digest='sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2') THEN
  RAISE EXCEPTION 'migration id is bound to another digest' USING ERRCODE='23514';
 END IF;
END $digest$;
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA flowpilot;
ALTER TABLE flowpilot.knowledge_sections
 ADD COLUMN IF NOT EXISTS search_vector tsvector,
 ADD COLUMN IF NOT EXISTS embedding flowpilot.vector(384),
 ADD COLUMN IF NOT EXISTS embedding_model text,
 ADD COLUMN IF NOT EXISTS embedding_version text;
CREATE INDEX IF NOT EXISTS knowledge_sections_keyword_idx
 ON flowpilot.knowledge_sections USING gin(search_vector);
CREATE INDEX IF NOT EXISTS knowledge_sections_embedding_idx
 ON flowpilot.knowledge_sections USING hnsw(embedding flowpilot.vector_cosine_ops)
 WITH(m=16,ef_construction=64);
CREATE INDEX IF NOT EXISTS knowledge_jobs_pending_idx
 ON flowpilot.knowledge_index_jobs(tenant_id,requested_at,job_id)
 WHERE index_state IN('pending','stale');
COMMIT;
