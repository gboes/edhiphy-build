# French corpus (edhiphy-fr): all research articles of the French JSTOR
# delivery, from all 37 titles and in all languages (decided 2026-10-29);
# the language of each article is in JSTOR_Article.language. Journals:
# data/manual/journals_fr.csv (title lineages grouped).
ifeq ($(DATA_DIR),)
$(error corpus fr needs DATA_DIR)
endif

CORPUS_NAME = fr
CORPUS_VERSION = 0.1
SOURCES = jstor_fr_2024
DICTIONARY = v1_fr
SELECT_INPUTS =
SELECT_ARGS = --doc-subtype research-article
JOURNALS_TABLE = data/manual/journals_fr.csv
JOURNALS_VARIANTS = data/manual/journals_fr_variants.csv
# Result of edhiphy.jstor_authors: the creators of the research articles
# matched to the dictionary (review sheet for experts in the same folder).
AUTHORSHIP_TABLE = $(CURATED)/fr/jstor_authorship_fr_2026-10-29.csv

MENTIONS_FROM = pipeline
# OCR often loses accents ("Levinas", "etude"): stage 7 matches folded
# texts against folded variants; the dictionary computes ambiguity alike.
FOLD_DIACRITICS = yes
# No English stemmer; diacritics folded as in matching.
FTS_TOKENIZE = unicode61 remove_diacritics 2
# LSA among French articles (similarity.FRENCH function words).
SIMILARITY_LANG = fr
