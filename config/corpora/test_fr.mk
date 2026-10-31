# Synthetic French mini-corpus for tests and CI (as config/corpora/fr.mk);
# needs no DATA_DIR. The inputs are generated into the build directory by
# tests/fixtures/mini_corpus_fr.py.
FIXTURE = $(BUILD_DIR)/fixture_fr
RAW = $(FIXTURE)/raw
CURATED = $(FIXTURE)/curated
REFERENCE = $(FIXTURE)/reference

CORPUS_NAME = test-fr
CORPUS_VERSION = 0.1
SOURCES = test_fr
DICTIONARY = test_fr
SELECT_INPUTS =
SELECT_ARGS = --doc-subtype research-article
JOURNALS_TABLE = $(CURATED)/tables/Journals_fr.csv
JOURNALS_VARIANTS = $(CURATED)/tables/Journals_fr_variants.csv
AUTHORSHIP_TABLE = $(CURATED)/fr/authorship_fr.csv

MENTIONS_FROM = pipeline
FOLD_DIACRITICS = yes
FTS_TOKENIZE = unicode61 remove_diacritics 2
# LSA among French articles (similarity.FRENCH function words).
SIMILARITY_LANG = fr

FIXTURE_FILES = $(foreach s,$(SOURCES),$(SRC_$(s)_METADATA) $(SRC_$(s)_FULLTEXT)) \
	$(JOURNALS_TABLE) $(JOURNALS_VARIANTS) $(AUTHORSHIP_TABLE) \
	$(DICT_PHILOSOPHERS) $(DICT_VARIANTS) $(DICT_WIKI) $(DICT_BIOGRAPHY) \
	$(DICT_LAYER_LABELS) $(DICT_LAYER_PHILOSOPHERS) $(DICT_LAYER_AUTHORS) \
	$(DICT_WIKI_DATES) $(INSTITUTIONS) $(PHD) $(CLASSIFICATIONS) $(HIRING)

define CORPUS_RULES
$(FIXTURE_FILES) &: tests/fixtures/mini_corpus_fr.py tests/fixtures/mini_corpus.py
	$(PYTHON) tests/fixtures/mini_corpus_fr.py $(FIXTURE)
endef

LSA_DIMENSIONS = 2
LSA_MIN_DF = 1
LSA_MAX_DF = 1.0
SIMILAR_K = 2
