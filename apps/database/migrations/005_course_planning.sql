CREATE TABLE "courseWeeks" (
 "courseId" uuid NOT NULL REFERENCES courses ON DELETE CASCADE,
 "weekNumber" integer NOT NULL CHECK ("weekNumber" BETWEEN 1 AND 52),
 "topic" varchar(200) NOT NULL CHECK (length(btrim(topic))>0),
 "objectives" text NOT NULL DEFAULT '',
 PRIMARY KEY ("courseId","weekNumber")
);
CREATE TABLE "courseDocumentWeeks" (
 "courseId" uuid NOT NULL, "documentId" uuid NOT NULL, "weekNumber" integer NOT NULL,
 PRIMARY KEY ("courseId","documentId","weekNumber"),
 FOREIGN KEY ("courseId","documentId") REFERENCES "courseDocuments" ON DELETE CASCADE,
 FOREIGN KEY ("courseId","weekNumber") REFERENCES "courseWeeks" ON DELETE CASCADE
);
ALTER TABLE courses ADD COLUMN "syllabusVersionId" uuid REFERENCES "documentVersions" ON DELETE SET NULL;
CREATE FUNCTION "checkSyllabus"() RETURNS trigger LANGUAGE plpgsql
 SET search_path = "__schema__", pg_catalog AS $$ BEGIN
 IF NEW."syllabusVersionId" IS NOT NULL AND NOT EXISTS (
  SELECT 1 FROM "documentVersions" v JOIN documents d ON d.id=v."documentId"
  JOIN "courseDocuments" cd ON cd."documentId"=d.id
  WHERE v.id=NEW."syllabusVersionId" AND cd."courseId"=NEW.id AND d."ownerId"=NEW."ownerId"
 ) THEN RAISE EXCEPTION 'syllabus must belong to this course owner and be linked' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER "courseSyllabusScope" BEFORE INSERT OR UPDATE ON courses FOR EACH ROW EXECUTE FUNCTION "checkSyllabus"();
ALTER TABLE "courseWeeks" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "courseWeeks" FORCE ROW LEVEL SECURITY;
CREATE POLICY "ownerAccess" ON "courseWeeks" USING (EXISTS (SELECT 1 FROM courses c WHERE c.id="courseId"));
ALTER TABLE "courseDocumentWeeks" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "courseDocumentWeeks" FORCE ROW LEVEL SECURITY;
CREATE POLICY "ownerAccess" ON "courseDocumentWeeks" USING (EXISTS (SELECT 1 FROM courses c WHERE c.id="courseId"));
CREATE TRIGGER "freezeIdentity" BEFORE UPDATE ON "courseWeeks" FOR EACH ROW EXECUTE FUNCTION "freezeFields"('courseId','weekNumber');
CREATE TRIGGER "freezeIdentity" BEFORE UPDATE ON "courseDocumentWeeks" FOR EACH ROW EXECUTE FUNCTION "freezeFields"('courseId','documentId','weekNumber');
CREATE TRIGGER "courseChanged" AFTER INSERT OR UPDATE OR DELETE ON "courseWeeks" FOR EACH ROW EXECUTE FUNCTION "notifyCourseChange"();
CREATE TRIGGER "courseChanged" AFTER INSERT OR UPDATE OR DELETE ON "courseDocuments" FOR EACH ROW EXECUTE FUNCTION "notifyCourseChange"();
CREATE TRIGGER "courseChanged" AFTER INSERT OR UPDATE OR DELETE ON "courseDocumentWeeks" FOR EACH ROW EXECUTE FUNCTION "notifyCourseChange"();
