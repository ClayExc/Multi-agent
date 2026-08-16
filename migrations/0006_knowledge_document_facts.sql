BEGIN;
DO $predecessor$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM flowpilot.schema_migrations WHERE migration_id='0005_governance_audit_query') THEN
  RAISE EXCEPTION '0006 requires 0005' USING ERRCODE='55000';
 END IF;
END $predecessor$;
INSERT INTO flowpilot.schema_migrations(migration_id,content_digest)
VALUES ('0006_knowledge_document_facts','sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2')
ON CONFLICT (migration_id) DO UPDATE SET content_digest=EXCLUDED.content_digest
WHERE flowpilot.schema_migrations.content_digest=EXCLUDED.content_digest;
DO $digest$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM flowpilot.schema_migrations WHERE migration_id='0006_knowledge_document_facts' AND content_digest='sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2') THEN
  RAISE EXCEPTION 'migration id is bound to another digest' USING ERRCODE='23514';
 END IF;
END $digest$;
CREATE TABLE IF NOT EXISTS flowpilot.knowledge_documents(
 tenant_id text NOT NULL,document_id text NOT NULL,revision bigint NOT NULL CHECK(revision>=0),
 current_version bigint NOT NULL CHECK(current_version>=0),lifecycle text NOT NULL CHECK(lifecycle IN('active','retired','deleted')),
 created_at timestamptz NOT NULL,updated_at timestamptz NOT NULL CHECK(updated_at>=created_at),retired_at timestamptz,deleted_at timestamptz,
 PRIMARY KEY(tenant_id,document_id),CHECK((lifecycle='active' AND retired_at IS NULL AND deleted_at IS NULL) OR (lifecycle='retired' AND retired_at IS NOT NULL AND deleted_at IS NULL) OR (lifecycle='deleted' AND deleted_at IS NOT NULL)));
CREATE TABLE IF NOT EXISTS flowpilot.knowledge_document_versions(
 tenant_id text NOT NULL,document_id text NOT NULL,document_version bigint NOT NULL CHECK(document_version>=0),
 source_type text NOT NULL,source_ref text NOT NULL,source_version text,source_digest text NOT NULL CHECK(source_digest~'^sha256:[a-f0-9]{64}$'),
 acl jsonb NOT NULL CHECK(jsonb_typeof(acl)='object'),data_classification text NOT NULL,effective_at timestamptz NOT NULL,
 expires_at timestamptz CHECK(expires_at IS NULL OR expires_at>effective_at),content_ref text NOT NULL,
 content_hash text NOT NULL CHECK(content_hash~'^sha256:[a-f0-9]{64}$'),created_at timestamptz NOT NULL,
 PRIMARY KEY(tenant_id,document_id,document_version),FOREIGN KEY(tenant_id,document_id) REFERENCES flowpilot.knowledge_documents DEFERRABLE INITIALLY DEFERRED);
CREATE TABLE IF NOT EXISTS flowpilot.knowledge_content_bodies(
 tenant_id text NOT NULL,document_id text NOT NULL,document_version bigint NOT NULL,content_hash text NOT NULL CHECK(content_hash~'^sha256:[a-f0-9]{64}$'),content_body text NOT NULL,
 PRIMARY KEY(tenant_id,document_id,document_version),FOREIGN KEY(tenant_id,document_id,document_version) REFERENCES flowpilot.knowledge_document_versions DEFERRABLE INITIALLY DEFERRED);
CREATE TABLE IF NOT EXISTS flowpilot.knowledge_sections(
 tenant_id text NOT NULL,document_id text NOT NULL,document_version bigint NOT NULL,
 section_id text NOT NULL,section_ordinal bigint NOT NULL CHECK(section_ordinal>=0),
 content_ref text NOT NULL,content_hash text NOT NULL CHECK(content_hash~'^sha256:[a-f0-9]{64}$'),
 safe_metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(safe_metadata)='object'),
 PRIMARY KEY(tenant_id,document_id,document_version,section_id),
 UNIQUE(tenant_id,document_id,document_version,section_ordinal),
 FOREIGN KEY(tenant_id,document_id,document_version) REFERENCES flowpilot.knowledge_document_versions DEFERRABLE INITIALLY DEFERRED);
CREATE TABLE IF NOT EXISTS flowpilot.knowledge_inbox(
 tenant_id text NOT NULL,idempotency_key text NOT NULL,request_digest text NOT NULL CHECK(request_digest~'^sha256:[a-f0-9]{64}$'),receipt jsonb,
 claimed_at timestamptz NOT NULL DEFAULT transaction_timestamp(),completed_at timestamptz,PRIMARY KEY(tenant_id,idempotency_key),CHECK((receipt IS NULL)=(completed_at IS NULL)));
CREATE TABLE IF NOT EXISTS flowpilot.knowledge_outbox(
 tenant_id text NOT NULL,event_id text NOT NULL,event_type text NOT NULL,document_id text NOT NULL,document_version bigint NOT NULL,
 document_revision bigint NOT NULL,payload jsonb NOT NULL CHECK(jsonb_typeof(payload)='object'),occurred_at timestamptz NOT NULL,published_at timestamptz,
 PRIMARY KEY(tenant_id,event_id),FOREIGN KEY(tenant_id,document_id) REFERENCES flowpilot.knowledge_documents DEFERRABLE INITIALLY DEFERRED);
CREATE TABLE IF NOT EXISTS flowpilot.knowledge_index_jobs(
 tenant_id text NOT NULL,job_id text NOT NULL,document_id text NOT NULL,document_version bigint NOT NULL,document_revision bigint NOT NULL,
 content_hash text NOT NULL CHECK(content_hash~'^sha256:[a-f0-9]{64}$'),operation text NOT NULL CHECK(operation IN('upsert','remove','rebuild')),
 requested_at timestamptz NOT NULL,index_state text NOT NULL DEFAULT 'pending' CHECK(index_state IN('missing','pending','ready','failed','stale','removed')),
 indexed_at timestamptz,failure_code text,PRIMARY KEY(tenant_id,job_id),UNIQUE(tenant_id,document_id,document_version,document_revision,operation),
 FOREIGN KEY(tenant_id,document_id) REFERENCES flowpilot.knowledge_documents DEFERRABLE INITIALLY DEFERRED);
CREATE OR REPLACE VIEW flowpilot.knowledge_index_diagnostics AS
 SELECT DISTINCT ON(tenant_id,document_id,document_version) tenant_id,document_id,document_version,document_revision,content_hash,index_state,job_id AS last_job_id,indexed_at,failure_code
 FROM flowpilot.knowledge_index_jobs ORDER BY tenant_id,document_id,document_version,document_revision DESC,requested_at DESC,job_id DESC;
DO $rls$
DECLARE n text;
BEGIN
 FOREACH n IN ARRAY ARRAY['knowledge_documents','knowledge_document_versions','knowledge_content_bodies','knowledge_sections','knowledge_inbox','knowledge_outbox','knowledge_index_jobs'] LOOP
  EXECUTE format('ALTER TABLE flowpilot.%I ENABLE ROW LEVEL SECURITY',n); EXECUTE format('ALTER TABLE flowpilot.%I FORCE ROW LEVEL SECURITY',n);
  IF NOT EXISTS(SELECT 1 FROM pg_policies WHERE schemaname='flowpilot' AND tablename=n AND policyname='tenant_isolation') THEN
   EXECUTE format('CREATE POLICY tenant_isolation ON flowpilot.%I USING (tenant_id=flowpilot.current_tenant_id()) WITH CHECK (tenant_id=flowpilot.current_tenant_id())',n);
  END IF;
  EXECUTE format('REVOKE ALL ON flowpilot.%I FROM PUBLIC',n); EXECUTE format('GRANT SELECT,INSERT,UPDATE ON flowpilot.%I TO flowpilot_api,flowpilot_worker',n);
 END LOOP;
END $rls$;
GRANT DELETE ON flowpilot.knowledge_content_bodies,flowpilot.knowledge_sections TO flowpilot_api,flowpilot_worker;
REVOKE ALL ON flowpilot.knowledge_index_diagnostics FROM PUBLIC;
GRANT SELECT ON flowpilot.knowledge_index_diagnostics TO flowpilot_api,flowpilot_worker;
CREATE OR REPLACE FUNCTION flowpilot.reject_knowledge_version_mutation() RETURNS trigger LANGUAGE plpgsql AS $f$
BEGIN RAISE EXCEPTION 'knowledge versions are immutable' USING ERRCODE='55000'; END $f$;
DROP TRIGGER IF EXISTS knowledge_versions_immutable ON flowpilot.knowledge_document_versions;
CREATE TRIGGER knowledge_versions_immutable BEFORE UPDATE OR DELETE ON flowpilot.knowledge_document_versions FOR EACH ROW EXECUTE FUNCTION flowpilot.reject_knowledge_version_mutation();
REVOKE ALL ON FUNCTION flowpilot.reject_knowledge_version_mutation() FROM PUBLIC;
COMMIT;
