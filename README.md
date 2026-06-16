# 🔍 Mini Search Engine

A document search engine built from scratch using Python, SQLite, Flask, and vanilla JavaScript.

## What It Does

- Indexes a folder of `.txt` documents into a SQLite database using an **Inverted Index**
- Accepts search queries and returns ranked results using **Term Frequency scoring**
- Serves results through a **Flask REST API**
- Displays results in a clean **Google-style UI**

## Tech Stack

| Layer      | Technology          |
|------------|---------------------|
| Indexer    | Python + SQLite     |
| Backend    | Python + Flask      |
| Database   | SQLite              |
| Frontend   | HTML + CSS + JS     |

## Project Structure

```
searchengine/
├── backend/
│   ├── indexer.py   # Reads docs → builds inverted index in SQLite
│   ├── search.py    # Search logic + TF ranking
│   └── app.py       # Flask REST API server
├── frontend/
│   └── index.html   # Search UI
├── data/
│   ├── documents/   # Put your .txt files here
│   └── search_index.db   # Auto-generated SQLite database
└── README.md
```

## How to Run

### Step 1 — Install dependencies
```bash
pip install flask flask-cors
```

### Step 2 — Add your documents
Put any `.txt` files inside `data/documents/`

### Step 3 — Build the index
```bash
python backend/indexer.py
```

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

## Key Concepts

### Inverted Index
The core data structure. Instead of reading every document on each search,
we pre-build a map: `word → [list of documents containing that word]`.
This makes searches O(1) instead of O(n*m).

### Term Frequency (TF) Ranking
Documents are ranked by how many times the search words appear.
A document mentioning "python" 8 times ranks higher than one mentioning it once.

### REST API
The frontend communicates with the backend via HTTP GET requests.
The server returns JSON which the frontend renders dynamically.
