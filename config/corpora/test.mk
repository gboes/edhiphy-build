# Synthetic mini-corpus for tests and CI; needs no DATA_DIR. The inputs are
# generated into the build directory by tests/fixtures/mini_corpus.py.
FIXTURE = $(BUILD_DIR)/fixture
RAW = $(FIXTURE)/raw
CURATED = $(FIXTURE)/curated
REFERENCE = $(FIXTURE)/reference

SOURCES = test_a test_b
DICTIONARY = test
SELECT_INPUTS = $(CURATED)/tables/Articles_list.csv
SELECT_ARGS = --ids $(CURATED)/tables/Articles_list.csv --doc-subtype research-article
JOURNALS_TABLE = $(CURATED)/tables/Journals_table.csv
JOURNALS_VARIANTS = $(CURATED)/tables/Journals_variants.csv
AUTHORSHIP_TABLE = $(CURATED)/tables/Authorship_table.csv

# Stages 6-9 run on the fixture; the v1-format reference tables serve
# MENTIONS_FROM=v1 (import_v1).
MENTIONS_FROM = pipeline
V1_MENTIONS = $(REFERENCE)/Mentions_table.csv
V1_CONTEXTS = $(REFERENCE)/Mention_context_table.csv
V1_FULLTEXTS = $(REFERENCE)/Full_texts_table.csv

FTS_TOKENIZE = porter unicode61 remove_diacritics 2

FIXTURE_FILES = $(foreach s,$(SOURCES),$(SRC_$(s)_METADATA) $(SRC_$(s)_FULLTEXT)) \
	$(SELECT_INPUTS) $(JOURNALS_TABLE) $(JOURNALS_VARIANTS) $(AUTHORSHIP_TABLE) \
	$(DICT_PHILOSOPHERS) $(DICT_VARIANTS) $(DICT_WIKI) $(DICT_BIOGRAPHY) \
	$(INSTITUTIONS) $(PHD) $(CLASSIFICATIONS) $(HIRING) \
	$(V1_MENTIONS) $(V1_CONTEXTS) $(V1_FULLTEXTS)

define CORPUS_RULES
$(FIXTURE_FILES) &: tests/fixtures/mini_corpus.py
	$(PYTHON) tests/fixtures/mini_corpus.py $(FIXTURE)
endef

# LSA on four short articles: every word, two dimensions. All articles are
# shorter than similarity.MIN_WORDS, so only mention neighbours result.
LSA_DIMENSIONS = 2
LSA_MIN_DF = 1
LSA_MAX_DF = 1.0
SIMILAR_K = 2
