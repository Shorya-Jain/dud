-- The registry's verdict reasons for each reading (rules that failed or had no value).
ALTER TABLE readings ADD COLUMN verdict_json TEXT;
