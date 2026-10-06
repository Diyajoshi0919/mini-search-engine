# 🔍 Mini Search Engine

A document search engine built from scratch using Python, SQLite, Flask, and vanilla JavaScript.

## What It Does

- Indexes `.txt`, `.md`, `.pdf` and `.docx` documents into a SQLite database using an **Inverted Index**
- Ranks results with **BM25**, plus boosts for filename matches and query terms appearing close together
- Supports phrases (`"exact phrase"`), `AND` / `OR`, and `filename:` filters
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
| `GET /search?q=...` | Search query, returns JSON results |
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
