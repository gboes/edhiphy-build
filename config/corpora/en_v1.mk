# English corpus of edhiphy 1.0: the 22,977 research articles of the v1
# database, selected by the explicit v1 article list (the delivery has
# 23,351 research articles; v1 did not record why 374 were left out).
ifeq ($(DATA_DIR),)
$(error corpus en_v1 needs DATA_DIR)
endif

CORPUS_NAME = en
CORPUS_VERSION = 2.0
SOURCES = jstor_ee_2023
DICTIONARY = v1
SELECT_INPUTS = $(CURATED)/v1/tables/Articles_table_v1.csv
SELECT_ARGS = --ids $(CURATED)/v1/tables/Articles_table_v1.csv
JOURNALS_TABLE = $(CURATED)/v1/tables/Journals_table_v1.csv
JOURNALS_VARIANTS = $(CURATED)/v1/tables/Journals_variants_v1.csv
AUTHORSHIP_TABLE = $(CURATED)/v1/tables/Authorship_table_v1.csv

# Mentions, contexts and cleaned texts from stages 6-9 (pipeline); with
# MENTIONS_FROM=v1 on the command line, the v1 tables below are used
# instead. The v1 tables are also the reference of compare-v1.
MENTIONS_FROM = pipeline
V1_MENTIONS = $(REFERENCE)/v1/Mentions_table_v1.csv
V1_CONTEXTS = $(REFERENCE)/v1/Mention_context_table_v1.csv
V1_FULLTEXTS = $(REFERENCE)/v1/Full_texts_table_v1.csv

FTS_TOKENIZE = porter unicode61 remove_diacritics 2

# Reference for compare-basic: the v1 database (without Full_Text).
COMPARE_REF = $(REFERENCE)/v1/edhiphy-basic.sqlite
