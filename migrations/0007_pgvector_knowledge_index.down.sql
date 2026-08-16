BEGIN;
DO $guard$
BEGIN
 IF EXISTS(SELECT 1 FROM flowpilot.schema_migrations WHERE migration_id>'0007_pgvector_knowledge_index') THEN RAISE EXCEPTION 'successor migration exists' USING ERRCODE='55000'; END IF;
 IF EXISTS(SELECT 1 FROM flowpilot.knowledge_sections WHERE embedding IS NOT NULL OR search_vector IS NOT NULL) THEN RAISE EXCEPTION 'knowledge index is not empty' USING ERRCODE='55000'; END IF;
END $guard$;
DROP INDEX flowpilot.knowledge_jobs_pending_idx;
DROP INDEX flowpilot.knowledge_sections_embedding_idx;
DROP INDEX flowpilot.knowledge_sections_keyword_idx;
ALTER TABLE flowpilot.knowledge_sections DROP COLUMN embedding_version,DROP COLUMN embedding_model,DROP COLUMN embedding,DROP COLUMN search_vector;
DELETE FROM flowpilot.schema_migrations WHERE migration_id='0007_pgvector_knowledge_index';
COMMIT;
