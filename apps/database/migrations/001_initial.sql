-- Execute only through apps.database.migrate (transaction + schema-scoped search_path).
CREATE TABLE "users" (
 "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 "name" varchar(120) NOT NULL CHECK (length(btrim("name")) > 0),
 "department" varchar(160) NOT NULL CHECK (length(btrim("department")) > 0),
 "role" text NOT NULL DEFAULT 'professor' CHECK ("role" IN ('professor','admin')),
 "status" text NOT NULL DEFAULT 'active' CHECK ("status" IN ('active','suspended','deleting')),
 "createdAt" timestamptz NOT NULL DEFAULT now(), "updatedAt" timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE "oauthAccounts" (
 "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(), "userId" uuid NOT NULL REFERENCES "users" ON DELETE CASCADE,
 "provider" text NOT NULL DEFAULT 'google' CHECK ("provider" = 'google'),
 "issuer" text NOT NULL DEFAULT 'https://accounts.google.com' CHECK ("issuer" = 'https://accounts.google.com'),
 "subject" text NOT NULL CHECK (length("subject") BETWEEN 1 AND 255),
 "linkedAt" timestamptz NOT NULL DEFAULT now(), UNIQUE ("issuer","subject"), UNIQUE ("userId","provider")
);
CREATE TABLE "sessions" (
 "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(), "userId" uuid NOT NULL REFERENCES "users" ON DELETE CASCADE,
 "sessionTokenHash" text NOT NULL UNIQUE CHECK ("sessionTokenHash" ~ '^[a-f0-9]{64}$'),
 "expiresAt" timestamptz NOT NULL, "revokedAt" timestamptz, "createdAt" timestamptz NOT NULL DEFAULT now(),
 CHECK ("expiresAt" > "createdAt")
);
CREATE TABLE "courses" (
 "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(), "ownerId" uuid NOT NULL REFERENCES "users" ON DELETE CASCADE,
 "title" varchar(120) NOT NULL CHECK (length(btrim("title")) > 0), "syllabus" text NOT NULL DEFAULT '',
 "status" text NOT NULL DEFAULT 'active' CHECK ("status" IN ('active','archived','deleting')),
 "createdAt" timestamptz NOT NULL DEFAULT now(), "updatedAt" timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE "documents" (
 "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(), "ownerId" uuid NOT NULL REFERENCES "users" ON DELETE CASCADE,
 "title" varchar(180) NOT NULL CHECK (length(btrim("title")) > 0), "currentVersionId" uuid,
 "createdAt" timestamptz NOT NULL DEFAULT now(), "deletedAt" timestamptz
);
CREATE TABLE "courseDocuments" (
 "courseId" uuid NOT NULL REFERENCES "courses" ON DELETE CASCADE,
 "documentId" uuid NOT NULL REFERENCES "documents" ON DELETE CASCADE,
 "addedAt" timestamptz NOT NULL DEFAULT now(), PRIMARY KEY ("courseId","documentId")
);
CREATE TABLE "documentVersions" (
 "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(), "documentId" uuid NOT NULL REFERENCES "documents" ON DELETE CASCADE,
 "versionNumber" integer NOT NULL CHECK ("versionNumber">0), "originalFileName" varchar(255) NOT NULL,
 "storageKey" text NOT NULL UNIQUE CHECK ("storageKey" LIKE 'documents/%' AND "storageKey" NOT LIKE '%..%'),
 "mimeType" text NOT NULL, "byteSize" bigint NOT NULL CHECK ("byteSize">=0),
 "contentHash" text NOT NULL CHECK ("contentHash" ~ '^[a-f0-9]{64}$'), "createdAt" timestamptz NOT NULL DEFAULT now(),
 UNIQUE ("documentId","versionNumber"), UNIQUE ("documentId","id")
);
ALTER TABLE "documents" ADD CONSTRAINT "documentsCurrentVersionFk" FOREIGN KEY ("id","currentVersionId")
 REFERENCES "documentVersions" ("documentId","id") ON DELETE SET NULL ("currentVersionId") DEFERRABLE INITIALLY DEFERRED;
CREATE TABLE "documentIndexes" (
 "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(), "documentVersionId" uuid NOT NULL REFERENCES "documentVersions" ON DELETE CASCADE,
 "status" text NOT NULL DEFAULT 'processing' CHECK ("status" IN ('processing','ready','failed')),
 "parserVersion" text NOT NULL, "chunkingConfig" jsonb NOT NULL CHECK (jsonb_typeof("chunkingConfig")='object'),
 "embeddingModel" text NOT NULL DEFAULT 'text-embedding-3-small',
 "embeddingDimensions" integer NOT NULL DEFAULT 256 CHECK ("embeddingDimensions"=256),
 "errorCode" text, "createdAt" timestamptz NOT NULL DEFAULT now(), "completedAt" timestamptz,
 UNIQUE ("documentVersionId","id")
);
CREATE TABLE "documentChunks" (
 "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(), "documentIndexId" uuid NOT NULL REFERENCES "documentIndexes" ON DELETE CASCADE,
 "chunkNumber" integer NOT NULL CHECK ("chunkNumber">=0), "pageNumber" integer NOT NULL CHECK ("pageNumber">0),
 "text" text NOT NULL, "textHash" text NOT NULL CHECK ("textHash" ~ '^[a-f0-9]{64}$'),
 "embedding" public.vector(256), UNIQUE ("documentIndexId","chunkNumber")
);
CREATE TABLE "runs" (
 "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(), "courseId" uuid NOT NULL REFERENCES "courses" ON DELETE CASCADE,
 "requestedBy" uuid NOT NULL REFERENCES "users" ON DELETE CASCADE,
 "parentRunId" uuid REFERENCES "runs" ON DELETE SET NULL,
 "taskType" text NOT NULL CHECK ("taskType" IN ('manager','lecture','practice','exam','project')),
 "topic" varchar(200) NOT NULL CHECK (length(btrim("topic"))>0), "weekNumber" integer CHECK ("weekNumber" BETWEEN 1 AND 52),
 "status" text NOT NULL DEFAULT 'queued' CHECK ("status" IN ('queued','running','waitingReview','succeeded','failed','cancelled')),
 "currentRevisionId" uuid, "idempotencyKey" varchar(128) NOT NULL,
 "requestHash" text NOT NULL CHECK ("requestHash" ~ '^[a-f0-9]{64}$'),
 "createdAt" timestamptz NOT NULL DEFAULT now(), "updatedAt" timestamptz NOT NULL DEFAULT now(),
 UNIQUE ("requestedBy","courseId","idempotencyKey"), CHECK ("parentRunId" IS DISTINCT FROM "id"),
 CHECK ("taskType" <> 'project' OR ("currentRevisionId" IS NULL AND "status" <> 'waitingReview'))
);
CREATE TABLE "runInputs" (
 "runId" uuid PRIMARY KEY REFERENCES "runs" ON DELETE CASCADE, "guidelines" text NOT NULL DEFAULT '',
 "syllabusSnapshot" text NOT NULL DEFAULT '', "taskConfig" jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof("taskConfig")='object'),
 "generationConfig" jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof("generationConfig")='object')
);
CREATE TABLE "runDocuments" (
 "runId" uuid NOT NULL REFERENCES "runs" ON DELETE CASCADE,
 "documentVersionId" uuid NOT NULL REFERENCES "documentVersions" ON DELETE CASCADE,
 "documentIndexId" uuid NOT NULL,
 PRIMARY KEY ("runId","documentVersionId"),
 FOREIGN KEY ("documentVersionId","documentIndexId") REFERENCES "documentIndexes" ("documentVersionId","id") ON DELETE CASCADE
);
CREATE TABLE "runAttempts" (
 "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(), "runId" uuid NOT NULL REFERENCES "runs" ON DELETE CASCADE,
 "attemptNumber" integer NOT NULL CHECK ("attemptNumber">0), "phase" text NOT NULL CHECK ("phase" IN ('draft','revise','finalize','evaluate')),
 "status" text NOT NULL DEFAULT 'queued' CHECK ("status" IN ('queued','running','succeeded','failed','cancelled')),
 "queueMessageId" text, "leaseExpiresAt" timestamptz, "startedAt" timestamptz, "finishedAt" timestamptz, "errorCode" text,
 UNIQUE ("runId","attemptNumber"), CHECK ("finishedAt" IS NULL OR "startedAt" IS NULL OR "finishedAt">="startedAt")
);
CREATE TABLE "runRevisions" (
 "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(), "runId" uuid NOT NULL REFERENCES "runs" ON DELETE CASCADE,
 "revisionNumber" integer NOT NULL CHECK ("revisionNumber">0), "origin" text NOT NULL CHECK ("origin" IN ('professor','ai')),
 "createdBy" uuid REFERENCES "users" ON DELETE SET NULL, "content" jsonb NOT NULL,
 "generationConfig" jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof("generationConfig")='object'),
 "createdAt" timestamptz NOT NULL DEFAULT now(), UNIQUE ("runId","revisionNumber"), UNIQUE ("runId","id")
);
ALTER TABLE "runs" ADD CONSTRAINT "runsCurrentRevisionFk" FOREIGN KEY ("id","currentRevisionId")
 REFERENCES "runRevisions" ("runId","id") ON DELETE SET NULL ("currentRevisionId") DEFERRABLE INITIALLY DEFERRED;
CREATE TABLE "revisionSources" (
 "revisionId" uuid NOT NULL REFERENCES "runRevisions" ON DELETE CASCADE,
 "chunkId" uuid NOT NULL REFERENCES "documentChunks" ON DELETE CASCADE,
 "rank" integer NOT NULL CHECK ("rank">0), "retrievalScore" double precision,
 "usageType" text NOT NULL DEFAULT 'reference' CHECK ("usageType" IN ('reference','lectureMain','examEvidence')),
 PRIMARY KEY ("revisionId","chunkId")
);
CREATE TABLE "reviews" (
 "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(), "revisionId" uuid NOT NULL REFERENCES "runRevisions" ON DELETE CASCADE,
 "reviewerId" uuid NOT NULL REFERENCES "users" ON DELETE CASCADE,
 "decision" text NOT NULL CHECK ("decision" IN ('approve','revise')), "feedback" text NOT NULL DEFAULT '',
 "createdAt" timestamptz NOT NULL DEFAULT now(), CHECK ("decision" <> 'revise' OR length(btrim("feedback"))>0),
 UNIQUE ("id","revisionId","decision")
);
CREATE UNIQUE INDEX "reviewsSingleApproval" ON "reviews" ("revisionId") WHERE "decision"='approve';
CREATE TABLE "feedback" (
 "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(), "runId" uuid NOT NULL REFERENCES "runs" ON DELETE CASCADE,
 "userId" uuid NOT NULL REFERENCES "users" ON DELETE CASCADE, "rating" smallint NOT NULL CHECK ("rating" BETWEEN 1 AND 5),
 "comment" text NOT NULL DEFAULT '', "createdAt" timestamptz NOT NULL DEFAULT now(), "updatedAt" timestamptz NOT NULL DEFAULT now(),
 UNIQUE ("runId","userId")
);
CREATE TABLE "courseStudents" (
 "id" bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "courseId" uuid NOT NULL REFERENCES "courses" ON DELETE CASCADE,
 "studentNumber" varchar(64) NOT NULL CHECK (length(btrim("studentNumber"))>0),
 "name" varchar(120) NOT NULL CHECK (length(btrim("name"))>0),
 "githubId" varchar(39) DEFAULT NULL CHECK ("githubId" IS NULL OR "githubId" ~ '^[A-Za-z0-9][A-Za-z0-9-]{0,38}$'),
 "repositoryUrl" text DEFAULT NULL CHECK ("repositoryUrl" IS NULL OR "repositoryUrl" ~ '^https://github[.]com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'),
 "createdAt" timestamptz NOT NULL DEFAULT now(), "updatedAt" timestamptz NOT NULL DEFAULT now(),
 UNIQUE ("courseId","studentNumber")
);
CREATE TABLE "rubricDocuments" (
 "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(), "courseId" uuid NOT NULL REFERENCES "courses" ON DELETE CASCADE,
 "title" varchar(180) NOT NULL CHECK (length(btrim("title"))>0), "currentVersionId" uuid,
 "createdAt" timestamptz NOT NULL DEFAULT now(), "updatedAt" timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE "rubricVersions" (
 "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(), "rubricDocumentId" uuid NOT NULL REFERENCES "rubricDocuments" ON DELETE CASCADE,
 "versionNumber" integer NOT NULL CHECK ("versionNumber">0), "origin" text NOT NULL CHECK ("origin" IN ('professor','ai')),
 "storageKey" text NOT NULL UNIQUE CHECK ("storageKey" LIKE 'rubrics/%.md' AND "storageKey" NOT LIKE '%..%'),
 "contentHash" text NOT NULL CHECK ("contentHash" ~ '^[a-f0-9]{64}$'), "createdAt" timestamptz NOT NULL DEFAULT now(),
 UNIQUE ("rubricDocumentId","versionNumber"), UNIQUE ("rubricDocumentId","id")
);
ALTER TABLE "rubricDocuments" ADD CONSTRAINT "rubricsCurrentVersionFk" FOREIGN KEY ("id","currentVersionId")
 REFERENCES "rubricVersions" ("rubricDocumentId","id") ON DELETE SET NULL ("currentVersionId") DEFERRABLE INITIALLY DEFERRED;
CREATE TABLE "evaluationRuns" (
 "runId" uuid PRIMARY KEY REFERENCES "runs" ON DELETE CASCADE,
 "courseStudentId" bigint NOT NULL REFERENCES "courseStudents" ON DELETE CASCADE,
 "rubricVersionId" uuid NOT NULL REFERENCES "rubricVersions" ON DELETE CASCADE,
 "repositoryUrl" text NOT NULL CHECK ("repositoryUrl" ~ '^https://github[.]com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'),
 "commitSha" text CHECK ("commitSha" ~ '^([a-f0-9]{40}|[a-f0-9]{64})$')
);
CREATE TABLE "evaluationSources" (
 "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(), "runId" uuid NOT NULL REFERENCES "evaluationRuns" ON DELETE CASCADE,
 "filePath" text NOT NULL CHECK ("filePath" <> '' AND "filePath" !~ '(^/|(^|/)\.\.(/|$))'),
 "blobSha" text NOT NULL CHECK ("blobSha" ~ '^([a-f0-9]{40}|[a-f0-9]{64})$'),
 "sourceUrl" text NOT NULL CHECK ("sourceUrl" LIKE 'https://github.com/%'), UNIQUE ("runId","filePath")
);
CREATE TABLE "evaluationDrafts" (
 "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(), "runId" uuid NOT NULL REFERENCES "evaluationRuns" ON DELETE CASCADE,
 "versionNumber" integer NOT NULL CHECK ("versionNumber">0),
 "storageKey" text NOT NULL UNIQUE CHECK ("storageKey" LIKE 'evaluations/%.md' AND "storageKey" NOT LIKE '%..%'),
 "fileName" varchar(255) NOT NULL CHECK ("fileName" LIKE '%.md'),
 "contentHash" text NOT NULL CHECK ("contentHash" ~ '^[a-f0-9]{64}$'), "createdAt" timestamptz NOT NULL DEFAULT now(),
 UNIQUE ("runId","versionNumber")
);
CREATE TABLE "generatedMaterials" (
 "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(), "courseId" uuid NOT NULL REFERENCES "courses" ON DELETE CASCADE,
 "title" varchar(180) NOT NULL CHECK (length(btrim("title"))>0),
 "materialType" text NOT NULL CHECK ("materialType" IN ('lectureNote','practiceNotebook','examPaper','semesterPlan')),
 "currentVersionId" uuid, "createdAt" timestamptz NOT NULL DEFAULT now(), "updatedAt" timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE "generatedMaterialVersions" (
 "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(), "generatedMaterialId" uuid NOT NULL REFERENCES "generatedMaterials" ON DELETE CASCADE,
 "versionNumber" integer NOT NULL CHECK ("versionNumber">0), "runRevisionId" uuid NOT NULL REFERENCES "runRevisions" ON DELETE CASCADE,
 "approvalReviewId" uuid NOT NULL, "approvalDecision" text NOT NULL DEFAULT 'approve' CHECK ("approvalDecision"='approve'),
 "createdAt" timestamptz NOT NULL DEFAULT now(),
 UNIQUE ("generatedMaterialId","versionNumber"), UNIQUE ("generatedMaterialId","id"),
 FOREIGN KEY ("approvalReviewId","runRevisionId","approvalDecision") REFERENCES "reviews" ("id","revisionId","decision") ON DELETE CASCADE
);
ALTER TABLE "generatedMaterials" ADD CONSTRAINT "materialsCurrentVersionFk" FOREIGN KEY ("id","currentVersionId")
 REFERENCES "generatedMaterialVersions" ("generatedMaterialId","id") ON DELETE SET NULL ("currentVersionId") DEFERRABLE INITIALLY DEFERRED;
CREATE TABLE "artifacts" (
 "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(), "generatedMaterialVersionId" uuid NOT NULL REFERENCES "generatedMaterialVersions" ON DELETE CASCADE,
 "fileRole" text NOT NULL CHECK ("fileRole" IN ('main','questionPaper','answerKey','gradingRubric')),
 "format" text NOT NULL CHECK ("format" IN ('md','pdf','pptx','ipynb','docx')),
 "storageKey" text NOT NULL UNIQUE CHECK ("storageKey" LIKE 'artifacts/%' AND "storageKey" NOT LIKE '%..%'),
 "byteSize" bigint NOT NULL CHECK ("byteSize">=0), "contentHash" text NOT NULL CHECK ("contentHash" ~ '^[a-f0-9]{64}$'),
 "createdAt" timestamptz NOT NULL DEFAULT now(), UNIQUE ("generatedMaterialVersionId","fileRole","format")
);
CREATE TABLE "jobOutbox" (
 "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(), "runId" uuid NOT NULL REFERENCES "runs" ON DELETE CASCADE,
 "eventKey" text NOT NULL UNIQUE, "status" text NOT NULL DEFAULT 'pending' CHECK ("status" IN ('pending','publishing','published','failed')),
 "attemptCount" integer NOT NULL DEFAULT 0 CHECK ("attemptCount">=0), "availableAt" timestamptz NOT NULL DEFAULT now(),
 "publishedAt" timestamptz, "createdAt" timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE "deletionJobs" (
 "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(), "ownerId" uuid,
 "targetType" text NOT NULL, "targetId" uuid NOT NULL, "storageKey" text NOT NULL UNIQUE,
 "status" text NOT NULL DEFAULT 'pending' CHECK ("status" IN ('pending','deleting','completed','failed')),
 "attemptCount" integer NOT NULL DEFAULT 0 CHECK ("attemptCount">=0), "errorCode" text,
 "createdAt" timestamptz NOT NULL DEFAULT now(), "completedAt" timestamptz
);
CREATE INDEX "coursesOwnerCreated" ON "courses" ("ownerId","createdAt" DESC);
CREATE INDEX "documentsOwnerCreated" ON "documents" ("ownerId","createdAt" DESC);
CREATE INDEX "courseDocumentsDocument" ON "courseDocuments" ("documentId");
CREATE INDEX "sessionsUser" ON "sessions" ("userId");
CREATE INDEX "sessionsExpires" ON "sessions" ("expiresAt");
CREATE INDEX "documentIndexesVersion" ON "documentIndexes" ("documentVersionId");
CREATE INDEX "documentChunksEmbedding" ON "documentChunks" USING hnsw ("embedding" public.vector_cosine_ops) WHERE "embedding" IS NOT NULL;
CREATE INDEX "runsCourseStatusCreated" ON "runs" ("courseId","status","createdAt" DESC);
CREATE INDEX "runsParent" ON "runs" ("parentRunId");
CREATE INDEX "runDocumentsVersion" ON "runDocuments" ("documentVersionId","runId");
CREATE INDEX "runDocumentsIndex" ON "runDocuments" ("documentIndexId");
CREATE INDEX "runAttemptsStatusLease" ON "runAttempts" ("status","leaseExpiresAt");
CREATE INDEX "revisionSourcesChunk" ON "revisionSources" ("chunkId");
CREATE INDEX "rubricDocumentsCourse" ON "rubricDocuments" ("courseId","updatedAt" DESC);
CREATE INDEX "evaluationRunsStudent" ON "evaluationRuns" ("courseStudentId");
CREATE INDEX "evaluationRunsRubric" ON "evaluationRuns" ("rubricVersionId");
CREATE INDEX "materialsCourseTypeCreated" ON "generatedMaterials" ("courseId","materialType","createdAt" DESC);
CREATE INDEX "materialVersionsRevision" ON "generatedMaterialVersions" ("runRevisionId");
CREATE INDEX "jobOutboxDispatch" ON "jobOutbox" ("status","availableAt");
CREATE INDEX "deletionJobsPending" ON "deletionJobs" ("status","createdAt");
