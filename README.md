# 🔍 Mini Search Engine

A document search engine built from scratch using Python, SQLite, Flask, and vanilla JavaScript.

## What It Does

- Indexes `.txt`, `.md`, `.pdf` and `.docx` documents into a SQLite database using an **Inverted Index**
- Ranks results with **BM25**, plus boosts for filename matches and query terms appearing close together
- Supports phrases (`"exact phrase"`), `AND` / `OR`, and `filename:` filters
- **Typo tolerance**: `pyhton` finds `python`, with Google-style "Showing results for" / "Did you mean"
- **Autocomplete** that uses the previous word: `machine le` suggests `machine learning` first
- Upload several files at once through the UI; PDF results show the page number
- Serves results through a **Flask REST API**
- Displays results in a clean **Google-style UI**

## Tech Stack

| Layer      | Technology          |
|------------|---------------------|
| Indexer    | Python + SQLite + pypdf + python-docx |
| Backend    | Python + Flask      |
| Database   | SQLite              |
| Frontend   | HTML + CSS + JS     |

## Project Structure

```
searchengine/
├── backend/
│   ├── extractors.py # Pulls text out of txt / md / pdf / docx
│   ├── indexer.py   # Builds the inverted index in SQLite
│   ├── search.py    # Search logic + BM25 ranking
│   ├── vocabulary.py # Spell correction + autocomplete
│   └── app.py       # Flask REST API server
├── frontend/
│   └── index.html   # Search UI
├── data/
│   ├── documents/   # Put your .txt / .md / .pdf / .docx files here
│   └── search_index.db   # Auto-generated SQLite database
└── README.md
```

## How to Run

### Step 1 — Install dependencies
```bash
pip install -r requirements.txt
```

### Step 2 — Add your documents
Put any `.txt`, `.md`, `.pdf` or `.docx` files inside `data/documents/`, or upload them later from the Documents page.

Scanned PDFs (pages that are just images) have no text to extract, so they index as empty.

### Step 3 — Build the index
```bash
python backend/indexer.py
```
The server also builds it automatically on startup if it is missing.

### Step 4 — Start the API server
```bash
python backend/app.py
```

### Step 5 — Open the frontend
Open `frontend/index.html` in your browser.

## API Endpoints

| Endpoint            | Description                        |
|---------------------|------------------------------------|
| `GET /`             | Health check                       |
| `GET /search?q=...` | Search query, returns JSON results (add `&exact=1` to turn off spell correction) |
| `GET /suggest?q=...` | Autocomplete suggestions for a partial query |
| `GET /stats`        | Index statistics                   |
| `POST /upload`      | Upload one or more files (form key `file`) |
| `GET /documents`    | List documents                     |
| `DELETE /documents/<name>` | Delete a document           |

## Key Concepts

### Inverted Index
The core data structure. Instead of reading every document on each search,
we pre-build a map: `word → [list of documents containing that word]`.
This makes searches O(1) instead of O(n*m).

### BM25 Ranking
Plain term counting has three problems: common words count as much as rare ones,
repeating a word 50 times keeps raising the score, and long documents win just by being long.
BM25 fixes all three:

- **IDF**: rare words (e.g. "backpropagation") count more than common ones (e.g. "data").
- **Saturation (`k1 = 1.5`)**: each extra repeat of a word adds less than the one before.
- **Length normalization (`b = 0.75`)**: counts are compared against the average document length.

On top of BM25, a document gets small boosts when a query word is in its **filename**
and when **several query terms appear on the same line**. Exact phrases are weighted 1.5×.
Hover the score on a result to see the breakdown.

### REST API
The frontend communicates with the backend via HTTP GET requests.
The server returns JSON which the frontend renders dynamically.

### Typo Tolerance
Every word in the index forms a vocabulary. When a query word isn't in it,
the engine finds the closest word using **edit distance**: the number of
single-letter insertions, deletions, substitutions or swaps needed to turn one
word into the other. Swapping two neighbouring letters counts as one edit, since
it's the most common typo (`pyhton` → `python` is 1 edit, not 2).

- Words of 3 to 5 letters may have 1 typo, longer words 2. Shorter words are never changed.
- Ties go to the word that appears in the most documents.
- If the original query finds nothing, the corrected one is searched automatically
  ("Showing results for ..."). If it does find something, the results are kept and
  a "Did you mean" link is shown instead.

**Making it fast.** Comparing a typo against every word is slow on large vocabularies
(about 220 ms per word at 50,000 words). So the vocabulary is also indexed by
**letter pairs** (`python` → `^p, py, yt, th, ho, on, n$`). Each edit can break at
most 3 of a word's letter pairs, so a real match must share at least
`pairs − 3 × allowed_typos` of them. Counting shared pairs is cheap, and only words
that pass get the full edit-distance check. At 50,000 words this brought
correction down to about 2 to 30 ms, with results identical to checking every word.

### Autocomplete
The vocabulary is kept in a **sorted list**, so every word starting with a prefix
is found by **binary search** in O(log n) instead of scanning all words.
Candidates are ranked by how often they directly **follow the previous word**
in your documents (bigram counts), then by overall frequency. That's why
`machine le` suggests `machine learning` before other `le...` words.

The vocabulary is cached in memory and reloads automatically whenever the
database file changes, so uploaded documents appear in suggestions right away.
