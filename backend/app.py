from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import sys
import sqlite3

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from search import search, suggest
from indexer import (
    create_database, index_document, remove_document,
    ensure_index, list_supported_files,
)
from extractors import is_supported, SUPPORTED_EXTENSIONS

app = Flask(__name__)
CORS(app)

# reject anything bigger than 20 MB per request
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "search_index.db")
DOCS_FOLDER = os.path.join(BASE_DIR, "data", "documents")

os.makedirs(DOCS_FOLDER, exist_ok=True)

# builds the index on first start (or after a schema upgrade), so the
# server works even when search_index.db isn't committed to git
ensure_index(DOCS_FOLDER, DB_PATH)


@app.route('/')
def home():
    return jsonify({
        "status": "running",
        "message": "Mini Search Engine API is live",
        "supported_file_types": sorted(SUPPORTED_EXTENSIONS),
        "endpoints": {
            "search": "/search?q=your+query",
            "suggest": "/suggest?q=partial+que",
            "stats": "/stats",
            "upload": "POST /upload",
            "documents": "/documents"
        }
    })


@app.route('/search')
def search_endpoint():
    query = request.args.get('q', '').strip()
    limit = request.args.get('limit', 5, type=int)
    # exact=1 turns off spelling correction ("Search instead for ...")
    exact = request.args.get('exact', '0') == '1'

    if not query:
        return jsonify({"error": "Query parameter 'q' is required"}), 400

    if limit < 1 or limit > 20:
        limit = 5

    if not os.path.exists(DB_PATH):
        return jsonify({"error": "Search index not found. Please run indexer.py first."}), 500

    outcome = search(query, DB_PATH, DOCS_FOLDER, top_n=limit, exact=exact)

    return jsonify({
        "query": query,
        "total_results": len(outcome["results"]),
        "total_found": outcome.get("total_found", len(outcome["results"])),
        "results": outcome["results"],
        "search_time_ms": outcome["search_time_ms"],
        "parsed_query": outcome["parsed_query"],
        "corrected_query": outcome["corrected_query"],
        "did_you_mean": outcome["did_you_mean"]
    })


@app.route('/suggest')
def suggest_endpoint():
    partial = request.args.get('q', '')
    limit = request.args.get('limit', 6, type=int)
    limit = max(1, min(limit, 10))

    if not os.path.exists(DB_PATH):
        return jsonify({"query": partial, "suggestions": []})

    return jsonify({
        "query": partial,
        "suggestions": suggest(partial, DB_PATH, limit=limit)
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

    cursor.execute("SELECT file_type, COUNT(*) FROM documents GROUP BY file_type")
    by_type = {ft: n for ft, n in cursor.fetchall()}

    conn.close()

    return jsonify({
        "documents_indexed": doc_count,
        "unique_words": word_count,
        "total_words_indexed": total_words_indexed,
        "total_index_entries": entry_count,
        "files": filenames,
        "files_by_type": by_type
    })


@app.route('/upload', methods=['POST'])
def upload_document():
    # getlist handles one file or many sent under the same 'file' key
    files = request.files.getlist('file')
    files = [f for f in files if f and f.filename]

    if not files:
        return jsonify({"error": "No file sent. Use key 'file' in form data."}), 400

    uploaded, failed = [], []
    conn = create_database(DB_PATH)

    for file in files:
        # basename strips any path components, blocks path traversal
        filename = os.path.basename(file.filename)

        if not is_supported(filename):
            failed.append({"filename": filename,
                           "error": f"Unsupported type. Allowed: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"})
            continue

        save_path = os.path.join(DOCS_FOLDER, filename)
        file.save(save_path)

        try:
            # only index the new file instead of rebuilding everything
            words = index_document(conn, save_path, filename)
            entry = {"filename": filename, "words": words}
            if words == 0:
                entry["warning"] = "No readable text found (scanned PDF or empty file?)"
            uploaded.append(entry)
        except Exception as e:
            os.remove(save_path)
            failed.append({"filename": filename, "error": f"Could not read file: {e}"})

    conn.close()

    status = 200 if uploaded else 400
    return jsonify({
        "success": bool(uploaded),
        "uploaded": uploaded,
        "failed": failed,
        "message": f"{len(uploaded)} file(s) indexed, {len(failed)} failed.",
        # kept for older frontends that expect a single filename
        "filename": uploaded[0]["filename"] if uploaded else None,
        "error": failed[0]["error"] if failed and not uploaded else None
    }), status


@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": "File too large. Max upload size is 20 MB."}), 413


@app.route('/documents')
def list_documents():
    files = list_supported_files(DOCS_FOLDER)
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
    remove_document(DB_PATH, filename)
    print(f"Deleted: {filename}")

    return jsonify({
        "success": True,
        "message": f"'{filename}' deleted and index updated."
    })


if __name__ == "__main__":
    print(f"Database : {DB_PATH}")
    print(f"Documents: {DOCS_FOLDER}")
    print("Server   : http://localhost:5000")
    app.run(debug=True, port=5000)
