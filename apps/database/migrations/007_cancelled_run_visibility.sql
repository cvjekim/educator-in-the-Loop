-- Retain cancelled work and its audit records, but remove it from user lists.
ALTER TABLE runs ADD COLUMN "deleteYn" boolean NOT NULL DEFAULT false;
CREATE INDEX "visibleRunsByCourse" ON runs ("courseId","createdAt" DESC) WHERE NOT "deleteYn";
UPDATE runs SET "deleteYn"=true WHERE status='cancelled';
