# edhiphy/build

Builds the edhiphy database of philosopher mentions by running a 
dictionary ('gazetteer'' ) of philosopher names and variants against a article 
full texts. The creation of database, gazetteer, and the original
disambiguation strategies are described in   Petrovich, E., Verhaegh, S., 
Bös, G., Cristalli, C., Dewulf, F.,  van Gemert, T., & IJdens, N. (2024). 
_Bibliometrics beyond citations: introducing mention extraction and analysis_. Scientometrics, 129(9),
  5731–5768. https://doi.org/10.1007/s11192-024-05116-x

A web application for interactive exploration is published at https://edhiphy.org

## Repository organisation

edhiphy consists of three repositories, connected only through the
SQLite database produced here:

- `edhiphy/build` (this repository): the pipeline from raw texts and
  curated inputs to the research database (with full texts) and the web
  export (without full texts, with a contentless full-text index).
- `edhiphy/web`: the Flask application that serves the web export.
- `edhiphy/analysis`: analysis scripts; it reads the research database.

## Funding
edhiphy is developed in the project "Exiled Empiricists: American
Philosophy and the Great Intellectual Migration" at Tilburg University,
which has received funding from the European Research Council (ERC)
under the European Union's Horizon Europe research and innovation
programme (grant agreement No 101039904, ERC-2021-STG) and from the
Dutch Research Council (NWO, grant VI.Vidi.201.115).

## Corpus definition (edhiphy 2.0)

- **English (edhiphy-en-2.0, reproduction of the edhiphy 1.4):**  22,977 research articles from 12 Anglophone journals, 1890–1979.
- **French (edhiphy-fr 0.1):** all research articles of 21 journals 1868–1980, in all languages
  (fr 33,658, en 748, some others; `JSTOR_Article.language`). Book
  reviews and miscellanea are excluded. 
- **Combined corpora** are built by listing several sources as input to
  the same pipeline, not by merging finished databases. Corpus-level
  steps (disambiguation strategies 2–4, statistics) therefore depend on
  the set of sources; each database records its sources in `Build_Info`.

## Data handling

The curated inputs (`data/`) and the internal documentation
(`documentation/`) mentioned below are not part of this public
repository.

JSTOR full texts, metadata dumps and everything derived from them
(tables, mention contexts, search indexes, SQLite builds) are
proprietary. They are never committed and never
published.

All data are expected in `DATA_DIR`, which should not be kept in a cloud synchronized folder, because it can disrupt the timestamps that Make relies on. 
The Docker container accesses data only through the following bind mounts; nothing is copied into or out of a
container:

| Host path | Container path | Mode | Content |
|---|---|---|---|
| repository checkout | `/work` | read-only | code, configuration, `data/manual` |
| `$DATA_DIR/raw` | `/data/raw` | read-only | JSTOR JSONL and metadata, scans |
| `$DATA_DIR/curated` | `/data/curated` | read-only | frozen v1 dictionary and authorship, Wikidata snapshots |
| `$DATA_DIR/feedback` | `/data/feedback` | read-only | exported website flags |
| `$DATA_DIR/reference` | `/data/reference` | read-only | v1 outputs for the comparison report |
| `$DATA_DIR/build` | `/data/build` | read-write | everything the pipeline writes |

This is the layout of `DATA_DIR` used by v2.0.0. It changes in v2.1.0 to
`raw/` (data as delivered or retrieved, including Wikidata snapshots),
`curated/` (inputs derived once and kept fixed), `flags/` (website flags),
`handover/` (v1 outputs for the comparison report), `releases/` (released
databases, one folder per release) and `scratch/` (everything the pipeline
writes).

`data/MANIFEST.sha256` lists every input file under `DATA_DIR` with its
checksum. Verify a local copy with
`make check-inputs DATA_DIR=...` if you are trying to recreate a particular version of the database.
Manual corrections (merges, drops, added variants, issue lists, journal
tables, known deviations) are not in `DATA_DIR` but in `data/manual/` of
this repository, versioned with the code that reads them.

Docker builds are the standard for every output that is shared
(releases, comparison runs). Native runs for development write to
`$DATA_DIR/build-native`, so that the two never write to the same files.
A release is checked with `make release` (web export check, checksums).

## Running the pipeline

Requirements: Docker, or for native runs GNU Make >= 4.3 (macOS: `brew
install make`, then `gmake`) and Python 3.11 with the locked
dependencies (`uv sync`; keep the environment outside a cloud-synchronised folder, e.g.
`UV_PROJECT_ENVIRONMENT=~/.venvs/edhiphy-build uv sync`).

```sh
# Docker (standard): builds the image, mounts as in the table above
DATA_DIR=/path/to/data ./run_docker.sh CORPUS=en_v1 all compare-basic
DATA_DIR=/path/to/data ./run_docker.sh CORPUS=fr EXTRACT_WORKERS=2 all release
BUILD_DIR=/tmp/edhiphy-test ./run_docker.sh CORPUS=test all test

# native (development)
gmake CORPUS=en_v1 DATA_DIR=/path/to/data all
gmake CORPUS=test BUILD_DIR=/tmp/edhiphy-test all
gmake test lint
```

A corpus is a file `config/corpora/<corpus>.mk`: its sources
(`config/sources/<source>.mk`: files, language), its dictionary
(`config/dictionary/`), the article selection, and the inputs of each
stage. `en_v1` reproduces edhiphy 1.0 (release edhiphy-en 2.0); `fr` is
the French corpus (edhiphy-fr 0.1); `test` and `test_fr` are synthetic
mini-corpora generated by `tests/fixtures/mini_corpus.py` and
`mini_corpus_fr.py`, which need no `DATA_DIR`. `CORPUS_NAME` and
`CORPUS_VERSION` name the data release (`edhiphy-<name>-<version>`, file
names and `Build_Info`); the code version is `edhiphy_version`.

The French corpus differs from the English one in its source configuration and
corpus file only: cleaner `jstor_fr` (French abbreviations and forms of
address, guillemets), the spaCy tokenizer `blank("fr")` (splits elisions:
"d'Alembert"), matching with diacritics folded (`FOLD_DIACRITICS=yes`:
OCR often drops accents), the dictionary `v1_fr` (the v1 dictionary with
its corrections and a French layer: French Wikidata labels, 1,136
philosophers of French-language traditions not in v1, the French JSTOR
authors; `edhiphy.dictionary_layers`), FTS without the English stemmer,
and LSA among French articles (`SIMILARITY_LANG=fr`). Phi_IDs of the v1
entries are shared with the English corpus; the layers' IDs are assigned
by the curated tools (`edhiphy.wikidata_philosophers`,
`edhiphy.jstor_authors`) and do not collide (plan of a global dataset:
`documentation/global_dataset.md`).

The per-document stages (clean, extract) run on a pool of processes
through dask: `WORKERS` and `EXTRACT_WORKERS` set their number (default:
one per CPU; `1` runs in the make process without dask). 
Stage parameters with their defaults:
`CONTEXT_CHARS=100`, `DISAMBIGUATION_ALPHA=0.01`,
`DISAMBIGUATION_BETA=0.25`, `DISAMBIGUATION_STRATEGIES=S1,L,S2,S3,S4`
`DISAMBIGUATION_MIN_AGE=20`)
This adds a lifetime disambiguation to drop mention candidates who are too young or not born yet when their name appears.
The equivalent of the edhiphy v1 disambiguation strategy is  `S1,S2,S3,S4`; they are recorded in `Build_Info`.

| Stage | Module | Output (below `$BUILD_DIR`) |
|---|---|---|
| 1 ingest | `edhiphy.ingest` | `sources/<source>/metadata.parquet`, `docs/` (pages per document) |
| 2 select | `edhiphy.select_articles` | `corpora/<corpus>/articles.parquet` |
| 3 journals | `edhiphy.journals` | `journals.parquet`, `journal_variants.parquet`, `article_journals.parquet` |
| 4 dictionary | `edhiphy.dictionary` | `dictionary/*.parquet`, `ambiguity_changes.csv` |
| 5 authorship | `edhiphy.authorship` | `authorship.parquet`, `article_authors.parquet` |
| 6 clean | `edhiphy.clean` | `sources/<source>/clean/` (cleaned texts, map to raw page offsets) |
| 7 extract | `edhiphy.extract` | `corpora/<corpus>/raw_mentions.parquet` |
| 8 contexts | `edhiphy.contexts` | `contexts.parquet`, `fulltexts.parquet` |
| 9 disambiguate | `edhiphy.disambiguate` | `mentions.parquet` |
| 6-9 alternative (`MENTIONS_FROM=v1`) | `edhiphy.import_v1` | the same three files from the v1 tables |
| 9b similarity | `edhiphy.similarity` | `similarity/` (LSA and mention-profile neighbours of articles and authors, summaries `similarity.md`, `authors.md`) |
| 10 package | `edhiphy.package` | `edhiphy-<name>-<version>.sqlite` (research database, with full texts) |
| 11 export_web | `edhiphy.export_web` | `edhiphy-<name>-<version>-web.sqlite` (no full texts) |

Each stage writes to a temporary file and renames it, so an interrupted
run leaves no partial target; each rule depends on its module, so a code
change re-runs the stages that depend on it. Further targets:
`compare-basic` (table-by-table comparison with `COMPARE_REF`, for
`en_v1` the v1 database), `compare-v1` (report on stages 6-9 against the
v1 tables, `compare-v1.md`, and the v1-to-new `Mention_ID` map),
`check-web` (release checks of the web export, `check-web.md`:
no full texts, web Mention IDs, bounded contexts, Build_Info),
`release` (`check-web` and the SHA-256 checksums of both databases), `check-inputs`, `test`, `lint`, `clean`
(removes the outputs of one corpus). Set `SOURCE_DATE_EPOCH` for
reproducible build dates in `Build_Info`.

`Article_Similarity` and `Author_Similarity` hold the 20 nearest
neighbours (`SIMILAR_K`) of each article and author by two methods: `lsa`
(LSA of the words, `LSA_DIMENSIONS` = 300; only among articles with an
English function-word share of at least 25 % and at least 1,000 words)
and `mentions` (profiles of the mentioned philosophers). Neither reveals
word order; both are part of the web export.

`Philosopher_Statistics`, `Article_Statistics`, `Journal_Statistics`
(per journal and year) and `Institution_Statistics` hold counts for the
website (mentions, mentioning and authored articles, first and last year
of mention, PhDs and hires); a mention counts for a philosopher when it is
resolved (`Mentioned_Phi_ID` set). `JSTOR_Authorship` is the authorship
relation; `JSTOR_Article.Authors_Phi_ID` is derived from it for the
website.

The dictionary stage applies a corrections layer to the frozen v1
dictionary (`data/manual/philosopher_merges.csv`, `philosopher_drops.csv`,
`variant_additions.csv`; `Philosopher_Merged` maps merged IDs to current
ones) and makes `Phi_Standard_Label` unique by adding life dates or the
Phi_ID to shared labels (`Phi_Standard_Label_legacy` keeps the v1 label).
`Philosopher_Life_Dates` holds birth and death years from Wikidata as
integers (535 BC = -535) with uncertainty flags; `edhiphy.life_dates`
formats them for display.

The web export contains no positional full-text index. `Full_Text_fts5`
holds the words of each article with their counts (ranked search with
`bm25`), `Full_Text_ngrams_fts5` the word pairs and triples within
sentences that occur in at least `FTS_NGRAM_MIN_DF` (default 2)
articles; phrases are answered from the n-grams. Queries must be
translated with `edhiphy.search_index.compile_query`, not passed to
`MATCH` directly.
The research database names mentions `<JSTOR number>_<page>_<raw
offset>`; the web export replaces the offset by the order of the mention
on its page (`<JSTOR number>_<page>_<k>`, k = 1, 2, …) in every
`Mention_ID` column. `Mention_Web_ID` in the research database maps the
two, e.g. for flags reported on the website.
Decisions, query semantics, leakage and the requirements for
`edhiphy/web`: `documentation/search_index.md`.
