# Dictionary of the synthetic mini-corpus with a French layer (written by
# the fixture rule of config/corpora/test_fr.mk).
include config/dictionary/test.mk
DICT_LAYER_LANG = fr
DICT_LAYER_LABELS = $(CURATED)/wikidata/labels_fr.csv
DICT_LAYER_PHILOSOPHERS = $(CURATED)/wikidata/philosophers_fr.csv
DICT_LAYER_AUTHORS = $(CURATED)/fr/authors_fr.csv
DICT_WIKI_DATES = $(CURATED)/wikidata/dates_fr.csv
