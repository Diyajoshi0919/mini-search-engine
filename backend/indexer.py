import sqlite3
import os
import re


def create_database(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT UNIQUE,
            total_words INTEGER
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

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_word ON index_entries(word)
    """)

    conn.commit()
    return conn


def clean_word(word):
    word = word.lower()
    word = re.sub(r'[^a-z0-9]', '', word)
    return word


def index_document(conn, filepath, filename):
    cursor = conn.cursor()

    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    word_data = {}
    total_words = 0

    for line_number, line in enumerate(lines, start=1):
        words = line.strip().split()

        for raw_word in words:
            word = clean_word(raw_word)

            if len(word) < 2:
                continue

            total_words += 1

            if word not in word_data:
                word_data[word] = {}
            if line_number not in word_data[word]:
                word_data[word][line_number] = 0
            word_data[word][line_number] += 1

    cursor.execute(
        "INSERT OR REPLACE INTO documents (filename, total_words) VALUES (?, ?)",
        (filename, total_words)
    )
    doc_id = cursor.lastrowid

    for word, lines_dict in word_data.items():
        for line_num, freq in lines_dict.items():
            cursor.execute(
                "INSERT INTO index_entries (word, doc_id, line_number, frequency) VALUES (?, ?, ?, ?)",
                (word, doc_id, line_num, freq)
            )

    conn.commit()
    print(f"Indexed: {filename} ({total_words} words, {len(word_data)} unique)")


def index_all_documents(docs_folder, db_path):
    conn = create_database(db_path)

    cursor = conn.cursor()
    cursor.execute("DELETE FROM index_entries")
    cursor.execute("DELETE FROM documents")
    conn.commit()

    txt_files = [f for f in os.listdir(docs_folder) if f.endswith('.txt')]

    if not txt_files:
        print("No .txt files found in documents folder.")
        return

    print(f"Found {len(txt_files)} documents to index")

    for filename in txt_files:
        filepath = os.path.join(docs_folder, filename)
        index_document(conn, filepath, filename)

    cursor.execute("SELECT COUNT(*) FROM index_entries")
    total_entries = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT word) FROM index_entries")
    unique_words = cursor.fetchone()[0]

    print(f"Indexing complete: {total_entries} entries, {unique_words} unique words, {len(txt_files)} documents")

    conn.close()


if __name__ == "__main__":
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DOCS_FOLDER = os.path.join(BASE_DIR, "data", "documents")
    DB_PATH = os.path.join(BASE_DIR, "data", "search_index.db")

    index_all_documents(DOCS_FOLDER, DB_PATH)
