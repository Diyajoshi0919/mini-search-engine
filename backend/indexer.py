"""
INDEXER.PY — The "Smart Librarian" that reads all documents and builds the index.

What this file does:
- Reads every .txt file from the documents folder
- Breaks each line into individual words
- Saves to SQLite: which word appears in which file, on which line
- This process is called "building an inverted index"

Run this ONCE before starting the search engine.
"""

import sqlite3  # Built-in Python library for SQLite database
import os       # For reading files and folders
import re       # For text cleaning (removing punctuation)


# ─────────────────────────────────────────────
# STEP 1: Create the Database and Tables
# ─────────────────────────────────────────────

def create_database(db_path):
    """
    Creates the SQLite database with two tables:
    
    Table 1: documents
        Stores each file we indexed.
        id | filename | total_words
    
    Table 2: index_entries  
        The inverted index — one row per (word, document) pair.
        word | doc_id | line_number | frequency
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create documents table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT UNIQUE,
            total_words INTEGER
        )
    """)

    # Create inverted index table
    # This is the heart of the search engine
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

    # Create an index ON the word column so searches are fast
    # Without this, SQLite scans every row — slow for large data
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_word ON index_entries(word)
    """)

    conn.commit()
    return conn


# ─────────────────────────────────────────────
# STEP 2: Clean a Word
# ─────────────────────────────────────────────

def clean_word(word):
    """
    Removes punctuation and converts to lowercase.
    
    Example:
        "Python," → "python"
        "Hello!" → "hello"
        "API." → "api"
    
    Why? So "Python" and "python" match the same index entry.
    """
    word = word.lower()                        # lowercase
    word = re.sub(r'[^a-z0-9]', '', word)      # remove non-alphanumeric
    return word


# ─────────────────────────────────────────────
# STEP 3: Index a Single Document
# ─────────────────────────────────────────────

def index_document(conn, filepath, filename):
    """
    Reads one file and adds all its words to the database.
    
    For each line:
        - Split into words
        - Clean each word
        - Count frequency of each word in this document
        - Save to database
    """
    cursor = conn.cursor()

    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # word_data = { "python": [(line_number, count), ...] }
    # We use a dict to count how many times each word appears
    word_data = {}
    total_words = 0

    for line_number, line in enumerate(lines, start=1):
        words = line.strip().split()  # Split line into words by spaces

        for raw_word in words:
            word = clean_word(raw_word)

            if len(word) < 2:  # Skip single characters like "a", "i"
                continue

            total_words += 1

            # Track which line this word appeared on
            if word not in word_data:
                word_data[word] = {}
            if line_number not in word_data[word]:
                word_data[word][line_number] = 0
            word_data[word][line_number] += 1

    # Save document record to DB
    cursor.execute(
        "INSERT OR REPLACE INTO documents (filename, total_words) VALUES (?, ?)",
        (filename, total_words)
    )
    doc_id = cursor.lastrowid

    # Save each word entry to index
    for word, lines_dict in word_data.items():
        for line_num, freq in lines_dict.items():
            cursor.execute(
                "INSERT INTO index_entries (word, doc_id, line_number, frequency) VALUES (?, ?, ?, ?)",
                (word, doc_id, line_num, freq)
            )

    conn.commit()
    print(f"  ✅ Indexed: {filename} ({total_words} words, {len(word_data)} unique)")


# ─────────────────────────────────────────────
# STEP 4: Index All Documents in a Folder
# ─────────────────────────────────────────────

def index_all_documents(docs_folder, db_path):
    """
    Scans a folder, finds all .txt files, indexes them all.
    This is the main function you call to build the entire index.
    """
    print(f"\n📚 Starting Indexer...")
    print(f"   Documents folder: {docs_folder}")
    print(f"   Database: {db_path}\n")

    conn = create_database(db_path)

    # Clear old index data before re-indexing
    cursor = conn.cursor()
    cursor.execute("DELETE FROM index_entries")
    cursor.execute("DELETE FROM documents")
    conn.commit()

    # Find all .txt files
    txt_files = [f for f in os.listdir(docs_folder) if f.endswith('.txt')]

    if not txt_files:
        print("❌ No .txt files found in documents folder!")
        return

    print(f"Found {len(txt_files)} documents to index:\n")

    for filename in txt_files:
        filepath = os.path.join(docs_folder, filename)
        index_document(conn, filepath, filename)

    # Print summary
    cursor.execute("SELECT COUNT(*) FROM index_entries")
    total_entries = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT word) FROM index_entries")
    unique_words = cursor.fetchone()[0]

    print(f"\n🎉 Indexing Complete!")
    print(f"   Total index entries : {total_entries}")
    print(f"   Unique words indexed: {unique_words}")
    print(f"   Documents indexed   : {len(txt_files)}")

    conn.close()


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    # Paths — adjust if running from different directory
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DOCS_FOLDER = os.path.join(BASE_DIR, "data", "documents")
    DB_PATH = os.path.join(BASE_DIR, "data", "search_index.db")

    index_all_documents(DOCS_FOLDER, DB_PATH)
