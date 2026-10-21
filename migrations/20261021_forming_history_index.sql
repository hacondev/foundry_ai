-- Run once on tower. Online creation avoids blocking normal table writes.
ALTER TABLE `tower`.`lista_formowania_historia_v2`
    ADD INDEX IF NOT EXISTS `idx_forming_history_product_stage_serial`
        (`produkt_id`, `production_stage`, `sn`, `prefix`),
    ALGORITHM=INPLACE, LOCK=NONE;
