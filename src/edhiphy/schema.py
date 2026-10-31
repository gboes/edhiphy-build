from sqlalchemy import (
    MetaData,
    Table,
    Column,
    Integer,
    Float,
    String,
    ForeignKey,
    Index,
)

metadata = MetaData()

# Version of the database schema, stored in PRAGMA user_version. Databases
# of edhiphy 1.x have 0. Increment on every change of tables or columns and
# record the change in the changelog.
SCHEMA_VERSION = 5

# Define all tables, based on the 1.2.1 schema.
# Create indexes for all columns, since we eat the cost
# of creating them only once.

# CREATE TABLE Philosopher (Phi_ID TEXT PRIMARY KEY NOT NULL, Phi_Standard_Label TEXT NOT NULL, Wiki_ID TEXT, Wiki INTEGER NOT NULL, JSTOR INTEGER NOT NULL, Hiring INTEGER NOT NULL, PhD INTEGER NOT NULL)
Philosopher = Table(
    "Philosopher",
    metadata,
    Column("Phi_ID", String, primary_key=True),
    Column("Phi_Standard_Label", String, nullable=False, unique=True),
    # The v1 label; Phi_Standard_Label is unique since schema version 4.
    Column("Phi_Standard_Label_legacy", String, nullable=False, index=True),
    Column("Wiki", Integer, nullable=False, index=True),
    Column("JSTOR", Integer, nullable=False, index=True),
    Column("Hiring", Integer, nullable=False, index=True),
    Column("PhD", Integer, nullable=False, index=True),
)

# Philosophers merged into another entry (data/manual/philosopher_merges.csv,
# issue #14): old Phi_ID -> current Phi_ID. Since schema version 4.
Philosopher_Merged = Table(
    "Philosopher_Merged",
    metadata,
    Column("Merged_Phi_ID", String, primary_key=True),
    Column(
        "Phi_ID", String, ForeignKey(Philosopher.c.Phi_ID), nullable=False, index=True
    ),
)

# Life dates of the Wikidata entry of a philosopher: historical years (535 BC
# is -535, no year 0); *_Uncertain = 1 for circa or the midpoint of a range.
# Display: edhiphy.life_dates. Since schema version 4.
Philosopher_Life_Dates = Table(
    "Philosopher_Life_Dates",
    metadata,
    Column("Phi_ID", String, ForeignKey(Philosopher.c.Phi_ID), primary_key=True),
    Column("Wiki_ID", String, nullable=False),
    Column("Birth_Year", Integer, index=True),
    Column("Birth_Uncertain", Integer),
    Column("Death_Year", Integer, index=True),
    Column("Death_Uncertain", Integer),
)

Philosopher_Wiki_ID = Table(
    "Philosopher_Wiki_ID",
    metadata,
    Column(
        "Phi_ID", String, ForeignKey(Philosopher.c.Phi_ID), nullable=False, index=True
    ),
    Column("Wiki_ID", String, index=True),
)

# CREATE TABLE Variant (Phi_ID TEXT REFERENCES Philosopher (Phi_ID) NOT NULL, Variant_ID TEXT NOT NULL PRIMARY KEY, Variant TEXT NOT NULL, Variant_origin TEXT NOT NULL, Variant_length INTEGER NOT NULL, Issue_level TEXT, Ambiguity TEXT, Matching_Phi_IDs TEXT, N_Multiple_Phi_IDs INTEGER)
Variant = Table(
    "Variant",
    metadata,
    Column(
        "Phi_ID", String, ForeignKey(Philosopher.c.Phi_ID), nullable=False, index=True
    ),
    Column("Variant_ID", String, primary_key=True),
    Column("Variant", String, nullable=False, index=True),
    Column("Variant_origin", String, nullable=False, index=True),
    Column("Variant_length", Integer, nullable=False, index=True),
    Column("Issue_level", String, index=True),
    Column("Ambiguity", String, index=True),
    Column("Matching_Phi_IDs", String, index=True),
    Column("N_Multiple_Phi_IDs", Integer, index=True),
)

Variant_Matching_Phi_ID = Table(
    "Variant_Matching_Phi_ID",
    metadata,
    Column(
        "Variant_ID",
        String,
        ForeignKey(Variant.c.Variant_ID),
        nullable=False,
        index=True,
    ),
    Column(
        "Phi_ID", String, ForeignKey(Philosopher.c.Phi_ID), nullable=False, index=True
    ),
)

# CREATE TABLE Biography (Phi_ID TEXT PRIMARY KEY REFERENCES Philosopher (Phi_ID) NOT NULL, Surname TEXT, First_Name TEXT, Gender TEXT, BirthYear INTEGER)
Biography = Table(
    "Biography",
    metadata,
    Column("Phi_ID", String, ForeignKey(Philosopher.c.Phi_ID), primary_key=True),
    Column("Surname", String, index=True),
    Column("First_Name", String, index=True),
    Column("Gender", String, index=True),
    Column("BirthYear", Integer, index=True),
)

# CREATE TABLE Journal (Journal_ID TEXT PRIMARY KEY NOT NULL, Journal_standard_name TEXT NOT NULL, Standard_abbreviation TEXT NOT NULL, Journal_name_JSTOR TEXT NOT NULL, Foundation_Year INTEGER NOT NULL)
Journal = Table(
    "Journal",
    metadata,
    Column("Journal_ID", String, primary_key=True),
    Column("Journal_standard_name", String, nullable=False, index=True),
    Column("Standard_abbreviation", String, nullable=False, index=True),
    Column("Journal_name_JSTOR", String, nullable=False, index=True),
    Column("Foundation_Year", Integer, nullable=False, index=True),
)

# CREATE TABLE Journal_Variant (Journal_ID TEXT REFERENCES Journal (Journal_ID, index=True), Journal_variant TEXT PRIMARY KEY NOT NULL, Starting_date INTEGER NOT NULL, Ending_date INTEGER)
Journal_Variant = Table(
    "Journal_Variant",
    metadata,
    Column("Journal_ID", String, ForeignKey(Journal.c.Journal_ID), index=True),
    Column("Journal_variant", String, primary_key=True),
    Column("Starting_date", Integer, nullable=False, index=True),
    Column("Ending_date", Integer, index=True),
)

# CREATE TABLE JSTOR_Article (Article_ID TEXT PRIMARY KEY NOT NULL, Authors_Phi_ID TEXT NOT NULL, title TEXT, publicationYear INTEGER NOT NULL, doi TEXT, docType TEXT, docSubType TEXT, provider TEXT, collection TEXT, datePublished TEXT, issueNumber TEXT, volumeNumber TEXT, url TEXT NOT NULL, creator TEXT, publisher TEXT, language TEXT, pageStart INTEGER, pageEnd INTEGER, placeOfPublication TEXT, keyphrase TEXT, wordCount INTEGER, pageCount INTEGER, file TEXT, N_authors INTEGER NOT NULL, Journal_ID TEXT NOT NULL REFERENCES Journal (Journal_ID))
JSTOR_Article = Table(
    "JSTOR_Article",
    metadata,
    Column("Article_ID", String, primary_key=True),
    Column("Authors_Phi_ID", String, nullable=False, index=True),
    Column("title", String, index=True),
    Column("publicationYear", Integer, nullable=False, index=True),
    Column("doi", String, index=True),
    Column("docType", String, index=True),
    Column("docSubType", String, index=True),
    Column("provider", String, index=True),
    Column("collection", String, index=True),
    Column("datePublished", String, index=True),
    Column("issueNumber", String, index=True),
    Column("volumeNumber", String, index=True),
    Column("url", String, nullable=False, index=True),
    Column("creator", String, index=True),
    Column("publisher", String, index=True),
    Column("language", String, index=True),
    Column("pageStart", Integer, index=True),
    Column("pageEnd", Integer, index=True),
    Column("placeOfPublication", String, index=True),
    Column("keyphrase", String, index=True),
    Column("wordCount", Integer, index=True),
    Column("pageCount", Integer, index=True),
    Column("file", String, index=True),
    Column("N_authors", Integer, nullable=False, index=True),
    Column(
        "Journal_ID",
        String,
        ForeignKey(Journal.c.Journal_ID),
        nullable=False,
        index=True,
    ),
)

# CREATE TABLE JSTOR_Authorship (Phi_ID TEXT NOT NULL REFERENCES Philosopher (Phi_ID, index=True), author_position INTEGER NOT NULL, original_JSTOR_author TEXT, Article_ID TEXT NOT NULL REFERENCES JSTOR_Article (Article_ID, index=True), PRIMARY KEY (Phi_ID, Article_ID))
# The authorship relation (issue #18): one row per article and author.
# author_position is the place of the name in the JSTOR creator list
# (from 1; 0 for "[No Author]", P:1); a name given twice keeps its first
# place, so positions can have gaps. JSTOR_Article.Authors_Phi_ID
# (";"-joined in author order) and N_authors are derived from it and kept
# only because edhiphy/web reads Authors_Phi_ID; new code should join
# JSTOR_Authorship.
# JSTOR_Article.creator and language are ";"-joined as delivered by JSTOR.
JSTOR_Authorship = Table(
    "JSTOR_Authorship",
    metadata,
    Column("Phi_ID", String, ForeignKey(Philosopher.c.Phi_ID), primary_key=True),
    Column("author_position", Integer, nullable=False, index=True),
    Column("original_JSTOR_author", String, index=True),
    Column(
        "Article_ID",
        String,
        ForeignKey(JSTOR_Article.c.Article_ID),
        primary_key=True,
        index=True,
    ),
)

# CREATE TABLE Full_Text (Article_ID TEXT PRIMARY KEY REFERENCES JSTOR_Article (Article_ID) NOT NULL, FullText TEXT NOT NULL, length_words INTEGER NOT NULL, length_characters INTEGER NOT NULL)
Full_Text = Table(
    "Full_Text",
    metadata,
    Column(
        "Article_ID", String, ForeignKey(JSTOR_Article.c.Article_ID), primary_key=True
    ),
    Column("FullText", String, nullable=False),
    Column("length_words", Integer, nullable=False, index=True),
    Column("length_characters", Integer, nullable=False, index=True),
)

# CREATE TABLE Wiki_Entry (Wiki_ID TEXT PRIMARY KEY REFERENCES Philosopher (Wiki_ID) NOT NULL, Wiki_label TEXT NOT NULL, Wiki_aliases TEXT, Wiki_description TEXT, Wiki_birthYear TEXT, Mult_years TEXT, Wiki_surname TEXT, Mult_surn TEXT, Wiki_firstname TEXT, Mult_first TEXT, Wiki_gender TEXT, Mult_gender TEXT)
Wiki_Entry = Table(
    "Wiki_Entry",
    metadata,
    Column(
        "Wiki_ID", String, ForeignKey(Philosopher_Wiki_ID.c.Wiki_ID), primary_key=True
    ),
    Column("Wiki_label", String, nullable=False, index=True),
    Column("Wiki_description", String, index=True),
    Column("Mult_years", String, index=True),
    Column("Mult_surn", String, index=True),
    Column("Mult_first", String, index=True),
    Column("Mult_gender", String, index=True),
)

Wiki_Entry_alias = Table(
    "Wiki_Entry_alias",
    metadata,
    Column("Wiki_ID", String, ForeignKey(Wiki_Entry.c.Wiki_ID), index=True),
    Column("alias", String, index=True),
)

Wiki_Entry_birthYear = Table(
    "Wiki_Entry_birthYear",
    metadata,
    Column("Wiki_ID", String, ForeignKey(Wiki_Entry.c.Wiki_ID), index=True),
    Column("birthYear", Integer, index=True),
)

Wiki_Entry_surname = Table(
    "Wiki_Entry_surname",
    metadata,
    Column("Wiki_ID", String, ForeignKey(Wiki_Entry.c.Wiki_ID), index=True),
    Column("surname", String, index=True),
)

Wiki_Entry_firstname = Table(
    "Wiki_Entry_firstname",
    metadata,
    Column("Wiki_ID", String, ForeignKey(Wiki_Entry.c.Wiki_ID), index=True),
    Column("firstname", String, index=True),
)

Wiki_Entry_gender = Table(
    "Wiki_Entry_gender",
    metadata,
    Column("Wiki_ID", String, ForeignKey(Wiki_Entry.c.Wiki_ID), index=True),
    Column("gender", String, index=True),
)

# CREATE TABLE Mention (Mentioning_Article_ID TEXT NOT NULL REFERENCES JSTOR_Article (Article_ID, index=True), Mention_ID TEXT NOT NULL PRIMARY KEY, Ent_text TEXT NOT NULL, Ent_label TEXT NOT NULL, Associated_Phi_IDs TEXT NOT NULL, Disambiguated_Phi_ID TEXT NOT NULL, Disambiguation_status TEXT NOT NULL, Mentioned_Phi_ID TEXT REFERENCES Philosopher (Phi_ID))
Mention = Table(
    "Mention",
    metadata,
    Column(
        "Mentioning_Article_ID",
        String,
        ForeignKey(JSTOR_Article.c.Article_ID),
        nullable=False,
        index=True,
    ),
    Column("Mention_ID", String, primary_key=True),
    Column("Ent_text", String, nullable=False, index=True),
    Column("Ent_label", String, nullable=False, index=True),
    Column("Disambiguation_status", String, nullable=False, index=True),
    Column("Mentioned_Phi_ID", String, ForeignKey(Philosopher.c.Phi_ID), index=True),
)

Mention_associated = Table(
    "Mention_Associated",
    metadata,
    Column("Mention_ID", String, ForeignKey(Mention.c.Mention_ID), index=True),
    Column("Phi_ID", String, ForeignKey(Philosopher.c.Phi_ID), index=True),
)

Mention_disambiguated = Table(
    "Mention_Disambiguated",
    metadata,
    Column("Mention_ID", String, ForeignKey(Mention.c.Mention_ID), index=True),
    Column("Phi_ID", String, ForeignKey(Philosopher.c.Phi_ID), index=True),
)

# CREATE TABLE Mention_context (Mentioning_Article_ID TEXT NOT NULL REFERENCES JSTOR_Article (Article_ID, index=True), Mention_ID TEXT REFERENCES Mention (Mention_ID) NOT NULL PRIMARY KEY, Mention_context TEXT NOT NULL)
Mention_context = Table(
    "Mention_context",
    metadata,
    Column(
        "Mentioning_Article_ID",
        String,
        ForeignKey(JSTOR_Article.c.Article_ID),
        nullable=False,
        index=True,
    ),
    Column("Mention_ID", String, ForeignKey(Mention.c.Mention_ID), primary_key=True),
    Column("Mention_context", String, nullable=False),
)

# Research database only: the Mention_ID of the web export, in which the
# raw character offset is replaced by the order k (1, 2, ...) of the
# mention on its page, <JSTOR number>_<page>_<k> (edhiphy.package);
# edhiphy.export_web rewrites every Mention_ID column with it and drops
# the table. Kept for mapping flags of the website back. Since schema
# version 5.
Mention_Web_ID = Table(
    "Mention_Web_ID",
    metadata,
    Column("Mention_ID", String, ForeignKey(Mention.c.Mention_ID), primary_key=True),
    Column("Web_Mention_ID", String, nullable=False, unique=True),
)

# CREATE TABLE Institution (Institution_ID TEXT PRIMARY KEY NOT NULL, Institution TEXT NOT NULL)
Institution = Table(
    "Institution",
    metadata,
    Column("Institution_ID", String, primary_key=True),
    Column("Institution", String, nullable=False, index=True),
)

# CREATE TABLE PhD_Dissertation (Phi_ID TEXT REFERENCES Philosopher (Phi_ID) NOT NULL, PQ_ID TEXT PRIMARY KEY, Title TEXT, PhD_Candidate TEXT, PhD_Year INTEGER, Institution_ID TEXT REFERENCES Institution (Institution_ID) NOT NULL)
PhD_Dissertation = Table(
    "PhD_Dissertation",
    metadata,
    Column(
        "Phi_ID", String, ForeignKey(Philosopher.c.Phi_ID), nullable=False, index=True
    ),
    Column("PQ_ID", String, primary_key=True),
    Column("Title", String, index=True),
    Column("PhD_Candidate", String, index=True),
    Column("PhD_Year", Integer, index=True),
    Column(
        "Institution_ID",
        String,
        ForeignKey(Institution.c.Institution_ID),
        nullable=False,
        index=True,
    ),
)

# CREATE TABLE Classification (Property_ID TEXT PRIMARY KEY NOT NULL, Phi_ID TEXT REFERENCES Philosopher (Phi_ID) NOT NULL, Property TEXT, Type TEXT, Source TEXT, Manual INTEGER NOT NULL)
Classification = Table(
    "Classification",
    metadata,
    Column("Property_ID", String, primary_key=True),
    Column(
        "Phi_ID", String, ForeignKey(Philosopher.c.Phi_ID), nullable=False, index=True
    ),
    Column("Property", String, index=True),
    Column("Type", String, index=True),
    Column("Source", String, index=True),
    Column("Manual", Integer, nullable=False, index=True),
)

# CREATE TABLE Hire_Position (Position_ID TEXT PRIMARY KEY NOT NULL, Phi_ID TEXT REFERENCES Philosopher (Phi_ID) NOT NULL, Hire_Name TEXT, Institution_ID TEXT NOT NULL REFERENCES Institution (Institution_ID, index=True), Hired_year INTEGER, Hired_before_1930 INTEGER NOT NULL, Hire_rank TEXT, Left_year INTEGER, Left_after_1980 INTEGER NOT NULL, Highest_rank TEXT)
Hire_Position = Table(
    "Hire_Position",
    metadata,
    Column("Position_ID", String, primary_key=True),
    Column(
        "Phi_ID", String, ForeignKey(Philosopher.c.Phi_ID), nullable=False, index=True
    ),
    Column("Hire_Name", String, index=True),
    Column(
        "Institution_ID",
        String,
        ForeignKey(Institution.c.Institution_ID),
        nullable=False,
        index=True,
    ),
    Column("Hired_year", Integer, index=True),
    Column("Hired_before_1930", Integer, nullable=False, index=True),
    Column("Hire_rank", String, index=True),
    Column("Left_year", Integer, index=True),
    Column("Left_after_1980", Integer, nullable=False, index=True),
    Column("Highest_rank", String, index=True),
)

# Provenance of a build: schema version, commit, sources, dictionary,
# parameters, date (see edhiphy.build_info).
Build_Info = Table(
    "Build_Info",
    metadata,
    Column("key", String, primary_key=True),
    Column("value", String),
)

Wiki_Entry_alias_spellfix1 = Table(
    "Wiki_Entry_alias_spellfix1",
    metadata,
    Column("rowid", String, primary_key=True),
    Column("word", String),
    Column("rank", Integer),
    Column("distance", Integer),
    Column("langid", Integer),
    Column("score", Integer),
    Column("matchlen", Integer),
    Column("phonehash", String),
    Column("top", Integer, system=True),
    Column("scope", Integer, system=True),
    Column("srchcnt", Integer, system=True),
    Column("soundslike", String, system=True),
    Column("command", String, system=True),
)

Full_Text_fts5 = Table(
    "Full_Text_fts5",
    metadata,
    Column("rowid", Integer, primary_key=True),
    Column("FullText", String, nullable=False, system=True),
)

# Nearest neighbours of the similarity stage (edhiphy.similarity): per
# article (author) and Method ("lsa": LSA of the words; "mentions":
# profile of mentioned philosophers), the neighbours by Rank 1..k with
# their Cosine. Since schema version 3.
Article_Similarity = Table(
    "Article_Similarity",
    metadata,
    Column(
        "Article_ID",
        String,
        ForeignKey(JSTOR_Article.c.Article_ID),
        primary_key=True,
    ),
    Column("Method", String, primary_key=True),
    Column("Rank", Integer, primary_key=True),
    Column(
        "Neighbour_ID",
        String,
        ForeignKey(JSTOR_Article.c.Article_ID),
        nullable=False,
        index=True,
    ),
    Column("Cosine", Float, nullable=False),
)

Author_Similarity = Table(
    "Author_Similarity",
    metadata,
    Column("Phi_ID", String, ForeignKey(Philosopher.c.Phi_ID), primary_key=True),
    Column("Method", String, primary_key=True),
    Column("Rank", Integer, primary_key=True),
    Column(
        "Neighbour_Phi_ID",
        String,
        ForeignKey(Philosopher.c.Phi_ID),
        nullable=False,
        index=True,
    ),
    Column("Cosine", Float, nullable=False),
)

# Summary statistics (web issue #8), computed by edhiphy.package from the
# tables above. N_mentions counts the mentions resolved to an entity
# (Mentioned_Phi_ID set, i.e. Disambiguation_status other than
# "Ambiguous", as the web pages count them); N_ambiguous_mentions the
# ambiguous mentions that list the philosopher among their candidates.
# Every philosopher, article, journal-year and institution has a row.
# Since schema version 5.
Philosopher_Statistics = Table(
    "Philosopher_Statistics",
    metadata,
    Column("Phi_ID", String, ForeignKey(Philosopher.c.Phi_ID), primary_key=True),
    Column("N_mentions", Integer, nullable=False, index=True),
    Column("N_mentioning_articles", Integer, nullable=False, index=True),
    Column("N_ambiguous_mentions", Integer, nullable=False, index=True),
    Column("N_authored_articles", Integer, nullable=False, index=True),
    Column("First_mention_year", Integer, index=True),
    Column("Last_mention_year", Integer, index=True),
)

Article_Statistics = Table(
    "Article_Statistics",
    metadata,
    Column(
        "Article_ID", String, ForeignKey(JSTOR_Article.c.Article_ID), primary_key=True
    ),
    Column("N_mentions", Integer, nullable=False, index=True),
    Column("N_ambiguous_mentions", Integer, nullable=False, index=True),
    Column("N_mentioned_philosophers", Integer, nullable=False, index=True),
)

# Per journal and publication year; N_authors counts distinct authors
# without "[No Author]" (P:1).
Journal_Statistics = Table(
    "Journal_Statistics",
    metadata,
    Column("Journal_ID", String, ForeignKey(Journal.c.Journal_ID), primary_key=True),
    Column("publicationYear", Integer, primary_key=True),
    Column("N_articles", Integer, nullable=False),
    Column("N_authors", Integer, nullable=False),
    Column("N_mentions", Integer, nullable=False),
    Column("N_mentioned_philosophers", Integer, nullable=False),
)

Institution_Statistics = Table(
    "Institution_Statistics",
    metadata,
    Column(
        "Institution_ID",
        String,
        ForeignKey(Institution.c.Institution_ID),
        primary_key=True,
    ),
    Column("N_PhD_dissertations", Integer, nullable=False, index=True),
    Column("N_hire_positions", Integer, nullable=False, index=True),
    Column("N_hired_philosophers", Integer, nullable=False, index=True),
)

# Web export only (see edhiphy.search_index): word pairs and triples per
# article, without positions or counts.
Full_Text_ngrams_fts5 = Table(
    "Full_Text_ngrams_fts5",
    metadata,
    Column("rowid", Integer, primary_key=True),
    Column("Ngrams", String, nullable=False, system=True),
)

# Links the fts5 tables to the Article table
Full_Text_fts5_Article_ID = Table(
    "Full_Text_fts5_ArticleID",
    metadata,
    Column("rowid", Integer, ForeignKey(Full_Text_fts5.c.rowid), primary_key=True),
    Column("Article_ID", String, ForeignKey(JSTOR_Article.c.Article_ID)),
)


# Tables of the research database that the web export drops.
research_only_tables = frozenset((Mention_Web_ID,))

virtual_tables = frozenset(
    (Wiki_Entry_alias_spellfix1, Full_Text_fts5, Full_Text_ngrams_fts5)
)
