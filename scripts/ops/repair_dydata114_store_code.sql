-- psql -v store_id=... -v store_code=... -v poi_id=... -v apply=false -f ...
-- Save the original target row in a restricted production evidence file first.
-- Default is a rollback preview. No source/organization/POI records are changed.
\set ON_ERROR_STOP on
\if :{?apply}
\else
\set apply false
\endif
BEGIN;
SET LOCAL statement_timeout = '15s';
SET LOCAL lock_timeout = '2s';
CREATE TEMP TABLE repair_input ON COMMIT DROP AS
SELECT :'store_id'::text AS store_id, :'store_code'::text AS store_code,
       :'poi_id'::text AS poi_id;
LOCK TABLE dim_stores IN SHARE ROW EXCLUSIVE MODE;
DO $repair$
DECLARE
    target repair_input%ROWTYPE;
    previous_code text;
BEGIN
    SELECT * INTO STRICT target FROM repair_input;
    IF target.store_code = '' OR target.store_id = '' OR target.poi_id = '' THEN
        RAISE EXCEPTION 'Repair identifiers must be nonempty';
    END IF;
    SELECT service_store_code INTO STRICT previous_code FROM dim_stores
    WHERE store_id = target.store_id;
    IF previous_code IS NOT NULL AND previous_code <> target.store_code THEN
        RAISE EXCEPTION 'Existing store code differs; refusing overwrite';
    END IF;
    IF EXISTS (SELECT 1 FROM dim_stores WHERE store_id <> target.store_id
               AND service_store_code = target.store_code) THEN
        RAISE EXCEPTION 'Store code is occupied by another store';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM dim_store_poi_mappings
                   WHERE store_id = target.store_id AND poi_id = target.poi_id)
       OR EXISTS (SELECT 1 FROM dim_store_poi_mappings
                  WHERE store_id <> target.store_id AND poi_id = target.poi_id) THEN
        RAISE EXCEPTION 'POI mapping does not identify target exclusively';
    END IF;
    IF (SELECT service_store_code FROM ranking_store_org_history
        WHERE store_id = target.store_id ORDER BY effective_from DESC LIMIT 1)
        IS DISTINCT FROM target.store_code THEN
        RAISE EXCEPTION 'Latest organization code does not corroborate repair';
    END IF;
    UPDATE dim_stores SET service_store_code = target.store_code,
                          updated_at = now()
    WHERE store_id = target.store_id AND service_store_code IS NULL;
END
$repair$;
SELECT s.store_id, s.service_store_code FROM dim_stores s
JOIN repair_input i USING (store_id);
\if :apply
COMMIT;
\else
ROLLBACK;
\endif
