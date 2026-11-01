-- Run once on tower to support the /grinding history filter and anti-join.
ALTER TABLE `tower`.`lista_formowania_historia_v2`
    ADD INDEX IF NOT EXISTS `idx_history_stage_casting`
        (`production_stage`, `produkt_id`, `prefix`, `sn`),
    ALGORITHM=INPLACE, LOCK=NONE;

ALTER TABLE `tower`.`lista_formowania_sn`
    ADD INDEX IF NOT EXISTS `idx_grinding_form_serial` (`produkt_id`, `prefix`, `sn`),
    ALGORITHM=INPLACE, LOCK=NONE;

ALTER TABLE `tower`.`grinding`
    ADD INDEX IF NOT EXISTS `idx_grinding_casting` (`item_id`, `prefix`, `sn`),
    ALGORITHM=INPLACE, LOCK=NONE;
