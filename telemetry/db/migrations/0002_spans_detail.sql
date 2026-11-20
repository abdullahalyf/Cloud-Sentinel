-- 0002: the spans.detail column (for databases made before 4 Nov). Safe to run twice.
alter table spans add column if not exists detail text not null default '{}';