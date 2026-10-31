# edhiphy build pipeline. Requires GNU Make >= 4.3 (on macOS: gmake).
#
#   make CORPUS=<corpus> DATA_DIR=<dir> [BUILD_DIR=<dir>] <target>
#
# A corpus (config/corpora/<corpus>.mk) lists its sources
# (config/sources/<source>.mk), its dictionary (config/dictionary/) and
# the files and parameters of each stage. Per-source outputs go to
# $(BUILD_DIR)/sources/<source>/, per-corpus outputs to
# $(BUILD_DIR)/corpora/<corpus>/. Inputs under DATA_DIR are only read.
# Every rule lists the module of its stage, so code changes rebuild the
# outputs that depend on them. See README.md, "Running the pipeline".

ifeq ($(filter grouped-target,$(.FEATURES)),)
$(error GNU Make >= 4.3 is required (macOS: use gmake))
endif

CORPUS ?= en_v1
DATA_DIR ?=
PYTHON ?= python3
# Path of the spellfix1 SQLite extension (set in the Docker image); empty:
# the web export gets a placeholder table.
SPELLFIX1 ?=
# Web search index: a word pair or triple is indexed only if it occurs in
# at least this many articles (documentation/search_index.md).
FTS_NGRAM_MIN_DF ?= 2
# Processes of the per-document stages (empty: all CPUs); extraction holds
# one spaCy pipeline per process (about 1 GB with the v1 dictionary).
WORKERS ?=
EXTRACT_WORKERS ?=
# Defaults of the text stages (a corpus may override them).
MENTIONS_FROM ?= pipeline
CONTEXT_CHARS ?= 100
DISAMBIGUATION_ALPHA ?= 0.01
DISAMBIGUATION_BETA ?= 0.25
# Sequence of disambiguation strategies (edhiphy.disambiguate): L (life
# dates, issue #16) after S1; T (recent mentions) is off by default and
# goes between S2 and S3 (S1,L,S2,T,S3,S4); the v1 sequence is S1,S2,S3,S4.
# T is off deliberately: a philosopher unmentioned for a year or a few is
# not thereby irrelevant; the field is too slow and corpora can be too
# small for that assumption.
DISAMBIGUATION_STRATEGIES ?= S1,L,S2,S3,S4
comma := ,
DISAMBIGUATION_MIN_AGE ?= 20
DISAMBIGUATION_WINDOW ?= 1
FALSE_POSITIVES ?= data/manual/v1/False_positives_0_mentions.csv
KNOWN_DEVIATIONS ?= data/manual/known_deviations.csv
LSA_DIMENSIONS ?= 300
LSA_MIN_DF ?= 5
LSA_MAX_DF ?= 0.5
SIMILAR_K ?= 20
# Language of the function words that admit an article to LSA (en, fr).
SIMILARITY_LANG ?= en

RAW = $(DATA_DIR)/raw
CURATED = $(DATA_DIR)/curated
REFERENCE = $(DATA_DIR)/reference
# Docker runs set BUILD_DIR=/data/build; native runs default to a separate
# tree so that the two never write the same files.
BUILD_DIR ?= $(if $(DATA_DIR),$(DATA_DIR)/build-native,$(error set DATA_DIR or BUILD_DIR))

export PYTHONPATH := $(CURDIR)/src
export PYTHONDONTWRITEBYTECODE := 1

VERSION := $(shell sed -n 's/^version = "\(.*\)"$$/\1/p' pyproject.toml)
GIT_COMMIT ?= $(shell git rev-parse HEAD 2>/dev/null)
GIT_DIRTY ?= $(if $(shell git status --porcelain --untracked-files=no 2>/dev/null),yes,no)

# Goals that need no corpus (and hence no DATA_DIR or BUILD_DIR).
STANDALONE_GOALS = test lint check-inputs
ifneq ($(filter-out $(STANDALONE_GOALS),$(or $(MAKECMDGOALS),all)),)

include config/corpora/$(CORPUS).mk
include $(foreach s,$(SOURCES),config/sources/$(s).mk)
include config/dictionary/$(DICTIONARY).mk

PKG = src/edhiphy
COMMON = $(PKG)/__init__.py $(PKG)/common.py
STAGE = $(PYTHON) -m edhiphy.

SRC_OUT = $(BUILD_DIR)/sources
OUT = $(BUILD_DIR)/corpora/$(CORPUS)
# Data release of a corpus (edhiphy-<name>-<version>, e.g. edhiphy-fr-0.1);
# the code version (VERSION) is recorded in Build_Info.
CORPUS_NAME ?= $(CORPUS)
CORPUS_VERSION ?= $(VERSION)
RELEASE = edhiphy-$(CORPUS_NAME)-$(CORPUS_VERSION)
DB = $(OUT)/$(RELEASE).sqlite
WEB_DB = $(OUT)/$(RELEASE)-web.sqlite
# yes: match and compute ambiguity with diacritics folded (French corpus).
FOLD_DIACRITICS ?= no
FOLD_ARG = $(if $(filter yes,$(FOLD_DIACRITICS)),--fold-diacritics)
METADATA = $(foreach s,$(SOURCES),$(SRC_OUT)/$(s)/metadata.parquet)
DOCS = $(foreach s,$(SOURCES),$(SRC_OUT)/$(s)/docs/_SUCCESS)

.DEFAULT_GOAL := all
.DELETE_ON_ERROR:
.SECONDEXPANSION:

all: ingest db web
ingest: $(DOCS)
db: $(DB)
web: $(WEB_DB)

# --- 1 ingest (per source) ---------------------------------------------

$(SRC_OUT)/%/metadata.parquet: $$(SRC_$$*_METADATA) $(PKG)/ingest.py $(COMMON)
	$(STAGE)ingest metadata --source $* --in $< --out $@

$(SRC_OUT)/%/docs/_SUCCESS: $$(SRC_$$*_FULLTEXT) $(PKG)/ingest.py $(COMMON)
	$(STAGE)ingest docs --source $* --out $(@D) $(SRC_$*_FULLTEXT)

# --- 2-5 select, journals, dictionary, authorship (per corpus) ----------

$(OUT)/articles.parquet: $(METADATA) $(SELECT_INPUTS) $(PKG)/select_articles.py $(COMMON)
	$(STAGE)select_articles $(SELECT_ARGS) --metadata $(METADATA) --out $@

JOURNALS_OUT = $(OUT)/journals.parquet $(OUT)/journal_variants.parquet \
	$(OUT)/article_journals.parquet
$(JOURNALS_OUT) &: $(OUT)/articles.parquet $(JOURNALS_TABLE) $(JOURNALS_VARIANTS) \
		$(PKG)/journals.py $(COMMON)
	$(STAGE)journals --articles $< \
		--journals $(JOURNALS_TABLE) --variants $(JOURNALS_VARIANTS) \
		--out-journals $(OUT)/journals.parquet \
		--out-variants $(OUT)/journal_variants.parquet \
		--out-article-journals $(OUT)/article_journals.parquet

DICT_OUT = $(addprefix $(OUT)/dictionary/,philosophers.parquet variants.parquet \
	wiki.parquet biography.parquet merges.parquet life_dates.parquet \
	ambiguity_changes.csv)
$(DICT_OUT) &: $(DICT_PHILOSOPHERS) $(DICT_VARIANTS) $(DICT_WIKI) $(DICT_BIOGRAPHY) \
		$(DICT_MERGES) $(DICT_DROPS) $(DICT_VARIANT_ADDITIONS) $(DICT_WIKI_DATES) \
		$(DICT_LAYER_LABELS) $(DICT_LAYER_PHILOSOPHERS) $(DICT_LAYER_AUTHORS) \
		$(DICT_LAYER_ISSUES) $(PKG)/dictionary.py $(PKG)/dictionary_layers.py $(PKG)/name_variants.py $(COMMON)
	$(STAGE)dictionary --philosophers $(DICT_PHILOSOPHERS) --variants $(DICT_VARIANTS) \
		--wiki $(DICT_WIKI) --biography $(DICT_BIOGRAPHY) \
		$(if $(DICT_MERGES),--merges $(DICT_MERGES)) \
		$(if $(DICT_DROPS),--drops $(DICT_DROPS)) \
		$(if $(DICT_VARIANT_ADDITIONS),--variant-additions $(DICT_VARIANT_ADDITIONS)) \
		$(if $(DICT_WIKI_DATES),--wiki-dates $(DICT_WIKI_DATES)) \
		$(if $(DICT_LAYER_LANG),--layer-lang $(DICT_LAYER_LANG)) \
		$(if $(DICT_LAYER_LABELS),--layer-labels $(DICT_LAYER_LABELS)) \
		$(if $(DICT_LAYER_PHILOSOPHERS),--layer-philosophers $(DICT_LAYER_PHILOSOPHERS)) \
		$(if $(DICT_LAYER_AUTHORS),--layer-authors $(DICT_LAYER_AUTHORS)) \
		$(if $(DICT_LAYER_ISSUES),--layer-issues $(DICT_LAYER_ISSUES)) \
		$(FOLD_ARG) --out-dir $(OUT)/dictionary \
		--out-changes $(OUT)/dictionary/ambiguity_changes.csv

AUTHORSHIP_OUT = $(OUT)/authorship.parquet $(OUT)/article_authors.parquet
$(AUTHORSHIP_OUT) &: $(OUT)/articles.parquet $(AUTHORSHIP_TABLE) $(DICT_OUT) \
		$(PKG)/authorship.py $(COMMON)
	$(STAGE)authorship --articles $< --authorship $(AUTHORSHIP_TABLE) \
		--merges $(OUT)/dictionary/merges.parquet \
		--out $(OUT)/authorship.parquet \
		--out-article-authors $(OUT)/article_authors.parquet

# --- 6 clean (per source), 7-9 extract, contexts, disambiguate (per corpus)

CLEAN = $(foreach s,$(SOURCES),$(SRC_OUT)/$(s)/clean/_SUCCESS)
CLEAN_DIRS = $(foreach s,$(SOURCES),$(SRC_OUT)/$(s)/clean)
LANGS = $(foreach s,$(SOURCES),$(SRC_$(s)_LANG))

$(SRC_OUT)/%/clean/_SUCCESS: $(SRC_OUT)/%/docs/_SUCCESS $(PKG)/clean.py $(COMMON)
	$(STAGE)clean --docs $(SRC_OUT)/$*/docs --rules $(SRC_$*_CLEAN) \
		$(if $(WORKERS),--workers $(WORKERS)) --out $(@D)

TEXT_OUT = $(OUT)/mentions.parquet $(OUT)/contexts.parquet $(OUT)/fulltexts.parquet
# The similarity stage writes its directory atomically, so one file stands
# for all its outputs.
SIMILARITY_OUT = $(OUT)/similarity/similarity.md
ifeq ($(MENTIONS_FROM),v1)
$(TEXT_OUT) &: $(OUT)/articles.parquet $(V1_MENTIONS) $(V1_CONTEXTS) $(V1_FULLTEXTS) \
		$(PKG)/import_v1.py $(COMMON)
	$(STAGE)import_v1 --articles $< \
		--mentions $(V1_MENTIONS) --contexts $(V1_CONTEXTS) --fulltexts $(V1_FULLTEXTS) \
		--out-mentions $(OUT)/mentions.parquet \
		--out-contexts $(OUT)/contexts.parquet \
		--out-fulltexts $(OUT)/fulltexts.parquet
else ifeq ($(MENTIONS_FROM),pipeline)
$(OUT)/raw_mentions.parquet: $(CLEAN) $(OUT)/articles.parquet $(OUT)/dictionary/variants.parquet \
		$(PKG)/extract.py $(PKG)/clean.py $(COMMON)
	$(STAGE)extract --clean $(CLEAN_DIRS) --langs $(LANGS) --articles $(OUT)/articles.parquet \
		--variants $(OUT)/dictionary/variants.parquet \
		$(if $(EXTRACT_WORKERS),--workers $(EXTRACT_WORKERS)) $(FOLD_ARG) --out $@

$(OUT)/contexts.parquet $(OUT)/fulltexts.parquet &: $(OUT)/raw_mentions.parquet $(CLEAN) \
		$(OUT)/articles.parquet $(PKG)/contexts.py $(COMMON)
	$(STAGE)contexts --clean $(CLEAN_DIRS) --articles $(OUT)/articles.parquet \
		--mentions $< --chars $(CONTEXT_CHARS) \
		--out-contexts $(OUT)/contexts.parquet --out-fulltexts $(OUT)/fulltexts.parquet

$(OUT)/mentions.parquet: $(OUT)/raw_mentions.parquet $(OUT)/authorship.parquet \
		$(OUT)/articles.parquet $(OUT)/dictionary/life_dates.parquet \
		$(FALSE_POSITIVES) $(PKG)/disambiguate.py $(COMMON)
	$(STAGE)disambiguate --mentions $< --authorship $(OUT)/authorship.parquet \
		--false-positives $(FALSE_POSITIVES) \
		--alpha $(DISAMBIGUATION_ALPHA) --beta $(DISAMBIGUATION_BETA) \
		--strategies $(DISAMBIGUATION_STRATEGIES) --articles $(OUT)/articles.parquet \
		--life-dates $(OUT)/dictionary/life_dates.parquet \
		--min-age $(DISAMBIGUATION_MIN_AGE) --window $(DISAMBIGUATION_WINDOW) --out $@
else
$(error MENTIONS_FROM=$(MENTIONS_FROM): use pipeline or v1)
endif

# --- 10 package, 11 export_web ------------------------------------------

BUILD_INFO = --info corpus=$(CORPUS) --info corpus_name=$(CORPUS_NAME) \
	--info corpus_version=$(CORPUS_VERSION) --info 'language=$(LANGS)' \
	--info 'sources=$(SOURCES)' \
	--info dictionary=$(DICTIONARY) --info mentions_from=$(MENTIONS_FROM) \
	$(if $(filter pipeline,$(MENTIONS_FROM)),--info context_chars=$(CONTEXT_CHARS) \
		--info disambiguation_alpha=$(DISAMBIGUATION_ALPHA) \
		--info disambiguation_beta=$(DISAMBIGUATION_BETA) \
		--info disambiguation_strategies=$(DISAMBIGUATION_STRATEGIES) \
		--info fold_diacritics=$(FOLD_DIACRITICS) \
		$(if $(filter L T,$(subst $(comma), ,$(DISAMBIGUATION_STRATEGIES))), \
			--info disambiguation_min_age=$(DISAMBIGUATION_MIN_AGE) \
			--info disambiguation_window=$(DISAMBIGUATION_WINDOW)) \
		--info 'clean_rules=$(foreach s,$(SOURCES),$(s):$(SRC_$(s)_CLEAN))') \
	--info lsa_dimensions=$(LSA_DIMENSIONS) --info similarity_lang=$(SIMILARITY_LANG) --info lsa_min_df=$(LSA_MIN_DF) \
	--info lsa_max_df=$(LSA_MAX_DF) --info similar_k=$(SIMILAR_K) \
	--info git_commit=$(GIT_COMMIT) --info git_dirty=$(GIT_DIRTY)

$(DB): $(OUT)/articles.parquet $(JOURNALS_OUT) $(DICT_OUT) $(AUTHORSHIP_OUT) $(TEXT_OUT) \
		$(SIMILARITY_OUT) $(INSTITUTIONS) $(PHD) $(CLASSIFICATIONS) $(HIRING) \
		$(PKG)/package.py $(PKG)/schema.py $(PKG)/build_info.py $(COMMON)
	$(STAGE)package --out $@ $(BUILD_INFO) \
		--articles $(OUT)/articles.parquet \
		--article-authors $(OUT)/article_authors.parquet \
		--article-journals $(OUT)/article_journals.parquet \
		--authorship $(OUT)/authorship.parquet \
		--journals $(OUT)/journals.parquet \
		--journal-variants $(OUT)/journal_variants.parquet \
		--philosophers $(OUT)/dictionary/philosophers.parquet \
		--variants $(OUT)/dictionary/variants.parquet \
		--wiki $(OUT)/dictionary/wiki.parquet \
		--biography $(OUT)/dictionary/biography.parquet \
		--mentions $(OUT)/mentions.parquet \
		--contexts $(OUT)/contexts.parquet \
		--fulltexts $(OUT)/fulltexts.parquet \
		--article-similarity $(OUT)/similarity/neighbours.parquet \
		--author-similarity $(OUT)/similarity/author_neighbours.parquet \
		--merges $(OUT)/dictionary/merges.parquet \
		--life-dates $(OUT)/dictionary/life_dates.parquet \
		--institutions $(INSTITUTIONS) --phd $(PHD) \
		--classifications $(CLASSIFICATIONS) --hiring $(HIRING)

$(WEB_DB): $(DB) $(PKG)/export_web.py $(PKG)/search_index.py $(PKG)/schema.py $(PKG)/build_info.py $(COMMON)
	$(STAGE)export_web --research $< --out $@ --tokenize '$(FTS_TOKENIZE)' \
		--ngram-min-df $(FTS_NGRAM_MIN_DF) $(if $(SPELLFIX1),--spellfix $(SPELLFIX1))

# Release checks of the web export (src/edhiphy/check_web.py) and the
# checksums of both databases.
check-web: $(OUT)/check-web.md
$(OUT)/check-web.md: $(WEB_DB) $(PKG)/check_web.py $(PKG)/schema.py $(COMMON)
	$(STAGE)check_web --web $< --context-chars $(CONTEXT_CHARS) --out $@

release: $(OUT)/$(RELEASE).sha256
$(OUT)/$(RELEASE).sha256: $(DB) $(WEB_DB) $(OUT)/check-web.md
	cd $(OUT) && if command -v sha256sum >/dev/null; \
		then sha256sum $(notdir $(DB) $(WEB_DB)); \
		else shasum -a 256 $(notdir $(DB) $(WEB_DB)); fi > $@.tmp && mv $@.tmp $@

# Table-by-table comparison with the database named by COMPARE_REF.
compare-basic: $(OUT)/compare-basic.md
$(OUT)/compare-basic.md: $(DB) $(COMPARE_REF) $(PKG)/compare_db.py $(COMMON)
	$(if $(COMPARE_REF),,$(error corpus $(CORPUS) defines no COMPARE_REF))
	$(STAGE)compare_db --ref $(COMPARE_REF) --new $(DB) --ignore Build_Info --out $@

# Article and author similarity: LSA over the cleaned texts and mention
# profiles (src/edhiphy/similarity.py); the neighbour lists go into the
# database (SIMILARITY_OUT, defined with TEXT_OUT).
similarity: $(SIMILARITY_OUT)
$(SIMILARITY_OUT): $(OUT)/fulltexts.parquet $(OUT)/mentions.parquet \
		$(OUT)/articles.parquet $(OUT)/authorship.parquet $(OUT)/dictionary/philosophers.parquet \
		$(PKG)/similarity.py $(COMMON)
	$(STAGE)similarity --fulltexts $(OUT)/fulltexts.parquet --mentions $(OUT)/mentions.parquet \
		--articles $(OUT)/articles.parquet --authorship $(OUT)/authorship.parquet \
		--philosophers $(OUT)/dictionary/philosophers.parquet --dimensions $(LSA_DIMENSIONS) \
		--lang $(SIMILARITY_LANG) \
		--min-df $(LSA_MIN_DF) --max-df $(LSA_MAX_DF) --k $(SIMILAR_K) --out-dir $(@D)

# Comparison of stages 6-9 with the v1 tables (Phase 3 report).
compare-v1: $(OUT)/compare-v1.md
$(OUT)/compare-v1.md $(OUT)/v1_mention_map.parquet &: $(OUT)/fulltexts.parquet \
		$(OUT)/raw_mentions.parquet $(OUT)/mentions.parquet $(OUT)/contexts.parquet \
		$(V1_FULLTEXTS) $(V1_MENTIONS) $(V1_CONTEXTS) $(KNOWN_DEVIATIONS) \
		$(PKG)/compare_v1.py $(COMMON)
	$(if $(filter pipeline,$(MENTIONS_FROM)),,$(error compare-v1 needs MENTIONS_FROM=pipeline))
	$(STAGE)compare_v1 --fulltexts $(OUT)/fulltexts.parquet \
		--raw-mentions $(OUT)/raw_mentions.parquet --mentions $(OUT)/mentions.parquet \
		--contexts $(OUT)/contexts.parquet --v1-fulltexts $(V1_FULLTEXTS) \
		--v1-mentions $(V1_MENTIONS) --v1-contexts $(V1_CONTEXTS) \
		--known-deviations $(KNOWN_DEVIATIONS) --context-chars $(CONTEXT_CHARS) \
		--out $(OUT)/compare-v1.md --out-map $(OUT)/v1_mention_map.parquet

# Remove the outputs of this corpus (not those of its sources).
clean:
	rm -rf $(OUT)

$(eval $(CORPUS_RULES))

endif # corpus goals

# --- checks (not part of all) -------------------------------------------

# Verify the DATA_DIR inputs against the checksum manifest.
check-inputs:
	$(if $(DATA_DIR),,$(error set DATA_DIR))
	cd $(DATA_DIR) && if command -v sha256sum >/dev/null; \
		then sha256sum --quiet -c $(CURDIR)/data/MANIFEST.sha256; \
		else shasum -a 256 --quiet -c $(CURDIR)/data/MANIFEST.sha256; fi

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m black --check src/edhiphy tests

.PHONY: all ingest db web similarity compare-basic compare-v1 check-web release \
	check-inputs test lint clean
