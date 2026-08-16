BEGIN;
DO $guard$
BEGIN
 IF EXISTS(SELECT 1 FROM flowpilot.schema_migrations WHERE migration_id>'0006_knowledge_document_facts') THEN RAISE EXCEPTION 'successor migration exists' USING ERRCODE='55000'; END IF;
 IF EXISTS(SELECT 1 FROM flowpilot.knowledge_documents) THEN RAISE EXCEPTION 'knowledge facts are not empty' USING ERRCODE='55000'; END IF;
END $guard$;
DROP VIEW flowpilot.knowledge_index_diagnostics;
DROP TRIGGER knowledge_versions_immutable ON flowpilot.knowledge_document_versions;
DROP FUNCTION flowpilot.reject_knowledge_version_mutation();
DROP TABLE flowpilot.knowledge_content_bodies,flowpilot.knowledge_sections,flowpilot.knowledge_index_jobs,flowpilot.knowledge_outbox,flowpilot.knowledge_inbox,flowpilot.knowledge_document_versions,flowpilot.knowledge_documents;
DELETE FROM flowpilot.schema_migrations WHERE migration_id='0006_knowledge_document_facts';
COMMIT;
