"""
SEARCH.PY — The actual search engine logic.

What this file does:
- Takes a user's search query like "python database"
- Splits it into individual words: ["python", "database"]
- Looks up each word in the inverted index
- Finds documents that contain those words
- Ranks them by relevance (more matches = higher rank)
- Returns results with matched lines as snippets

This is what runs every time someone clicks "Search".
"""

import sqlite3
import os
import re


# ─────────────────────────────────────────────
# HELPER: Clean a word (same as in indexer)
# ─────────────────────────────────────────────

def clean_word(word):
    word = word.lower()
    word = re.sub(r'[^a-z0-9]', '', word)
    return word


# ─────────────────────────────────────────────
# CORE FUNCTION: Search the index
# ─────────────────────────────────────────────

def search(query, db_path, docs_folder, top_n=5):
    """
    Main search function. 
    
    Args:
        query      : The search string e.g. "python list"
        db_path    : Path to the SQLite database
        docs_folder: Where the original .txt files are stored
        top_n      : How many results to return (default 5)
    
    Returns:
        A list of result dicts, each containing:
        {
            "filename": "python_basics.txt",
            "score": 4,
            "matched_words": ["python", "list"],
            "snippets": ["Python is a high-level...", "Lists tuples and..."]
        }
    
    How ranking works (simple TF scoring):
        score = sum of frequencies of all matched words in that document
        Higher score = more relevant document
    """

    if not query.strip():
        return []

    # Step 1: Clean and split the query into individual words
    raw_words = query.strip().split()
    search_words = [clean_word(w) for w in raw_words if len(clean_word(w)) >= 2]

    if not search_words:
        return []

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Step 2: For each search word, find matching documents
    # doc_scores = { doc_id: { "score": N, "matched_words": [], "lines": [] } }
    doc_scores = {}

    for word in search_words:
        # Query the inverted index
        # This is why the index exists — this query is instant even with millions of docs
        cursor.execute("""
            SELECT ie.doc_id, d.filename, ie.line_number, ie.frequency
            FROM index_entries ie
            JOIN documents d ON ie.doc_id = d.id
            WHERE ie.word = ?
        """, (word,))

        rows = cursor.fetchall()

        for doc_id, filename, line_number, frequency in rows:
            if doc_id not in doc_scores:
                doc_scores[doc_id] = {
                    "filename": filename,
                    "score": 0,
                    "matched_words": [],
                    "line_numbers": []
                }

            # Add frequency to score — more occurrences = more relevant
            doc_scores[doc_id]["score"] += frequency

            # Track which words matched
            if word not in doc_scores[doc_id]["matched_words"]:
                doc_scores[doc_id]["matched_words"].append(word)

            # Track which lines matched
            if line_number not in doc_scores[doc_id]["line_numbers"]:
                doc_scores[doc_id]["line_numbers"].append(line_number)

    conn.close()

    if not doc_scores:
        return []

    # Step 3: Sort documents by score (highest first)
    sorted_docs = sorted(doc_scores.values(), key=lambda x: x["score"], reverse=True)

    # Step 4: For each top result, fetch the actual matching lines as snippets
    results = []

    for doc in sorted_docs[:top_n]:
        snippets = get_snippets(
            docs_folder,
            doc["filename"],
            doc["line_numbers"]
        )

        results.append({
            "filename": doc["filename"],
            "score": doc["score"],
            "matched_words": doc["matched_words"],
            "snippets": snippets,
            "total_matches": len(doc["matched_words"])
        })

    return results


# ─────────────────────────────────────────────
# HELPER: Get matching lines from a file
# ─────────────────────────────────────────────

def get_snippets(docs_folder, filename, line_numbers, max_snippets=3):
    """
    Opens the original file and returns the actual text lines
    that contained the search words.
    
    These become the "preview text" shown under each search result,
    just like Google shows a snippet of matching text.
    """
    filepath = os.path.join(docs_folder, filename)

    if not os.path.exists(filepath):
        return []

    snippets = []

    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # Only show first max_snippets matching lines
    for line_num in sorted(line_numbers)[:max_snippets]:
        if 1 <= line_num <= len(lines):
            snippet = lines[line_num - 1].strip()
            if snippet:
                snippets.append(snippet)

    return snippets


# ─────────────────────────────────────────────
# QUICK TEST — run this file directly to test
# ─────────────────────────────────────────────

if __name__ == "__main__":
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DB_PATH = os.path.join(BASE_DIR, "data", "search_index.db")
    DOCS_FOLDER = os.path.join(BASE_DIR, "data", "documents")

    test_queries = ["python", "database sql", "socket network", "list stack"]

    for query in test_queries:
        print(f"\n🔍 Query: '{query}'")
        print("-" * 50)
        results = search(query, DB_PATH, DOCS_FOLDER)

        if not results:
            print("  No results found.")
        else:
            for i, r in enumerate(results, 1):
                print(f"  {i}. {r['filename']} (score: {r['score']}, matched: {r['matched_words']})")
                for snippet in r['snippets'][:2]:
                    print(f"     → {snippet[:80]}...")
