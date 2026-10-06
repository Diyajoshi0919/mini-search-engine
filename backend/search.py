import sqlite3
import os
import re
import time
import math


def clean_word(word):
    word = word.lower()
    word = re.sub(r'[^a-z0-9]', '', word)
    return word


def parse_query(query):
    filename_filter = None
    fm = re.search(r'filename:(\S+)', query, re.IGNORECASE)
    if fm:
        filename_filter = fm.group(1).lower()
        query = (query[:fm.start()] + query[fm.end():]).strip()

    phrases = re.findall(r'"([^"]+)"', query)
    query_no_phrases = re.sub(r'"[^"]+"', ' __PHRASE__ ', query)
    phrase_iter = iter(phrases)

    or_parts = re.split(r'\s+OR\s+', query_no_phrases.strip(), flags=re.IGNORECASE)

    or_groups = []
    for part in or_parts:
        # AND has to be split out before whitespace splitting, otherwise
        # \s+ swallows the gaps around "AND" too and it gets treated as
        # a regular search term instead of an operator
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


# ── Ranking ──
#
# BM25 is the standard ranking formula behind engines like Elasticsearch.
# Compared to plain term-frequency counting it fixes three problems:
#   1. Rare words matter more than common ones (IDF). Matching "recursion"
#      says more about a doc than matching "the" or "data".
#   2. Repeating a word has diminishing returns (k1). The 20th "python"
#      adds far less than the 1st.
#   3. Long documents don't win just by being long (b). Counts are
#      normalized against the average document length.
K1 = 1.5
B = 0.75
PHRASE_WEIGHT = 1.5      # exact phrases are more specific than single words
FILENAME_BOOST = 0.6     # fraction of a term's IDF added when it's in the filename
PROXIMITY_BOOST = 0.4    # per line where 2+ query terms appear together (max 3 lines)


def idf(df, total_docs):
    return math.log(1 + (total_docs - df + 0.5) / (df + 0.5))


def bm25(tf, df, doc_len, avg_doc_len, total_docs):
    if tf == 0:
        return 0.0
    norm = K1 * (1 - B + B * doc_len / avg_doc_len) if avg_doc_len else K1
    return idf(df, total_docs) * (tf * (K1 + 1)) / (tf + norm)


def _escape_like(text):
    return text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def search(query, db_path, docs_folder=None, top_n=5):
    # docs_folder is no longer needed (text comes from the database) but is
    # kept in the signature so existing callers don't break
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

    if cursor.execute("PRAGMA user_version").fetchone()[0] < 2:
        conn.close()
        raise RuntimeError("Search index is from an older version. Run: python backend/indexer.py")

    cursor.execute("SELECT id, filename, file_type, total_words FROM documents")
    docs = {
        doc_id: {"filename": fn, "file_type": ft, "length": tw or 0}
        for doc_id, fn, ft, tw in cursor.fetchall()
    }
    total_docs = len(docs)
    if total_docs == 0:
        conn.close()
        empty["parsed_query"] = parsed
        return empty
    avg_doc_len = sum(d["length"] for d in docs.values()) / total_docs

    terms = {t["value"] for g in parsed["or_groups"] for t in g if t["type"] == "term"}
    phrases = {t["value"] for g in parsed["or_groups"] for t in g if t["type"] == "phrase"}

    # tf[doc_id][token] and lines_hit[doc_id][token] for every query token,
    # fetched only for the words in the query instead of the whole index
    tf = {}
    lines_hit = {}
    df = {}

    if terms:
        placeholders = ",".join("?" * len(terms))
        cursor.execute(
            f"SELECT doc_id, word, line_number, frequency FROM index_entries WHERE word IN ({placeholders})",
            tuple(terms)
        )
        for doc_id, word, line_number, freq in cursor.fetchall():
            tf.setdefault(doc_id, {})
            tf[doc_id][word] = tf[doc_id].get(word, 0) + freq
            lines_hit.setdefault(doc_id, {}).setdefault(word, set()).add(line_number)

    for phrase in phrases:
        cursor.execute(
            "SELECT doc_id, line_number, text FROM lines WHERE text LIKE ? ESCAPE '\\'",
            (f"%{_escape_like(phrase)}%",)
        )
        key = f'"{phrase}"'
        for doc_id, line_number, text in cursor.fetchall():
            count = text.lower().count(phrase)
            if count == 0:
                continue
            tf.setdefault(doc_id, {})
            tf[doc_id][key] = tf[doc_id].get(key, 0) + count
            lines_hit.setdefault(doc_id, {}).setdefault(key, set()).add(line_number)

    for doc_tf in tf.values():
        for token in doc_tf:
            df[token] = df.get(token, 0) + 1

    results = []

    for doc_id, doc_tf in tf.items():
        doc = docs.get(doc_id)
        if not doc:
            continue
        filename = doc["filename"]

        if parsed["filename_filter"] and parsed["filename_filter"] not in filename.lower():
            continue

        # a doc is a hit if ANY group fully matches (tokens within a group are AND'd)
        matched_tokens = set()
        for group in parsed["or_groups"]:
            keys = [t["value"] if t["type"] == "term" else f'"{t["value"]}"' for t in group]
            if all(k in doc_tf for k in keys):
                matched_tokens.update(keys)

        if not matched_tokens:
            continue

        bm25_score = 0.0
        filename_score = 0.0
        name_tokens = re.findall(r'[a-z0-9]+', os.path.splitext(filename)[0].lower())
        name_words = set(name_tokens)
        name_text = " ".join(name_tokens)  # keeps word order for phrase checks

        for token in matched_tokens:
            token_score = bm25(doc_tf[token], df[token], doc["length"], avg_doc_len, total_docs)
            if token.startswith('"'):
                token_score *= PHRASE_WEIGHT
                in_name = token.strip('"') in name_text
            else:
                in_name = token in name_words
            bm25_score += token_score
            if in_name:
                filename_score += FILENAME_BOOST * idf(df[token], total_docs)

        # lines where several different query tokens show up together
        line_token_count = {}
        for token in matched_tokens:
            for ln in lines_hit[doc_id][token]:
                line_token_count[ln] = line_token_count.get(ln, 0) + 1
        cooccur_lines = sum(1 for c in line_token_count.values() if c >= 2)
        proximity_score = PROXIMITY_BOOST * min(cooccur_lines, 3) if len(matched_tokens) > 1 else 0.0

        score = bm25_score + filename_score + proximity_score

        # best snippets: lines with the most distinct query tokens first
        best_lines = sorted(line_token_count, key=lambda ln: (-line_token_count[ln], ln))[:3]
        snippet_details = []
        if best_lines:
            placeholders = ",".join("?" * len(best_lines))
            cursor.execute(
                f"SELECT line_number, page, text FROM lines WHERE doc_id = ? AND line_number IN ({placeholders}) ORDER BY line_number",
                (doc_id, *best_lines)
            )
            snippet_details = [
                {"line": ln, "page": page, "text": text}
                for ln, page, text in cursor.fetchall()
            ]

        word_frequencies = {t: doc_tf[t] for t in matched_tokens}

        results.append({
            "filename": filename,
            "file_type": doc["file_type"],
            "score": round(score, 3),
            "score_breakdown": {
                "bm25": round(bm25_score, 3),
                "filename_boost": round(filename_score, 3),
                "proximity_boost": round(proximity_score, 3),
            },
            "matched_words": sorted(matched_tokens),
            "word_frequencies": word_frequencies,
            "snippets": [s["text"] for s in snippet_details],
            "snippet_details": snippet_details,
            "total_matches": len(matched_tokens)
        })

    conn.close()

    results.sort(key=lambda r: (-r["score"], r["filename"]))
    total_found = len(results)
    results = results[:top_n]

    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

    return {
        "results": results,
        "total_found": total_found,
        "search_time_ms": elapsed_ms,
        "parsed_query": parsed
    }


if __name__ == "__main__":
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DB_PATH = os.path.join(BASE_DIR, "data", "search_index.db")
    DOCS_FOLDER = os.path.join(BASE_DIR, "data", "documents")

    # rebuild the index if it's missing or from the old .txt-only version
    from indexer import ensure_index
    ensure_index(DOCS_FOLDER, DB_PATH)

    test_queries = [
        "python",
        "database sql",
        '"machine learning"',
        "python OR java",
        'filename:python_programming.txt list',
    ]

    for query in test_queries:
        print(f"\nQuery: '{query}'")
        outcome = search(query, DB_PATH, DOCS_FOLDER)
        results = outcome["results"]
        print(f"({outcome['search_time_ms']} ms)")

        if not results:
            print("No results found.")
        else:
            for i, r in enumerate(results, 1):
                print(f"{i}. {r['filename']} (score: {r['score']}, matched: {r['matched_words']})")
                print(f"   breakdown: {r['score_breakdown']}")
                print(f"   frequencies: {r['word_frequencies']}")
                for snippet in r['snippets'][:2]:
                    print(f"   -> {snippet[:80]}...")
