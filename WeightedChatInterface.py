# WeightedChatInterface.py
import sys
import os
import shutil
import zipfile
import tempfile
from pathlib import Path

# Ensure local module path is available
module_path = str(Path(__file__).resolve().parent)
if module_path not in sys.path:
    sys.path.append(module_path)

# Import project modules
try:
    from CapstoneIntegration import WeightedIntegratedAnalyzer  # (kept for future use)
    from CapstoneImportOnly import ImportInstructions
    from CapstoneImportSample import ImportSample
    from memory_db import MemoryDB
    from extractors import read_textlike, split_code_and_comments, ALLOWED_DOCS, ALLOWED_SCRIPTS
    from ai_provider import AIProvider
    print("✅ Imported ImportInstructions and ImportSample")
    print("✅ Successfully imported integration modules")
except ImportError as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)


# ---------- helpers ----------
def _dedupe_preserve_order(items):
    seen = set()
    out = []
    for it in items:
        key = (it or "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(it)
    return out


def _is_macos_junk(p: Path) -> bool:
    name = p.name
    return name.startswith("._") or name == ".DS_Store" or "__MACOSX" in str(p)


def _guess_source_type(path: Path) -> str:
    """
    Heuristic auto-classifier:
      - .ppt/.pptx => slides
      - script extensions => working_solution
      - names with 'solution','answer','sample' => working_solution
      - names with 'slide','lecture','deck','chapter' => slides
      - doc/pdf/txt/md => instructions by default
      - fallback => notes
    """
    name = path.name.lower()
    ext = path.suffix.lower()

    if ext in {".ppt", ".pptx"}:
        return "slides"
    if ext in ALLOWED_SCRIPTS:
        return "working_solution"
    if any(k in name for k in ("solution", "answers", "answer_key", "sample")):
        return "working_solution"
    if any(k in name for k in ("slide", "slides", "lecture", "deck", "chapter")):
        return "slides"
    if ext in ALLOWED_DOCS:
        return "instructions"
    return "notes"


class WeightedChatInterface:
    """
    Instructor REPL for uploading multiple files, reviewing AI-derived core concepts,
    and publishing an assignment "live".
    """

    def __init__(self):
        self.mdb = MemoryDB()
        self.ai = AIProvider()
        self.importers = []   # list[ImportInstructions] for instructions/slides/notes
        self.samples = []     # list[ImportSample] for code solutions
        self.last_core_concepts = []
        self.assignment_live = False
        self.assignment_title = None

        # --- helper: sanitize raw code/text before sending to AI ---
    def clean_code_for_context(self, text: str) -> str:
        """
        Strip or shorten raw code/text so AI doesn’t parrot it back.
        Keeps only the essence for context.
        """
        import re

        # Remove common code/comment patterns
        text = re.sub(r"```.*?```", "[code omitted]", text, flags=re.S)
        text = re.sub(r"/\*.*?\*/", "[comment omitted]", text, flags=re.S)
        text = re.sub(r"//.*", "", text)   # remove single-line comments
        text = re.sub(r"^\s*(public|private|class|def)\s+\w+.*", "[definition omitted]", text, flags=re.M)

        # Collapse whitespace
        text = " ".join(text.split())

        # Truncate long text
        if len(text) > 200:
            text = text[:200] + "..."

        return text

    # ---------- single-file ingest ----------
    def ingest_reference_file(self, path: str, source_type: str | None = None) -> bool:
        p = Path(path)
        if not p.exists():
            print(f"❌ File not found: {p}")
            return False
        if _is_macos_junk(p) or p.is_dir():
            return False

        source_type = source_type or _guess_source_type(p)
        ext = p.suffix.lower()
        chunks = []

        try:
            # Text-like docs (instructions/slides/notes)
            if ext in ALLOWED_DOCS or ext in {".ppt", ".pptx"}:
                text = read_textlike(str(p))
                parts = [text[i:i + 2000] for i in range(0, len(text), 2000)] or [text]
                for i, t in enumerate(parts):
                    chunks.append({
                        "text": self.clean_code_for_context(t),
                        "source_type": source_type,
                        "file_path": str(p),
                        "section": f"chunk_{i+1}",
                        "weight": 0.7 if source_type == "slides" else 0.6,
                        "priority": "medium",
                        "tags": [source_type],
                    })

                # Run instruction analyzer to extract concepts/grading focus
                if source_type in {"instructions", "slides", "notes"}:
                    imp = ImportInstructions()
                    res = imp.upload_and_parse(str(p))
                    if isinstance(res, dict) and "error" in res:
                        print(f"⚠️  Analyzer warning for {p.name}: {res['error']}")
                    else:
                        self.importers.append(imp)

            # Script-like (solutions / code)
            elif ext in ALLOWED_SCRIPTS:
                sc = split_code_and_comments(str(p))
                if sc.get("comments_only", "").strip():
                    chunks.append({
                        "text": self.clean_code_for_context(sc["comments_only"]),
                        "source_type": "working_solution",
                        "file_path": str(p),
                        "section": "comments",
                        "weight": 0.95,
                        "priority": "high",
                        "tags": ["working_solution", "comments", "benchmark"],
                        "language": sc.get("language"),
                    })
                if sc.get("code_no_comments", "").strip():
                    chunks.append({
                        "text": self.clean_code_for_context(sc["code_no_comments"]),
                        "source_type": "working_solution",
                        "file_path": str(p),
                        "section": "code_no_comments",
                        "weight": 0.65,
                        "priority": "medium",
                        "tags": ["working_solution", "code"],
                        "language": sc.get("language"),
                    })

                # Sample analyzer (extracts learning explanations, etc.)
                samp = ImportSample({})
                sres = samp.upload_and_analyze(str(p))
                if isinstance(sres, dict) and "error" in sres:
                    print(f"⚠️  Sample warning for {p.name}: {sres['error']}")
                else:
                    self.samples.append(samp)

            else:
                print(f"❌ Unsupported file type: {ext}")
                return False

            if chunks:
                self.mdb.add_documents(chunks)
                print(f"✅ Ingested {p.name} as {source_type} ({len(chunks)} chunk(s))")
            else:
                print(f"⚠️  Nothing ingested for {p.name} (empty or unsupported).")

            return True

        except Exception as e:
            print(f"❌ Error ingesting {p.name}: {e}")
            return False

    # ---------- bulk ingest (zip or folder) ----------
    def ingest_all(self, target: str):
        target_path = Path(target).expanduser()
        if not target_path.exists():
            print(f"❌ Path not found: {target_path}")
            return

        files_to_process = []
        tmpdir = None

        try:
            if target_path.is_dir():
                for root, _, files in os.walk(target_path):
                    for fname in files:
                        p = Path(root) / fname
                        if _is_macos_junk(p):
                            continue
                        files_to_process.append(p)
            elif target_path.suffix.lower() == ".zip":
                tmpdir = Path(tempfile.mkdtemp(prefix="capstone_ingest_"))
                try:
                    with zipfile.ZipFile(target_path, "r") as zf:
                        zf.extractall(tmpdir)
                except Exception as e:
                    print(f"❌ Failed to extract zip: {e}")
                    return
                for root, _, files in os.walk(tmpdir):
                    for fname in files:
                        p = Path(root) / fname
                        if _is_macos_junk(p):
                            continue
                        files_to_process.append(p)
            else:
                print("❌ ingest-all expects a folder or a .zip file.")
                return

            if not files_to_process:
                print("⚠️  No files found to ingest.")
                return

            print("\n🗂️  Mapping Summary:")
            for p in files_to_process:
                st = _guess_source_type(p)
                print(f"   📄 Found {p.name} → auto as {st}")

            for p in files_to_process:
                st = _guess_source_type(p)
                print(f"📥 Ingesting {p.name} as {st}")
                self.ingest_reference_file(str(p), source_type=st)

            print("✅ Bulk ingest complete.")

        finally:
            if tmpdir and tmpdir.exists():
                shutil.rmtree(tmpdir, ignore_errors=True)

    # ---------- concept review ----------
    def review_concepts(self):
        """
        Aggregate proposed core concepts & grading focus from all ImportInstructions
        and dedupe across files.
        """
        if not self.importers:
            print("❌ No instruction/notes/slides files ingested yet.")
            return

        concepts = []
        grading_focus = []

        for imp in self.importers:
            pri = imp.get_priority_content_for_response()
            concepts.extend(pri.get("priority_concepts", []))
            grading_focus.extend(pri.get("grading_focus", []))

        concepts = _dedupe_preserve_order(concepts)
        grading_focus = _dedupe_preserve_order(grading_focus)

        self.last_core_concepts = concepts[:20]

        print("\n🧠 Proposed core concepts:")
        if not self.last_core_concepts:
            print("  (none detected yet)")
        else:
            for i, c in enumerate(self.last_core_concepts, 1):
                print(f"  {i}. {c}")

        if grading_focus:
            print("\n🎯 Grading focus (from instructions):")
            for g in grading_focus:
                print(f"  • {g}")

        print('\n(Use `publish "Your Title"` when ready.)')

    # ---------- retrieval QA ----------
    def answer_with_retrieval(self, question: str) -> str:
        hits = self.mdb.search(question, k=6)

        # --- Summarize context snippets before sending ---
        context_parts = []
        for i, h in enumerate(hits[:4]):
            snippet = " ".join(h['text'].split())  # collapse whitespace
            snippet = snippet[:200]  # hard trim
            context_parts.append(f"[{i+1}] {snippet}")

        short_context = "; ".join(context_parts) if context_parts else "No relevant context."

        # --- Strong system instruction ---
        system = (
            "You are a helpful AI tutor. "
            "Use background knowledge plus the provided context to answer questions in plain English. "
            "Never copy raw text or code directly. "
            "Always summarize what the context means, in 2–4 clear sentences. "
            "If code appears in the context, describe its purpose (e.g., 'sets up a class', 'handles input') "
            "instead of repeating it."
        )

        # --- User prompt (no giant dumps) ---
        user = f"Student asked: {question}\nRelevant context (summarized): {short_context}\n\nAnswer:"

        # --- Generate answer ---
        answer = self.ai.generate(system, user, max_tokens=2000)

        return answer.strip()



    # ---------- publish toggle ----------
    def publish(self, title: str | None):
        if not self.importers:
            print("❌ You must ingest instructions/notes first.")
            return
        self.assignment_live = True
        self.assignment_title = title or "Untitled Assignment"
        print(f'🚀 Assignment "{self.assignment_title}" is now LIVE for students.')
        print("   (This sets a flag locally; wire this to your LMS/DB when ready.)")

    # ---------- help ----------
    def show_help(self):
        print("\n🆘 Commands:")
        print('  ingest "/full/path.ext" <slides|instructions|working_solution|notes>')
        print('  ingest-all "/folder/or/zip"     → bulk ingest all files (auto classifies)')
        print('  ingest-dir "/folder"            → alias of ingest-all (folder)')
        print('  ingest-batch "/zip/or/folder"   → alias of ingest-all (zip or folder)')
        print('  review-concepts                 → show AI-proposed key concepts & grading focus')
        print('  publish "Your Title"            → mark assignment LIVE')
        print('  ask <question>                  → retrieval-augmented answer')
        print('  help                            → show this help')
        print('  quit                            → exit\n')

    # ---------- REPL ----------
    def chat_loop(self):
        print("\n🎯 AI Tutor (Instructor Module)")
        print("Type 'help' to see commands.")
        while True:
            try:
                raw = input("👤 You: ").strip()
                if not raw:
                    continue

                cmd = raw.split(" ", 1)[0].lower()

                if cmd in {"quit", "exit", "bye"}:
                    print("🤖 AI Tutor: Goodbye!")
                    break

                if cmd == "help":
                    self.show_help()
                    continue

                if cmd == "ingest":
                    try:
                        _, rest = raw.split(" ", 1)
                        file_path, src = [x.strip() for x in rest.rsplit(" ", 1)]
                        self.ingest_reference_file(file_path.strip('"'), src)
                    except Exception:
                        print('Usage: ingest "/full/path.ext" <slides|instructions|working_solution|notes>')
                    continue

                # NEW: aliases for bulk ingest
                if cmd in {"ingest-all", "ingest-dir", "ingest-batch"}:
                    try:
                        _, arg = raw.split(" ", 1)
                        target = arg.strip().strip('"')
                        self.ingest_all(target)
                    except Exception:
                        print('Usage: ingest-all|ingest-dir|ingest-batch "/folder/or/zip"')
                    continue

                if cmd == "review-concepts":
                    self.review_concepts()
                    continue

                if cmd == "publish":
                    title = ""
                    if " " in raw:
                        title = raw.split(" ", 1)[1].strip().strip('"')
                    self.publish(title)
                    continue

                if cmd == "ask":
                    if " " not in raw:
                        print("Usage: ask <question>")
                        continue
                    q = raw.split(" ", 1)[1].strip()
                    print(f"🤖 AI Tutor: {self.answer_with_retrieval(q)}")
                    continue

                print("❌ Unknown command. Type 'help'.")

            except KeyboardInterrupt:
                print("\n🤖 AI Tutor: Goodbye!")
                break


if __name__ == "__main__":
    cli = WeightedChatInterface()
    cli.chat_loop()
