-- Canonical editable syllabus; independent from document/vector indexes.
CREATE TABLE "coursePlans" (
 "courseId" uuid PRIMARY KEY REFERENCES courses ON DELETE CASCADE,
 "goals" text NOT NULL DEFAULT '',
 "mainTextbooks" text NOT NULL DEFAULT '',
 "supplementaryTextbooks" text NOT NULL DEFAULT '',
 "revision" integer NOT NULL DEFAULT 1 CHECK (revision > 0),
 "updatedAt" timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE "courseWeeks" ADD COLUMN "content" text NOT NULL DEFAULT '';
ALTER TABLE "coursePlans" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "coursePlans" FORCE ROW LEVEL SECURITY;
CREATE POLICY "ownerAccess" ON "coursePlans" USING (EXISTS (SELECT 1 FROM courses c WHERE c.id="courseId"));
CREATE TRIGGER "freezeIdentity" BEFORE UPDATE ON "coursePlans" FOR EACH ROW EXECUTE FUNCTION "freezeFields"('courseId');
CREATE TRIGGER "touchUpdatedAt" BEFORE UPDATE ON "coursePlans" FOR EACH ROW EXECUTE FUNCTION "touchUpdatedAt"();
CREATE TRIGGER "courseChanged" AFTER INSERT OR UPDATE OR DELETE ON "coursePlans" FOR EACH ROW EXECUTE FUNCTION "notifyCourseChange"();
