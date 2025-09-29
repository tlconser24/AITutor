from flask import Flask, render_template, request, jsonify
import os
from werkzeug.utils import secure_filename

# Project imports
from WeightedChatInterface import WeightedChatInterface

app = Flask(__name__)
cli = WeightedChatInterface()

# Upload directory
UPLOAD_FOLDER = "./uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/ask", methods=["POST"])
def ask():
    data = request.get_json()
    question = data.get("question", "")
    answer = cli.answer_with_retrieval(question)
    return jsonify({"answer": answer})


@app.route("/run_code", methods=["POST"])
def run_code():
    data = request.json
    code = data.get("code")
    try:
        exec_locals = {}
        exec(code, {}, exec_locals)
        result = "\n".join(str(v) for v in exec_locals.values())
    except Exception as e:
        result = str(e)
    return jsonify({"result": result})


# ---------- NEW ROUTE: upload & ingest documents ----------
@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    filename = secure_filename(file.filename)
    save_path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(save_path)

    # Push into MemoryDB
    cli.ingest_reference_file(save_path, source_type=None)

    return jsonify({"status": "ok", "message": f"{filename} ingested."})


if __name__ == "__main__":
    app.run(debug=True)
# ------------- ai_provider.py -------------