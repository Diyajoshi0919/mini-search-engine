"""
SEARCH.PY — The actual search engine logic.

What this file does:
- Takes a user's search query like "python database"
- Splits it into individual words: ["python", "database"]
- Looks up each word in the inverted index
- Finds documents that contain those words
- Ranks them by relevance (more matches = higher rank)
- Returns results with matched lines as snippets

Advanced search syntax supported:
    "exact phrase"        → only matches documents containing that exact phrase
    term1 AND term2       → both terms required (this is also the default
                             behavior between two bare words)
    term1 OR term2        → either term is enough
    filename:somefile.txt → only search within files whose name contains this

This is what runs every time someone clicks "Search".
"""

import sqlite3
import os
import re
import time


# ─────────────────────────────────────────────
# HELPER: Clean a word (same as in indexer)
# ─────────────────────────────────────────────

def clean_word(word):
    word = word.lower()
    word = re.sub(r'[^a-z0-9]', '', word)
    return word


# ─────────────────────────────────────────────
# QUERY PARSER — turns raw query text into a structured search
# ─────────────────────────────────────────────

def parse_query(query):
    """
    Parses the raw query string into a structured form.

    Returns:
        {
            "filename_filter": "somefile.txt" or None,
            "or_groups": [
                [ {"type": "term", "value": "python"},
                  {"type": "phrase", "value": "machine learning"} ],   # AND'd together
                [ {"type": "term", "value": "java"} ]                  # OR'd with group above
            ]
        }

    Logic:
        - filename:xyz   is pulled out first and used as a separate filter
        - "quoted text"  becomes a phrase token
        - splitting on " OR " creates separate groups (any group matching = a hit)
        - everything else within a group is split on " AND " or whitespace,
          and ALL of those tokens must match for that group to count
    """
    filename_filter = None
    fm = re.search(r'filename:(\S+)', query, re.IGNORECASE)
    if fm:
        filename_filter = fm.group(1).lower()
        query = (query[:fm.start()] + query[fm.end():]).strip()

    # Pull out "quoted phrases" before word-splitting, so spaces inside
    # quotes don't get treated as separate search terms
    phrases = re.findall(r'"([^"]+)"', query)
    query_no_phrases = re.sub(r'"[^"]+"', ' __PHRASE__ ', query)
    phrase_iter = iter(phrases)

    or_parts = re.split(r'\s+OR\s+', query_no_phrases.strip(), flags=re.IGNORECASE)

    or_groups = []
    for part in or_parts:
        # Split on the AND keyword FIRST (its own pass), then split each
        # resulting chunk on whitespace. Doing both in one regex alternation
        # is wrong: \s+ matches every gap (including the ones around "and"),
        # so the AND-specific branch never gets a chance to fire and "and"
        # falls through as if it were a regular search word.
        and_chunks = re.split(r'\s+AND\s+', part.strip(), flags=re.IGNORECASE)
        tokens = []
        for chunk in and_chunks:
            tokens.extend(re.split(r'\s+', chunk.strip()))

        group = []
        for tok in tokens:
            tok = tok.strip()
            if not tok:
                continue
            if tok == '__PHRASE__':
                try:
                    phrase = next(phrase_iter).strip().lower()
                    if phrase:
                        group.append({"type": "phrase", "value": phrase})
                except StopIteration:
                    pass
            else:
                cleaned = clean_word(tok)
                if len(cleaned) >= 2:
                    group.append({"type": "term", "value": cleaned})
        if group:
            or_groups.append(group)

    return {"filename_filter": filename_filter, "or_groups": or_groups}


# ─────────────────────────────────────────────
# CORE FUNCTION: Search the index
# ─────────────────────────────────────────────

def search(query, db_path, docs_folder, top_n=5):
    """
    Main search function.

    Args:
        query      : The search string e.g. 'python AND "list comprehension"'
        db_path    : Path to the SQLite database
        docs_folder: Where the original .txt files are stored
        top_n      : How many results to return (default 5)

    Returns:
        {
            "results": [ {filename, score, matched_words, word_frequencies,
                           snippets, total_matches}, ... ],
            "search_time_ms": 4.2,
            "parsed_query": { ...structured query, useful for debugging/UI... }
        }

    How ranking works (simple TF scoring):
        score = sum of frequencies of all matched terms/phrases in that document
        Higher score = more relevant document
    """
    start_time = time.perf_counter()

    empty = {"results": [], "search_time_ms": 0.0, "parsed_query": None}

    if not query.strip():
        return empty

    parsed = parse_query(query)

    if not parsed["or_groups"]:
        empty["parsed_query"] = parsed
        return empty

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT id, filename FROM documents")
    all_docs = cursor.fetchall()

    results = []

    for doc_id, filename in all_docs:
        # Filename filter — skip documents that don't match
        if parsed["filename_filter"] and parsed["filename_filter"] not in filename.lower():
            continue

        # Pull this document's word -> frequency / line-numbers from the index
        cursor.execute(
            "SELECT word, line_number, frequency FROM index_entries WHERE doc_id = ?",
            (doc_id,)
        )
        rows = cursor.fetchall()

        word_freq = {}
        word_lines = {}
        for word, line_number, freq in rows:
            word_freq[word] = word_freq.get(word, 0) + freq
            word_lines.setdefault(word, set()).add(line_number)

        # Load the raw file text — needed for phrase matching and snippets
        filepath = os.path.join(docs_folder, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except FileNotFoundError:
            continue

        matched_terms = {}     # display label -> frequency, e.g. {"python": 4, '"machine learning"': 2}
        matched_lines = set()
        any_group_matched = False

        # OR'd groups — a document is a hit if ANY group fully matches (AND within group)
        for group in parsed["or_groups"]:
            group_ok = True
            group_matches = {}
            group_lines = set()

            for token in group:
                if token["type"] == "term":
                    word = token["value"]
                    if word in word_freq:
                        group_matches[word] = word_freq[word]
                        group_lines |= word_lines.get(word, set())
                    else:
                        group_ok = False
                        break
                else:  # phrase
                    phrase = token["value"]
                    phrase_line_nums = [
                        i + 1 for i, line in enumerate(lines)
                        if phrase in line.lower()
                    ]
                    if phrase_line_nums:
                        group_matches[f'"{phrase}"'] = len(phrase_line_nums)
                        group_lines.update(phrase_line_nums)
                    else:
                        group_ok = False
                        break

            if group_ok:
                any_group_matched = True
                matched_terms.update(group_matches)
                matched_lines |= group_lines

        if not any_group_matched:
            continue

        score = sum(matched_terms.values())

        snippets = []
        for line_num in sorted(matched_lines)[:3]:
            if 1 <= line_num <= len(lines):
                text = lines[line_num - 1].strip()
                if text:
                    snippets.append(text)

        results.append({
            "filename": filename,
            "score": score,
            "matched_words": list(matched_terms.keys()),
            "word_frequencies": matched_terms,
            "snippets": snippets,
            "total_matches": len(matched_terms)
        })

    conn.close()

    results.sort(key=lambda r: r["score"], reverse=True)
    results = results[:top_n]

    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

    return {
        "results": results,
        "search_time_ms": elapsed_ms,
        "parsed_query": parsed
    }


# ─────────────────────────────────────────────
# QUICK TEST — run this file directly to test
# ─────────────────────────────────────────────

if __name__ == "__main__":
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DB_PATH = os.path.join(BASE_DIR, "data", "search_index.db")
    DOCS_FOLDER = os.path.join(BASE_DIR, "data", "documents")

    test_queries = [
        "python",
        "database sql",
        '"machine learning"',
        "python OR java",
        'filename:python_basics.txt list',
    ]

    for query in test_queries:
        print(f"\n🔍 Query: '{query}'")
        print("-" * 50)
        outcome = search(query, DB_PATH, DOCS_FOLDER)
        results = outcome["results"]
        print(f"  (search took {outcome['search_time_ms']} ms)")

        if not results:
            print("  No results found.")
        else:
            for i, r in enumerate(results, 1):
                print(f"  {i}. {r['filename']} (score: {r['score']}, matched: {r['matched_words']})")
                print(f"     frequencies: {r['word_frequencies']}")
                for snippet in r['snippets'][:2]:
                    print(f"     → {snippet[:80]}...")
