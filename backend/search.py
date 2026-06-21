import sqlite3
import os
import re
import time


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


def search(query, db_path, docs_folder, top_n=5):
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
        if parsed["filename_filter"] and parsed["filename_filter"] not in filename.lower():
            continue

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

        filepath = os.path.join(docs_folder, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except FileNotFoundError:
            continue

        matched_terms = {}
        matched_lines = set()
        any_group_matched = False

        # a doc is a hit if ANY group fully matches (terms within a group are AND'd)
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
                else:
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
        print(f"\nQuery: '{query}'")
        outcome = search(query, DB_PATH, DOCS_FOLDER)
        results = outcome["results"]
        print(f"({outcome['search_time_ms']} ms)")

        if not results:
            print("No results found.")
        else:
            for i, r in enumerate(results, 1):
                print(f"{i}. {r['filename']} (score: {r['score']}, matched: {r['matched_words']})")
                print(f"   frequencies: {r['word_frequencies']}")
                for snippet in r['snippets'][:2]:
                    print(f"   -> {snippet[:80]}...")
