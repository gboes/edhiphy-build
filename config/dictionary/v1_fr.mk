# The v1 dictionary with its corrections (config/dictionary/v1.mk) and the
# French layer (edhiphy.dictionary_layers): French Wikidata labels and
# aliases of the dictionary entries, philosophers of French-language
# traditions not in v1 (edhiphy.wikidata_philosophers) and the French JSTOR
# authors not found in the dictionary (edhiphy.jstor_authors). Phi_IDs of
# the v1 entries are those of the English corpus.
include config/dictionary/v1.mk
WIKIDATA = $(CURATED)/wikidata
DICT_LAYER_LANG = fr
DICT_LAYER_LABELS = $(WIKIDATA)/wikidata_labels_fr_2026-10-29.csv \
	$(WIKIDATA)/wikidata_labels_fr_new_2026-10-29.csv
DICT_LAYER_PHILOSOPHERS = $(WIKIDATA)/wikidata_philosophers_fr_2026-10-29.csv
DICT_LAYER_AUTHORS = $(CURATED)/fr/jstor_authors_fr_2026-10-29.csv
# Given names, places and common words that are valid one-word variants
# but mostly something else in French texts (to be extended by experts).
DICT_LAYER_ISSUES = data/manual/variant_issues_fr.csv
DICT_WIKI_DATES += $(WIKIDATA)/wikidata_dates_fr_new_2026-10-29.csv
