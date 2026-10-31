# Frozen edhiphy 1.0 dictionary and philosopher data (DATA_DIR/curated/v1).
V1_TABLES = $(CURATED)/v1/tables
DICT_PHILOSOPHERS = $(V1_TABLES)/Philosophers_table_v1.csv
DICT_VARIANTS = $(V1_TABLES)/Variants_table_v1.csv
DICT_WIKI = $(V1_TABLES)/Wiki_data_table_v1.csv
DICT_BIOGRAPHY = $(V1_TABLES)/Biographical_data_table_v1.csv
INSTITUTIONS = $(V1_TABLES)/Institutions_table_v1.csv
PHD = $(V1_TABLES)/PhD_Data_table_v1.csv
CLASSIFICATIONS = $(V1_TABLES)/Classifications_table_v0_5.csv
HIRING = $(V1_TABLES)/Hiring_data_table_v1.csv
# Corrections layer (issue #14): duplicate philosophers merged into one entry,
# entries dropped from the dictionary, variants added by hand.
DICT_MERGES = data/manual/philosopher_merges.csv
DICT_DROPS = data/manual/philosopher_drops.csv
DICT_VARIANT_ADDITIONS = data/manual/variant_additions.csv
# Birth and death years of the Wikidata entries (edhiphy.wikidata_dates,
# retrieved 2026-10-29) for unique labels (issue #9).
DICT_WIKI_DATES = $(CURATED)/wikidata/wikidata_dates_2026-10-29.csv
