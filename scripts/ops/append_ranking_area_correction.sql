-- psql -X -v ON_ERROR_STOP=1 -v store_id=... -v code=... -v effective=...
--      -v center=... -v district=... -v old_area=... -v new_area=... -v reason=... -f ...
-- Targets exactly one imported version. Re-running the identical decision is harmless.
BEGIN;
SET LOCAL lock_timeout='5s';
SELECT pg_advisory_xact_lock(7342091101);
CREATE TEMP TABLE approved ON COMMIT DROP AS
SELECT o.mapping_version, o.store_id, o.service_store_code, o.source_hash,
       o.area_key old_key, o.area_name old_area, d.area_key new_key,
       d.area_name new_area, :'reason'::text reason
FROM ranking_store_org_history o JOIN (
    SELECT DISTINCT mapping_version,service_center_key,district_key,area_key,area_name
    FROM ranking_store_org_history WHERE area_name=:'new_area' AND area_key IS NOT NULL
) d USING(mapping_version,service_center_key,district_key)
WHERE o.store_id=:'store_id' AND o.service_store_code=:'code'
  AND o.service_center_name=:'center' AND o.district_name=:'district'
  AND o.area_name=:'old_area' AND o.effective_from=:'effective'::timestamptz;
DO $$ BEGIN IF (SELECT count(*) FROM approved) <> 1 THEN
  RAISE EXCEPTION 'Expected one source registration and one destination in the same roster';
END IF; END $$;
INSERT INTO ranking_area_corrections(mapping_version,store_id,service_store_code,source_hash,
    old_key,old_area,new_key,new_area,reason)
SELECT * FROM approved
ON CONFLICT (mapping_version,store_id) DO NOTHING;
DO $$ BEGIN IF EXISTS(SELECT * FROM approved EXCEPT
    SELECT mapping_version,store_id,service_store_code,source_hash,old_key,old_area,new_key,new_area,reason
    FROM ranking_area_corrections) THEN RAISE EXCEPTION 'Conflicting correction exists'; END IF; END $$;
SELECT store_id, old_area,new_area,reason FROM approved;
COMMIT;
