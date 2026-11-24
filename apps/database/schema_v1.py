"""Immutable initial policy/trigger migration. Add future changes as new migrations."""
from psycopg import sql

# Parent relationships are also used for RLS; every child policy traverses a protected parent.
PARENTS = {
 'oauthAccounts':('users','userId','id'), 'sessions':('users','userId','id'),
 'courseDocuments':('courses','courseId','id'), 'documentVersions':('documents','documentId','id'),
 'documentIndexes':('documentVersions','documentVersionId','id'), 'documentChunks':('documentIndexes','documentIndexId','id'),
 'runs':('courses','courseId','id'), 'runInputs':('runs','runId','id'), 'runDocuments':('runs','runId','id'),
 'runAttempts':('runs','runId','id'), 'runRevisions':('runs','runId','id'), 'revisionSources':('runRevisions','revisionId','id'),
 'reviews':('runRevisions','revisionId','id'), 'feedback':('runs','runId','id'),
 'courseStudents':('courses','courseId','id'), 'rubricDocuments':('courses','courseId','id'),
 'rubricVersions':('rubricDocuments','rubricDocumentId','id'), 'evaluationRuns':('runs','runId','id'),
 'evaluationSources':('evaluationRuns','runId','runId'), 'evaluationDrafts':('evaluationRuns','runId','runId'),
 'generatedMaterials':('courses','courseId','id'), 'generatedMaterialVersions':('generatedMaterials','generatedMaterialId','id'),
 'artifacts':('generatedMaterialVersions','generatedMaterialVersionId','id'), 'jobOutbox':('runs','runId','id'),
}
SCOPE_TABLES = ('courseDocuments','runs','runInputs','runDocuments','runRevisions','revisionSources','reviews','feedback',
                'evaluationRuns','evaluationSources','evaluationDrafts','generatedMaterialVersions')
IMMUTABLE = {
 'users':('id',), 'courses':('id','ownerId'), 'documents':('id','ownerId'),
 'courseDocuments':('courseId','documentId'), 'oauthAccounts':('id','userId','provider','issuer','subject'),
 'sessions':('id','userId','sessionTokenHash'), 'runs':('id','courseId','requestedBy','taskType','idempotencyKey','requestHash'),
 'runInputs':('runId','guidelines','syllabusSnapshot','taskConfig','generationConfig'),
 'runDocuments':('runId','documentVersionId','documentIndexId'), 'runAttempts':('id','runId','attemptNumber','phase'),
 'documentVersions':('id','documentId','versionNumber','originalFileName','storageKey','mimeType','byteSize','contentHash'),
 'documentIndexes':('id','documentVersionId','parserVersion','chunkingConfig','embeddingModel','embeddingDimensions'),
 'documentChunks':('id','documentIndexId','chunkNumber','pageNumber','text','textHash','embedding'),
 'runRevisions':('id','runId','revisionNumber','origin','content','generationConfig'),
 'revisionSources':('revisionId','chunkId','rank','retrievalScore','usageType'),
 'reviews':('id','revisionId','reviewerId','decision','feedback'), 'feedback':('id','runId','userId'),
 'courseStudents':('id','courseId'), 'rubricDocuments':('id','courseId'),
 'rubricVersions':('id','rubricDocumentId','versionNumber','origin','storageKey','contentHash'),
 'evaluationRuns':('runId','courseStudentId','rubricVersionId','repositoryUrl'),
 'evaluationSources':('id','runId','filePath','blobSha','sourceUrl'),
 'evaluationDrafts':('id','runId','versionNumber','storageKey','fileName','contentHash'),
 'generatedMaterials':('id','courseId','materialType'),
 'generatedMaterialVersions':('id','generatedMaterialId','versionNumber','runRevisionId','approvalReviewId','approvalDecision'),
 'artifacts':('id','generatedMaterialVersionId','fileRole','format','storageKey','byteSize','contentHash'),
 'jobOutbox':('id','runId','eventKey'), 'deletionJobs':('id','ownerId','targetType','targetId','storageKey'),
}


def install_policies_and_triggers(db, schema):
    ident = sql.Identifier
    for table, fields in IMMUTABLE.items():
        db.execute(sql.SQL('CREATE TRIGGER "freezeIdentity" BEFORE UPDATE ON {} FOR EACH ROW EXECUTE FUNCTION "freezeFields"({})').format(
            ident(table),sql.SQL(',').join(sql.Literal(f) for f in fields)))
    for table in SCOPE_TABLES:
        db.execute(sql.SQL('CREATE TRIGGER "validateScope" BEFORE INSERT OR UPDATE ON {} FOR EACH ROW EXECUTE FUNCTION "checkScope"()').format(ident(table)))
    for table in ('users','courses','runs','courseStudents','rubricDocuments','generatedMaterials','feedback'):
        db.execute(sql.SQL('CREATE TRIGGER "touchTimestamp" BEFORE UPDATE ON {} FOR EACH ROW EXECUTE FUNCTION "touchUpdatedAt"()').format(ident(table)))
    for table in ('documentVersions','documentIndexes','courseStudents','rubricVersions'):
        db.execute(sql.SQL('CREATE TRIGGER "deleteDependentResults" BEFORE DELETE ON {} FOR EACH ROW EXECUTE FUNCTION "deleteDependentRuns"()').format(ident(table)))
    for table in ('documentVersions','rubricVersions','evaluationDrafts','artifacts'):
        db.execute(sql.SQL('CREATE TRIGGER "enqueueFileDeletion" BEFORE DELETE ON {} FOR EACH ROW EXECUTE FUNCTION "queueDeletedFile"()').format(ident(table)))
    for table in ('courses','runs','courseStudents','rubricDocuments','generatedMaterials'):
        db.execute(sql.SQL('CREATE TRIGGER "courseChanged" AFTER INSERT OR UPDATE OR DELETE ON {} FOR EACH ROW EXECUTE FUNCTION "notifyCourseChange"()').format(ident(table)))
    for table in IMMUTABLE:
        if table=='users':
            predicate=sql.SQL('"id"="currentUserId"()')
        elif table in ('courses','documents','deletionJobs'):
            predicate=sql.SQL('"ownerId"="currentUserId"()')
        else:
            parent,fk,pk=PARENTS[table]
            predicate=sql.SQL('EXISTS (SELECT 1 FROM {} AS parent WHERE parent.{}={}.{})').format(ident(parent),ident(pk),ident(table),ident(fk))
        db.execute(sql.SQL('ALTER TABLE {} ENABLE ROW LEVEL SECURITY').format(ident(table)))
        db.execute(sql.SQL('ALTER TABLE {} FORCE ROW LEVEL SECURITY').format(ident(table)))
        db.execute(sql.SQL('CREATE POLICY "ownerAccess" ON {} USING ({}) WITH CHECK ({})').format(ident(table),predicate,predicate))
    db.execute(sql.SQL('REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM PUBLIC').format(ident(schema)))
    db.execute(sql.SQL('REVOKE ALL ON ALL SEQUENCES IN SCHEMA {} FROM PUBLIC').format(ident(schema)))
    db.execute(sql.SQL('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA {} FROM PUBLIC').format(ident(schema)))

