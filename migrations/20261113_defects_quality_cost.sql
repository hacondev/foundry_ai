-- Apply before deploying quality cost calculations. Preserve existing NULL values.
ALTER TABLE defects
    MODIFY COLUMN koszt_zlej_jakowsci DECIMAL(10,2) NULL DEFAULT NULL;
