import sqlite3
import os
import re

from extractors import extract_lines, is_supported, SUPPORTED_EXTENSIONS

# bump this whenever the table layout changes, so old databases get rebuilt
SCHEMA_VERSION = 2


def create_database(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("PRAGMA user_version")
    if cursor.fetchone()[0] != SCHEMA_VERSION:
        # old layout from before PDF support: start fresh
        cursor.execute("DROP TABLE IF EXISTS index_entries")
        cursor.execute("DROP TABLE IF EXISTS lines")
        cursor.execute("DROP TABLE IF EXISTS documents")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT UNIQUE,
            file_type TEXT,
            total_words INTEGER,
            total_lines INTEGER
        )
    """)

    # the extracted text lives here, so search never has to re-open a PDF
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER,
            line_number INTEGER,
            page INTEGER,
            text TEXT,
            FOREIGN KEY (doc_id) REFERENCES documents(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS index_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT,
            doc_id INTEGER,
            line_number INTEGER,
            frequency INTEGER DEFAULT 1,
            FOREIGN KEY (doc_id) REFERENCES documents(id)
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_word ON index_entries(word)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_entries_doc ON index_entries(doc_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_lines_doc ON lines(doc_id, line_number)")
    cursor.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    conn.commit()
    return conn


def clean_word(word):
    word = word.lower()
    word = re.sub(r'[^a-z0-9]', '', word)
    return word


def _delete_doc_rows(cursor, filename):
    cursor.execute("SELECT id FROM documents WHERE filename = ?", (filename,))
    row = cursor.fetchone()
    if row:
        doc_id = row[0]
        cursor.execute("DELETE FROM index_entries WHERE doc_id = ?", (doc_id,))
        cursor.execute("DELETE FROM lines WHERE doc_id = ?", (doc_id,))
        cursor.execute("DELETE FROM documents WHERE id = ?", (doc_id,))


def index_document(conn, filepath, filename):
    """Index (or re-index) one file. Returns the number of words indexed."""
    cursor = conn.cursor()

    lines = extract_lines(filepath)

    # re-uploading a file replaces its old entries instead of duplicating them
    _delete_doc_rows(cursor, filename)

    word_data = {}
    total_words = 0

    for line_number, (page, text) in enumerate(lines, start=1):
        for raw_word in text.split():
            word = clean_word(raw_word)

            if len(word) < 2:
                continue

            total_words += 1
            word_data.setdefault(word, {})
            word_data[word][line_number] = word_data[word].get(line_number, 0) + 1

    file_type = os.path.splitext(filename)[1].lower().lstrip('.')
    cursor.execute(
        "INSERT INTO documents (filename, file_type, total_words, total_lines) VALUES (?, ?, ?, ?)",
        (filename, file_type, total_words, len(lines))
    )
    doc_id = cursor.lastrowid

    cursor.executemany(
        "INSERT INTO lines (doc_id, line_number, page, text) VALUES (?, ?, ?, ?)",
        [(doc_id, i, page, text) for i, (page, text) in enumerate(lines, start=1)]
    )

    cursor.executemany(
        "INSERT INTO index_entries (word, doc_id, line_number, frequency) VALUES (?, ?, ?, ?)",
        [
            (word, doc_id, line_num, freq)
            for word, lines_dict in word_data.items()
            for line_num, freq in lines_dict.items()
        ]
    )

    conn.commit()
    print(f"Indexed: {filename} ({total_words} words, {len(word_data)} unique)")

    if total_words == 0 and file_type == "pdf":
        print(f"  warning: no text found in {filename}. It may be a scanned PDF (images only).")

    return total_words


def remove_document(db_path, filename):
    conn = create_database(db_path)
    _delete_doc_rows(conn.cursor(), filename)
    conn.commit()
    conn.close()


def list_supported_files(docs_folder):
    if not os.path.exists(docs_folder):
        return []
    return sorted(f for f in os.listdir(docs_folder) if is_supported(f))


def index_all_documents(docs_folder, db_path):
    conn = create_database(db_path)

    cursor = conn.cursor()
    cursor.execute("DELETE FROM index_entries")
    cursor.execute("DELETE FROM lines")
    cursor.execute("DELETE FROM documents")
    conn.commit()

    files = list_supported_files(docs_folder)

    if not files:
        print(f"No supported files found. Supported types: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
        conn.close()
        return

    print(f"Found {len(files)} documents to index")

    for filename in files:
        filepath = os.path.join(docs_folder, filename)
        try:
            index_document(conn, filepath, filename)
        except Exception as e:
            # one corrupt file shouldn't stop the rest from being indexed
            print(f"Skipped {filename}: {e}")

    cursor.execute("SELECT COUNT(*) FROM index_entries")
    total_entries = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT word) FROM index_entries")
    unique_words = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM documents")
    doc_count = cursor.fetchone()[0]

    print(f"Indexing complete: {total_entries} entries, {unique_words} unique words, {doc_count} documents")

    conn.close()


def ensure_index(docs_folder, db_path):
    """Build the index if it's missing or was made by an older version."""
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        if version == SCHEMA_VERSION:
            return
    index_all_documents(docs_folder, db_path)


if __name__ == "__main__":
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DOCS_FOLDER = os.path.join(BASE_DIR, "data", "documents")
    DB_PATH = os.path.join(BASE_DIR, "data", "search_index.db")

    index_all_documents(DOCS_FOLDER, DB_PATH)
