ALTER TABLE article_acquisition_tasks
ADD COLUMN work_class TEXT NOT NULL DEFAULT 'backfill';

ALTER TABLE intelligence_workload_limits
ADD COLUMN max_fresh_active_per_key INTEGER NOT NULL DEFAULT 2;

ALTER TABLE intelligence_workload_limits
ADD COLUMN max_fresh_active_global INTEGER NOT NULL DEFAULT 10;

CREATE INDEX idx_article_acquisition_tasks_work_class
ON article_acquisition_tasks(work_class,status,next_attempt_at,id);
