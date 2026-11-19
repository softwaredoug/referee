# Judgments tables

For convenience, we hold in the database a set of judgments as taken from the cheat-at-search library.

These are preloaded into the database. As these are well known datasets.

### Dataset table

Dataset table describes a corpus. We don't store the corpus here, but we do store metadata about that
corpus.

| dataset_id    | dataset_name | min_grade   | max_grade | metric |
|---------------|--------------|-------------| ----------| ------ |
| 1             | msmarco      | 0           | 1         | mrr    |
| 2             | esci         | 0           | 3         | ndcg   |
| 3             | doug_blog    | 0           | 1         | mrr    |

- dataset_name is used to identify the dataset through the API and should be indexed.
- min_grade - the lowest grade available for an item in the dataset
- max_grade - the highest grade available for an item in the dataset
- metric - the default metric used to evaluate this dataset


### Queries table

Queries table holds the query + any associated metadata used to execute the query. For example, Amazon ESCI
queries have a locale used to identify the language of the query.

| query_id      | source_query_id | split        | dataset_id   | keywords     | metadata    |
|---------------|-----------------|--------------|--------------|--------------| ------------|
| 1             | 1234            | test         | 1            | "What is the capital of France?" | NULL      |
| 2             | ab12            | dev          |2             | "How to cook pasta?" | {"locale": "en-US"} |

- keywords - the search query string
- metadata - any additional metadata associated with the query, stored as a JSON object. This can include information like locale, user preferences, or other relevant details.
- source_query_id - any query identifier provided from the source dataset
- split the name of the split given by the source dataset, if available


### Judgments table

The table is called judgments, it associates documents (string identifiers of documents not present
in the database) with queries and a grade.

| judgment_id  | query_id                         | doc_id   | grade |
| -------------|----------------------------------|----------|-------|
|            1 | 1                                | "doc123" |     1 |
|            2 | 2                                | "doc567" |     1 |


## Loading script

The `load-judgments` CLI imports cheat-at-search from a pinned Git revision in the
`judgments-loader` dependency group. It bulk loads through PostgreSQL staging
tables and normalizes the source data into `queries` and `judgments`.

Load the schema before running the CLI:

```sh
psql "$DATABASE_URL" -f database/0001_initial_schema.sql
```

Then install the loader dependencies and import the supported datasets:

```sh
uv sync --group judgments-loader
uv run load-judgments
```

Use `--dataset_name msmarco`, `--dataset_name esci`, or
`--dataset_name doug_blog` to load only one dataset. Each selected dataset is
replaced atomically, so the command can be rerun. For a small end-to-end smoke
load, run `uv run load-judgments --dataset_name doug_blog`.

The MS MARCO loader uses the `judgments` dataframe selected by cheat-at-search
(currently its `dev.small` qrels) and stores `split = 'dev'`. The ESCI loader
uses its complete `judgments` dataframe, retaining each row's `split` and
storing `product_locale` as `metadata.locale`. `doug_blog` loads the small
`cheat_at_search.doug_blog_data.judgments` dataframe and has no source split.
PostgreSQL end-to-end import tests use `doug_blog`; they do not download the
larger MS MARCO or ESCI datasets.
