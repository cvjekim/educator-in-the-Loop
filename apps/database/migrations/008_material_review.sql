-- One version-bound report, not student scores or normalized rubric criteria.
ALTER TABLE "generatedMaterialVersions" ADD COLUMN "educationReview" jsonb;
