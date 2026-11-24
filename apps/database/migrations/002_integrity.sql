CREATE FUNCTION "currentUserId"() RETURNS uuid LANGUAGE sql STABLE
 SET search_path = "__schema__", pg_catalog
 AS $$ SELECT nullif(current_setting('app.userId', true),'')::uuid $$;

-- Reject changes to identity/scope keys and preserve version bodies once written.
CREATE FUNCTION "freezeFields"() RETURNS trigger LANGUAGE plpgsql
 SET search_path = "__schema__", pg_catalog AS $$
DECLARE field text;
BEGIN
 FOREACH field IN ARRAY TG_ARGV LOOP
  IF (to_jsonb(OLD)->field) IS DISTINCT FROM (to_jsonb(NEW)->field) THEN
   RAISE EXCEPTION 'immutable field: %', field USING ERRCODE='23514';
  END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE FUNCTION "touchUpdatedAt"() RETURNS trigger LANGUAGE plpgsql
 SET search_path = "__schema__", pg_catalog AS $$ BEGIN NEW."updatedAt"=clock_timestamp(); RETURN NEW; END $$;

CREATE FUNCTION "checkScope"() RETURNS trigger LANGUAGE plpgsql
 SET search_path = "__schema__", pg_catalog AS $$
DECLARE valid boolean := false;
BEGIN
 CASE TG_TABLE_NAME
 WHEN 'courseDocuments' THEN
  SELECT c."ownerId"=d."ownerId" INTO valid FROM "courses" c, "documents" d WHERE c.id=NEW."courseId" AND d.id=NEW."documentId";
 WHEN 'runs' THEN
  SELECT c."ownerId"=NEW."requestedBy" AND (NEW."parentRunId" IS NULL OR EXISTS (
   SELECT 1 FROM "runs" p WHERE p.id=NEW."parentRunId" AND p."courseId"=NEW."courseId" AND p."taskType"='manager'))
   INTO valid FROM "courses" c WHERE c.id=NEW."courseId";
 WHEN 'runInputs' THEN
  SELECT r."taskType" <> 'project' OR (NEW."guidelines"='' AND NEW."syllabusSnapshot"='' AND NEW."taskConfig"='{}'::jsonb)
   INTO valid FROM "runs" r WHERE r.id=NEW."runId";
 WHEN 'runDocuments' THEN
  SELECT r."requestedBy"=d."ownerId" AND r."taskType"<>'project' AND i.status='ready' AND EXISTS (
    SELECT 1 FROM "courseDocuments" cd WHERE cd."courseId"=r."courseId" AND cd."documentId"=d.id)
   INTO valid FROM "runs" r, "documentVersions" v JOIN "documents" d ON d.id=v."documentId",
   "documentIndexes" i WHERE r.id=NEW."runId" AND v.id=NEW."documentVersionId" AND i.id=NEW."documentIndexId" AND i."documentVersionId"=v.id;
 WHEN 'runRevisions' THEN
  SELECT r."taskType"<>'project' AND (NEW."createdBy" IS NULL OR NEW."createdBy"=r."requestedBy")
   INTO valid FROM "runs" r WHERE r.id=NEW."runId";
 WHEN 'revisionSources' THEN
  SELECT EXISTS (SELECT 1 FROM "runRevisions" r JOIN "runDocuments" d ON d."runId"=r."runId"
    JOIN "documentChunks" c ON c."documentIndexId"=d."documentIndexId" WHERE r.id=NEW."revisionId" AND c.id=NEW."chunkId") INTO valid;
 WHEN 'reviews' THEN
  SELECT r."requestedBy"=NEW."reviewerId" INTO valid FROM "runRevisions" v JOIN "runs" r ON r.id=v."runId" WHERE v.id=NEW."revisionId";
 WHEN 'feedback' THEN
  SELECT r."requestedBy"=NEW."userId" INTO valid FROM "runs" r WHERE r.id=NEW."runId";
 WHEN 'evaluationRuns' THEN
  SELECT r."taskType"='project' AND r."courseId"=s."courseId" AND r."courseId"=d."courseId"
    INTO valid FROM "runs" r, "courseStudents" s, "rubricVersions" v JOIN "rubricDocuments" d ON d.id=v."rubricDocumentId"
    WHERE r.id=NEW."runId" AND s.id=NEW."courseStudentId" AND v.id=NEW."rubricVersionId";
 WHEN 'evaluationSources' THEN
  SELECT e."commitSha" IS NOT NULL AND NEW."sourceUrl"=e."repositoryUrl"||'/blob/'||e."commitSha"||'/'||NEW."filePath"
    INTO valid FROM "evaluationRuns" e WHERE e."runId"=NEW."runId";
 WHEN 'evaluationDrafts' THEN
  SELECT e."commitSha" IS NOT NULL INTO valid FROM "evaluationRuns" e WHERE e."runId"=NEW."runId";
 WHEN 'generatedMaterialVersions' THEN
  SELECT m."courseId"=r."courseId" AND m."materialType"=CASE r."taskType"
    WHEN 'lecture' THEN 'lectureNote' WHEN 'exam' THEN 'examPaper' WHEN 'practice' THEN 'practiceNotebook' WHEN 'manager' THEN 'semesterPlan' END
   INTO valid FROM "generatedMaterials" m, "runRevisions" v JOIN "runs" r ON r.id=v."runId"
    WHERE m.id=NEW."generatedMaterialId" AND v.id=NEW."runRevisionId";
 END CASE;
 IF valid IS DISTINCT FROM true THEN RAISE EXCEPTION 'invalid ownership, scope or source relationship' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION "requireRunChildren"() RETURNS trigger LANGUAGE plpgsql
 SET search_path = "__schema__", pg_catalog AS $$
DECLARE run_key uuid;
BEGIN
 IF TG_TABLE_NAME='runs' THEN run_key=NEW.id; ELSE run_key=OLD."runId"; END IF;
 IF EXISTS (SELECT 1 FROM "runs" WHERE id=run_key) THEN
  IF NOT EXISTS (SELECT 1 FROM "runInputs" WHERE "runId"=run_key) OR
    EXISTS (SELECT 1 FROM "runs" r WHERE r.id=run_key AND r."taskType"='project' AND NOT EXISTS (
      SELECT 1 FROM "evaluationRuns" e WHERE e."runId"=r.id)) THEN
   RAISE EXCEPTION 'run requires inputs and project evaluation context' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER "runsRequireChildren" AFTER INSERT OR UPDATE ON "runs" DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION "requireRunChildren"();
CREATE CONSTRAINT TRIGGER "inputsRequireParentIntegrity" AFTER DELETE ON "runInputs" DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION "requireRunChildren"();
CREATE CONSTRAINT TRIGGER "evaluationsRequireParentIntegrity" AFTER DELETE ON "evaluationRuns" DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION "requireRunChildren"();

CREATE FUNCTION "deleteDependentRuns"() RETURNS trigger LANGUAGE plpgsql
 SET search_path = "__schema__", pg_catalog AS $$
BEGIN
 CASE TG_TABLE_NAME
 WHEN 'documentVersions' THEN
   DELETE FROM "runs" WHERE id IN (SELECT "runId" FROM "runDocuments" WHERE "documentVersionId"=OLD.id);
 WHEN 'documentIndexes' THEN
   DELETE FROM "runs" WHERE id IN (SELECT "runId" FROM "runDocuments" WHERE "documentIndexId"=OLD.id);
 WHEN 'courseStudents' THEN
   DELETE FROM "runs" WHERE id IN (SELECT "runId" FROM "evaluationRuns" WHERE "courseStudentId"=OLD.id);
 WHEN 'rubricVersions' THEN
   DELETE FROM "runs" WHERE id IN (SELECT "runId" FROM "evaluationRuns" WHERE "rubricVersionId"=OLD.id);
 END CASE;
 RETURN OLD;
END $$;

-- Keep file cleanup durable after relational rows are removed. A storage worker consumes these jobs.
-- ownerId is nullable for trusted maintenance deletions without an authenticated user context.
CREATE FUNCTION "queueDeletedFile"() RETURNS trigger LANGUAGE plpgsql
 SET search_path = "__schema__", pg_catalog AS $$
BEGIN
 INSERT INTO "deletionJobs" ("ownerId","targetType","targetId","storageKey")
 VALUES ("currentUserId"(), TG_TABLE_NAME, OLD.id, OLD."storageKey") ON CONFLICT ("storageKey") DO NOTHING;
 RETURN OLD;
END $$;
CREATE FUNCTION "notifyCourseChange"() RETURNS trigger LANGUAGE plpgsql
 SET search_path = "__schema__", pg_catalog AS $$
DECLARE payload jsonb; course_key text;
BEGIN
 IF TG_OP='DELETE' THEN payload=to_jsonb(OLD); ELSE payload=to_jsonb(NEW); END IF;
 IF TG_TABLE_NAME='courses' THEN course_key=payload->>'id'; ELSE course_key=payload->>'courseId'; END IF;
 PERFORM pg_notify('educator_'||md5(course_key),'changed');
 RETURN NULL;
END $$;
