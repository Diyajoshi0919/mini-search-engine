from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import sys
import sqlite3

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from search import search
from indexer import index_all_documents

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "search_index.db")
DOCS_FOLDER = os.path.join(BASE_DIR, "data", "documents")


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


@app.route('/stats')
def stats():
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


@app.route('/upload', methods=['POST'])
def upload_document():
    if 'file' not in request.files:
        return jsonify({"error": "No file sent. Use key 'file' in form data."}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({"error": "No file selected."}), 400

    if not file.filename.endswith('.txt'):
        return jsonify({"error": "Only .txt files are allowed."}), 400

    # basename strips any path components, blocks path traversal
    filename = os.path.basename(file.filename)
    save_path = os.path.join(DOCS_FOLDER, filename)

    file.save(save_path)
    print(f"Saved: {filename}")

    index_all_documents(DOCS_FOLDER, DB_PATH)

    return jsonify({
        "success": True,
        "message": f"'{filename}' uploaded and indexed successfully.",
        "filename": filename
    })


@app.route('/documents')
def list_documents():
    if not os.path.exists(DOCS_FOLDER):
        return jsonify({"documents": []})

    files = [f for f in os.listdir(DOCS_FOLDER) if f.endswith('.txt')]
    files.sort()

    return jsonify({
        "total": len(files),
        "documents": files
    })


@app.route('/documents/<filename>', methods=['DELETE'])
def delete_document(filename):
    filename = os.path.basename(filename)
    file_path = os.path.join(DOCS_FOLDER, filename)

    if not os.path.exists(file_path):
        return jsonify({"error": f"File '{filename}' not found."}), 404

    os.remove(file_path)
    print(f"Deleted: {filename}")

    index_all_documents(DOCS_FOLDER, DB_PATH)

    return jsonify({
        "success": True,
        "message": f"'{filename}' deleted and index updated."
    })


if __name__ == "__main__":
    print(f"Database : {DB_PATH}")
    print(f"Documents: {DOCS_FOLDER}")
    print("Server   : http://localhost:5000")
    app.run(debug=True, port=5000)
