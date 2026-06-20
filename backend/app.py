"""
APP.PY — The Flask REST API Server

Endpoints:
    GET  /              → Health check
    GET  /search?q=...  → Search and return results as JSON
    GET  /stats         → Index statistics
    POST /upload        → Upload a .txt file, auto re-index it
    GET  /documents     → List all uploaded documents
    DELETE /documents/<filename> → Delete a document and re-index
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from search import search
from indexer import index_all_documents

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "search_index.db")
DOCS_FOLDER = os.path.join(BASE_DIR, "data", "documents")


# ─────────────────────────────────────────────
# Route 1: Health Check
# ─────────────────────────────────────────────

@app.route('/')
def home():
    return jsonify({
        "status": "running",
        "message": "Mini Search Engine API is live",
        "endpoints": {
            "search": "/search?q=your+query",
            "stats": "/stats",
            "upload": "POST /upload",
            "documents": "/documents"
        }
    })


# ─────────────────────────────────────────────
# Route 2: Search
# ─────────────────────────────────────────────

@app.route('/search')
def search_endpoint():
    query = request.args.get('q', '').strip()
    limit = request.args.get('limit', 5, type=int)

    if not query:
        return jsonify({"error": "Query parameter 'q' is required"}), 400

    if limit < 1 or limit > 20:
        limit = 5

    if not os.path.exists(DB_PATH):
        return jsonify({"error": "Search index not found. Please run indexer.py first."}), 500

    outcome = search(query, DB_PATH, DOCS_FOLDER, top_n=limit)

    return jsonify({
        "query": query,
        "total_results": len(outcome["results"]),
        "results": outcome["results"],
        "search_time_ms": outcome["search_time_ms"],
        "parsed_query": outcome["parsed_query"]
    })


# ─────────────────────────────────────────────
# Route 3: Stats
# ─────────────────────────────────────────────

@app.route('/stats')
def stats():
    import sqlite3

    if not os.path.exists(DB_PATH):
        return jsonify({"error": "Index not found"}), 404

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM documents")
    doc_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT word) FROM index_entries")
    word_count = cursor.fetchone()[0]

    cursor.execute("SELECT COALESCE(SUM(total_words), 0) FROM documents")
    total_words_indexed = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM index_entries")
    entry_count = cursor.fetchone()[0]

    cursor.execute("SELECT filename FROM documents")
    filenames = [row[0] for row in cursor.fetchall()]

    conn.close()

    return jsonify({
        "documents_indexed": doc_count,
        "unique_words": word_count,
        "total_words_indexed": total_words_indexed,
        "total_index_entries": entry_count,
        "files": filenames
    })


# ─────────────────────────────────────────────
# Route 4: Upload Document
# ─────────────────────────────────────────────

@app.route('/upload', methods=['POST'])
def upload_document():
    """
    Accepts a .txt file upload from the browser.

    What happens step by step:
    1. Browser sends a POST request with the file attached
    2. Flask reads the file from the request
    3. We validate — only .txt files allowed
    4. Save the file to data/documents/ folder
    5. Re-run the indexer so the new file is searchable immediately
    6. Return success response

    Why re-index everything and not just the new file?
    Simplicity. For a small document set this is fast enough.
    In production you would do incremental indexing.
    """

    # Check if file was actually sent in the request
    # request.files is a dict of uploaded files
    if 'file' not in request.files:
        return jsonify({"error": "No file sent. Use key 'file' in form data."}), 400

    file = request.files['file']

    # Empty filename means user submitted without selecting a file
    if file.filename == '':
        return jsonify({"error": "No file selected."}), 400

    # Only allow .txt files — reject everything else
    if not file.filename.endswith('.txt'):
        return jsonify({"error": "Only .txt files are allowed."}), 400

    # Sanitize filename — remove any path components for security
    # e.g. "../../etc/passwd" becomes "passwd" — prevents path traversal attack
    filename = os.path.basename(file.filename)
    save_path = os.path.join(DOCS_FOLDER, filename)

    # Save the file to documents folder
    file.save(save_path)
    print(f"📁 File saved: {filename}")

    # Re-index all documents including the new one
    # This rebuilds the entire SQLite index from scratch
    print(f"🔄 Re-indexing all documents...")
    index_all_documents(DOCS_FOLDER, DB_PATH)

    return jsonify({
        "success": True,
        "message": f"'{filename}' uploaded and indexed successfully.",
        "filename": filename
    })


# ─────────────────────────────────────────────
# Route 5: List All Documents
# ─────────────────────────────────────────────

@app.route('/documents')
def list_documents():
    """
    Returns a list of all .txt files currently in the documents folder.
    The frontend uses this to show the document library.
    """
    if not os.path.exists(DOCS_FOLDER):
        return jsonify({"documents": []})

    files = [f for f in os.listdir(DOCS_FOLDER) if f.endswith('.txt')]
    files.sort()

    return jsonify({
        "total": len(files),
        "documents": files
    })


# ─────────────────────────────────────────────
# Route 6: Delete a Document
# ─────────────────────────────────────────────

@app.route('/documents/<filename>', methods=['DELETE'])
def delete_document(filename):
    """
    Deletes a document from the folder and re-indexes.
    Called when user clicks the delete button on a document.
    """

    # Sanitize — prevent path traversal
    filename = os.path.basename(filename)
    file_path = os.path.join(DOCS_FOLDER, filename)

    if not os.path.exists(file_path):
        return jsonify({"error": f"File '{filename}' not found."}), 404

    os.remove(file_path)
    print(f"🗑️ Deleted: {filename}")

    # Re-index without the deleted file
    index_all_documents(DOCS_FOLDER, DB_PATH)

    return jsonify({
        "success": True,
        "message": f"'{filename}' deleted and index updated."
    })


# ─────────────────────────────────────────────
# Start Server
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("\n🔍 Mini Search Engine API")
    print("=" * 40)
    print(f"   Database : {DB_PATH}")
    print(f"   Documents: {DOCS_FOLDER}")
    print(f"   Server   : http://localhost:5000")
    print("=" * 40)
    print("\n✅ Server starting...\n")

    app.run(debug=True, port=5000)
