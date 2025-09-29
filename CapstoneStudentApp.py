# CapstoneStudentApp.py — Student CLI with PASTE SANDBOX, ChatGPT-style TA "why"
# - code/paste snippets
# - compile/run py/java (targeted file only)
# - "why": ChatGPT-like explanation of last run with local fallback
# - retrieval-augmented ask using MemoryDB + AIProvider

import os
import sys
import re
import time
import subprocess
from pathlib import Path
from typing import Optional

PUBLIC_CLASS_RE = re.compile(r'^\s*public\s+class\s+([A-Za-z_]\w*)\b', re.MULTILINE)
HAS_MAIN_RE = re.compile(r'\bpublic\s+static\s+void\s+main\s*\(\s*String\[\]\s+\w+\s*\)')

def detect_public_class_name(java_src: str) -> str | None:
    m = PUBLIC_CLASS_RE.search(java_src)
    return m.group(1) if m else None

def java_has_main(java_src: str) -> bool:
    return bool(HAS_MAIN_RE.search(java_src))

def normalize_code_args(arg: str | None) -> tuple[str, str | None]:
    """
    Returns (language, explicit_filename)
      language in {"py","java"}
      explicit_filename can be None
    Rules:
      - no arg  -> ("py", None)
      - 'py'    -> ("py", None)
      - 'java'  -> ("java", None)
      - endswith .py/.java -> (detected from ext, filename as-is, preserving case)
      - otherwise -> assume Python filename (add .py)
    """
    if not arg:
        return "py", None
    a = arg.strip()
    low = a.lower()
    if low == "py":
        return "py", None
    if low == "java":
        return "java", None
    if a.endswith(".py"):
        return "py", a  # preserve original case
    if a.endswith(".java"):
        return "java", a  # preserve original case
    # Fallback: treat as Python filename (no forced lowercase)
    return "py", a + ".py"



# --- local modules from the same folder ---
try:
    from ai_provider import AIProvider
except Exception as e:
    print(f"❌ Missing ai_provider.py or import failed: {e}")
    sys.exit(1)

try:
    from memory_db import MemoryDB
except Exception as e:
    print(f"❌ Missing memory_db.py or import failed: {e}")
    sys.exit(1)

# Extractors: text/docs + code/comment splitter (with fallbacks)
try:
    from extractors import read_textlike, split_code_and_comments, ALLOWED_DOCS, ALLOWED_SCRIPTS
except Exception:
    ALLOWED_DOCS = {".txt", ".md", ".pdf", ".docx", ".pptx"}
    ALLOWED_SCRIPTS = {".py", ".java", ".c", ".cpp", ".js", ".ts", ".r", ".html", ".css"}

    def read_textlike(p: str) -> str:
        try:
            return Path(p).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""

    def split_code_and_comments(p: str) -> dict:
        code = ""
        try:
            code = Path(p).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            pass
        return {"comments_only": "", "code_no_comments": code, "language": "unknown"}


def print_banner():
    print("\n" + "="*72)
    print("🎓 CAPSTONE – STUDENT APP (CLI)")
    print("="*72)
    print("Commands:")
    print("  help                                   → show this help")
    print("  ingest \"path\" instructions|slides|notes → add instructor material")
    print("  upload \"path/to/code.ext\"               → add your code (py/java/etc.)")
    print("  paste  \"filename.ext\"                   → paste code into sandbox (end with EOF or :wq or ```)")
    print("  code [py|java|filename.ext]             → paste snippet inline (auto-detect + run)")
    print("  list                                    → list sandbox files")
    print("  open  \"filename.ext\"                    → show sandbox file contents")
    print("  run [filename.ext]                       → run all or one file (py/java)")
    print("  why                                     → explain the last run like a TA")
    print("  ask your question                       → retrieval-augmented answer")
    print("  status                                  → show what’s loaded")
    print("  quit                                    → exit")
    print("-"*72)


class StudentApp:
    def __init__(self):
        self.mdb = MemoryDB()
        self.provider = AIProvider()
        self.student_code_files: list[Path] = []
        self.last_run_output = ""
        self.last_run_errors = ""

        # sandbox directory for pasted code
        self.sandbox_dir = Path.cwd() / "student_sandbox"
        self.sandbox_dir.mkdir(exist_ok=True)

    # ---------- sandbox helpers ----------
    def sandbox_path(self, name: str) -> Path:
        # normalize filename, forbid path traversal
        name = name.strip().replace("\\", "/")
        name = name.split("/")[-1]
        return self.sandbox_dir / name

    def list_sandbox(self):
        print(f"📁 Sandbox: {self.sandbox_dir}")
        files = sorted(self.sandbox_dir.glob("*"))
        if not files:
            print("   (empty)")
            return
        for f in files:
            size = f.stat().st_size
            print(f"   • {f.name} ({size} bytes)")

    def open_sandbox(self, name: str):
        path = self.sandbox_path(name)
        if not path.exists():
            print(f"❌ Not found in sandbox: {name}")
            return
        print(f"--- {name} ---")
        try:
            print(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception as e:
            print(f"⚠️ Could not read file: {e}")

    # ---------- ingest reference material ----------
    def ingest_reference(self, path: str, source_type: str):
        p = Path(path)
        if not p.exists():
            print(f"❌ File not found: {p}")
            return

        ext = p.suffix.lower()
        chunks = []

        if ext in ALLOWED_DOCS:
            text = read_textlike(str(p))
            if not text.strip():
                print(f"⚠️ Could not read {ext} as text.")
                return
            parts = [text[i:i+2000] for i in range(0, len(text), 2000)] or [text]
            for i, t in enumerate(parts):
                chunks.append({
                    "text": t,
                    "source_type": source_type,
                    "file_path": str(p),
                    "section": f"chunk_{i+1}",
                    "weight": 0.7 if source_type == "slides" else 0.6,
                    "priority": "medium",
                    "tags": [source_type],
                })
        elif ext in ALLOWED_SCRIPTS:
            sc = split_code_and_comments(str(p))
            if sc.get("comments_only", "").strip():
                chunks.append({
                    "text": sc["comments_only"],
                    "source_type": "reference_code",
                    "file_path": str(p),
                    "section": "comments",
                    "weight": 0.9,
                    "priority": "high",
                    "tags": ["code","comments"],
                })
            if sc.get("code_no_comments", "").strip():
                chunks.append({
                    "text": sc["code_no_comments"],
                    "source_type": "reference_code",
                    "file_path": str(p),
                    "section": "code_no_comments",
                    "weight": 0.6,
                    "priority": "medium",
                    "tags": ["code"],
                })
        else:
            print(f"❌ Unsupported file type: {ext}")
            return

        if chunks:
            self.mdb.add_documents(chunks)
            print(f"✅ Ingested {p.name} as {source_type} ({len(chunks)} chunk(s))")

    # ---------- upload student code (from disk or sandbox) ----------
    def upload_code(self, path: str):
        p = Path(path)
        if not p.exists():
            print(f"❌ File not found: {p}")
            return
        if p.suffix.lower() not in ALLOWED_SCRIPTS:
            print(f"❌ Not a supported code file: {p.suffix}")
            return

        sc = split_code_and_comments(str(p))
        chunks = []
        if sc.get("comments_only", "").strip():
            chunks.append({
                "text": sc["comments_only"],
                "source_type": "student_submission",
                "file_path": str(p),
                "section": "comments",
                "weight": 0.85,
                "priority": "high",
                "tags": ["student","comments"],
                "language": sc.get("language"),
            })
        if sc.get("code_no_comments", "").strip():
            chunks.append({
                "text": sc["code_no_comments"],
                "source_type": "student_submission",
                "file_path": str(p),
                "section": "code",
                "weight": 0.55,
                "priority": "medium",
                "tags": ["student","code"],
                "language": sc.get("language"),
            })

        if chunks:
            self.mdb.add_documents(chunks)
            if p not in self.student_code_files:
                self.student_code_files.append(p)
            print(f"✅ Uploaded student code: {p.name} ({len(chunks)} chunk(s))")

    # ---------- paste code into sandbox ----------
    def paste_code(self, filename: str):
        if not filename.strip():
            print('Usage: paste "filename.ext"')
            return

        target = self.sandbox_path(filename)
        if target.exists():
            print(f"⚠️ {filename} already exists in sandbox. Overwrite? (y/n) ", end="")
            choice = input("").strip().lower()
            if choice not in {"y","yes"}:
                print("↩️  Cancelled.")
                return

        print(f"\n📝 Paste your code for {filename} below.")
        print("End input with a single line containing one of:  EOF   or   :wq   or   ```")
        print("(Empty line is accepted; we only stop on the markers above.)\n")

        lines = []
        while True:
            try:
                line = input()
            except (EOFError, KeyboardInterrupt):
                print("\n⚠️ Paste cancelled.")
                return
            if line.strip() in {"EOF", ":wq", "```"}:
                break
            lines.append(line)

        try:
            target.write_text("\n".join(lines), encoding="utf-8")
        except Exception as e:
            print(f"❌ Failed to save: {e}")
            return

        print(f"💾 Saved to sandbox: {target.name} ({target.stat().st_size} bytes)")
        # auto-index as student code
        self.upload_code(str(target))
    def handle_code_command(self, arg: Optional[str] = None):
        """
        Supports:
        code                   -> auto-detect language from pasted code (via AIProvider)
        code py/java/...       -> user hint (overrides detection)
        code filename.ext      -> save as that filename; ext informs detection
        Then saves, indexes, and runs the single file.
        """
        from pathlib import Path
        import re
        from time import strftime

        # --- parse optional arg into (user hint, explicit filename) ---
        arg_hint: Optional[str] = None
        explicit_name: Optional[str] = None
        if arg:
            a = arg.strip()
            # user-provided language hint
            if a.lower() in {
                "python","py","java","javascript","typescript","c","cpp","csharp",
                "go","ruby","php","kotlin","swift","rust","scala","r","matlab","shell"
            }:
                arg_hint = a.lower()
            else:
                # treat as requested filename (preserve case; may include extension)
                explicit_name = a

        # --- prompt for paste ---
        print("\n📝 Paste your code below. End with EOF or :wq or ```")
        print("(You can paste multiple lines; blank lines are fine.)\n")

        lines = []
        while True:
            try:
                line = input()
            except (EOFError, KeyboardInterrupt):
                print("\n⚠️ Paste cancelled.")
                return
            if line.strip() in {"EOF", ":wq", "```"}:
                break
            lines.append(line)

        src = "\n".join(lines)

        # --- ask provider to detect language (filename + hint influence decision) ---
        lang, conf, reason = self.provider.detect_language(
            code=src,
            filename=explicit_name,
            user_hint=arg_hint,
            allow_llm=True,   # set False to force offline-only heuristics
        )
        # Debug (optional): print(f"(detected {lang} @ {conf:.2f} via {reason})")

        # --- decide target filename (respect language and Java public class rule) ---
        ts = strftime("%Y%m%d_%H%M%S")

        def _ensure_ext(name: str, want_ext: str) -> str:
            p = Path(name)
            return name if p.suffix else (name + want_ext)

        target_name: str
        if lang == "java":
            # If a public class is present, filename must match it.
            m = re.search(r'^\s*public\s+class\s+([A-Za-z_]\w*)', src, re.MULTILINE)
            public_cls = m.group(1) if m else None
            if public_cls:
                pc_file = f"{public_cls}.java"
                if explicit_name and Path(explicit_name).name != pc_file:
                    print(f"ℹ️ Detected public class '{public_cls}'; renaming file to {pc_file} to match Java rules.")
                target_name = pc_file
            else:
                if explicit_name:
                    target_name = _ensure_ext(explicit_name, ".java")
                else:
                    target_name = f"Main_{ts}.java"
        else:
            # Default to Python filename conventions
            if explicit_name:
                target_name = _ensure_ext(explicit_name, ".py")
            else:
                target_name = f"snippet_{ts}.py"

        # --- save to sandbox (case-preserving) ---
        target = self.sandbox_path(target_name)
        target.parent.mkdir(exist_ok=True)
        try:
            target.write_text(src, encoding="utf-8")
        except Exception as e:
            print(f"❌ Failed to save: {e}")
            return

        size_bytes = target.stat().st_size
        print(f"💾 Saved inline snippet → {target.name} ({size_bytes} bytes)")

        # --- index as student code, then compile/run using your existing helpers ---
        self.upload_code(str(target))
        self.run_code(target.name)


    # ---------- run code (python/java supported) ----------
    def run_code(self, target_name: str | None = None):
        if not self.student_code_files:
            print("⚠️ No student code uploaded yet. Use: upload \"path/file.py|.java\" or paste \"file.java\"")
            return

        # Determine which files to run
        if target_name:
            t = self.sandbox_path(target_name)
            # Exact match by sandbox name or any previously uploaded path with same name
            candidates = [p for p in self.student_code_files if p.name == target_name or p == t]
            if not candidates:
                print(f"⚠️ {target_name} is not in uploaded files. Try 'list' or 'status'.")
                return
            files = candidates  # compile only this file
        else:
            # compile all uploaded (use with caution)
            files = self.student_code_files

        py_files = [p for p in files if p.suffix.lower() == ".py"]
        java_files = [p for p in files if p.suffix.lower() == ".java"]

        # Reset last run
        self.last_run_output = ""
        self.last_run_errors = ""

        if py_files:
            # run each python file separately (the one with __main__ takes precedence)
            self._run_python(py_files)

        if java_files:
            # compile/run only the selected java files
            self._run_java(java_files)

        # Save run outputs to MemoryDB for retrieval & why
        run_text = ""
        if self.last_run_output:
            run_text += f"[RUN OUTPUT]\n{self.last_run_output}\n"
        if self.last_run_errors:
            run_text += f"[RUN ERRORS]\n{self.last_run_errors}\n"

        if run_text.strip():
            # Mark source_type by language for better why()
            src_type = "run_output"
            if java_files and not py_files:
                src_type = "STUDENT_RUN_java"
            elif py_files and not java_files:
                src_type = "STUDENT_RUN_python"

            self.mdb.add_documents([{
                "text": run_text[:4000],
                "source_type": src_type,
                "file_path": "STUDENT_RUN",
                "section": "latest",
                "weight": 0.9 if "[RUN ERRORS]" in run_text else 0.7,
                "priority": "high",
                "tags": ["run","output","errors"]
            }])

    def _run_python(self, files: list[Path]):
        # pick a main file
        main = None
        for p in files:
            try:
                t = p.read_text(encoding="utf-8", errors="ignore")
                if "if __name__" in t:
                    main = p
                    break
            except Exception:
                pass
        if main is None:
            main = files[0]

        print(f"🐍 Running Python: {main.name}")
        try:
            proc = subprocess.run(
                [sys.executable, str(main)],
                capture_output=True,
                text=True,
                cwd=str(main.parent)
            )
            self.last_run_output = proc.stdout
            self.last_run_errors = proc.stderr
            print("---- STDOUT ----")
            print(proc.stdout if proc.stdout.strip() else "(no output)")
            print("---- STDERR ----")
            print(proc.stderr if proc.stderr.strip() else "(no errors)")
        except FileNotFoundError:
            print("❌ Python not found on PATH.")
        except Exception as e:
            print(f"❌ Error running Python: {e}")

    def _run_java(self, files: list[Path]):
        # Compile only the files specified
        folder = files[0].parent
        print(f"☕ Compiling Java in: {folder}")
        try:
            proc = subprocess.run(
                ["javac"] + [str(f.name) for f in files],
                capture_output=True,
                text=True,
                cwd=str(folder)
            )
        except FileNotFoundError:
            print("❌ 'javac' not found. Install JDK or add it to PATH to run Java.")
            return

        if proc.stderr.strip():
            self.last_run_errors = proc.stderr
            print("---- JAVAC ERRORS ----")
            print(proc.stderr)
            return
        else:
            print("✅ Compilation OK")

        # detect a main class among the provided files
        main_class = None
        for f in files:
            try:
                t = f.read_text(encoding="utf-8", errors="ignore")
                m = re.search(r"public\s+class\s+(\w+).*?static\s+void\s+main\s*\(", t, re.S)
                if m:
                    main_class = m.group(1)
                    break
            except Exception:
                pass

        if not main_class:
            print("⚠️ No 'public static void main' found. Skipping run.")
            return

        print(f"▶️ Running: java {main_class}")
        try:
            r = subprocess.run(
                ["java", main_class],
                capture_output=True,
                text=True,
                cwd=str(folder)
            )
            self.last_run_output = r.stdout
            self.last_run_errors = r.stderr
            print("---- STDOUT ----")
            print(r.stdout if r.stdout.strip() else "(no output)")
            print("---- STDERR ----")
            print(r.stderr if r.stderr.strip() else "(no errors)")
        except FileNotFoundError:
            print("❌ 'java' not found on PATH.")
        except Exception as e:
            print(f"❌ Error running Java: {e}")

    # ---------- ask with retrieval ----------
    def ask(self, question: str):
        """
        Retrieval-augmented Q&A:
        • Pulls top-k context from MemoryDB
        • Calls AIProvider.generate(system, user)
        • Filters prompt-echo/empty replies
        • Falls back to a concise heuristic answer if the model fails
        """
        import re
        if not question or not question.strip():
            print("⚠️ Provide a question after 'ask'.")
            return
        q = question.strip()

        # ---- 1) Retrieve small, high-signal context ----
        k = 6
        hits = self.mdb.search(q, k=k)
        # keep short slices so prompts stay small and robust
        ctx_chunks = []
        for i, h in enumerate(hits[:4], 1):
            t = h["text"].strip().replace("\r", " ")
            # keep ~500 chars per chunk
            ctx_chunks.append(f"[{i}] {t[:500]}")
        context = "\n\n".join(ctx_chunks) if ctx_chunks else "(no context found)"

        # ---- 2) Build prompt (concise, instruction-light) ----
        system = (
            "You are a concise, helpful tutor for a programming class. "
            "Answer the user's question using the provided context if it helps. "
            "Prefer instructor material and the student's recent run output or errors. "
            "Keep the answer short, specific, and actionable."
        )
        user = (
            f"Question: {q}\n\n"
            f"Context (may be partial):\n{context}\n\n"
            "Answer succinctly for a student. If the code has clear errors, point them out "
            "briefly and suggest the smallest possible fix."
        )

        # ---- 3) Call model ----
        try:
            ans = self.provider.generate(system, user, max_tokens=450).strip()
        except Exception:
            ans = ""

        # ---- 4) Detect prompt-echo / empty replies ----
        def _looks_like_prompt_echo(text: str) -> bool:
            if not text or len(text) < 5:
                return True
            low = text.lower()
            if "you are a helpful" in low or "return exactly:" in low or "summary:" == text[:8].lower():
                return True
            # if the answer repeats large portions of the prompt (context markers)
            if "[1]" in text and "Question:" in text and "Context" in text:
                return True
            return False

        if _looks_like_prompt_echo(ans):
            # ---- 5) Heuristic fallback (compact & useful) ----
            ans = self._fallback_qa(q, hits)

        # ---- 6) Print final, clean tutor answer ----
        print("\n🤖 Tutor:\n" + ans + "\n")

    def _fallback_qa(self, question: str, hits: list) -> str:
        """
        Compact, rule-based answer when the model fails.
        Uses question keywords and any run errors in MemoryDB.
        """
        import re

        q = question.lower().strip()

        # Pull any recent run diagnostics if present in top hits
        run_err = ""
        run_out = ""
        for h in hits:
            txt = (h.get("text") or "").strip()
            if "[RUN ERRORS]" in txt and not run_err:
                run_err = txt.split("[RUN ERRORS]", 1)[1].split("[RUN OUTPUT]")[0].strip()
            if "[RUN OUTPUT]" in txt and not run_out:
                run_out = txt.split("[RUN OUTPUT]", 1)[1].strip()
            if run_err and run_out:
                break

        # 1) Very common classroom Qs
        if "inheritance" in q and "java" in q:
            return (
                "Inheritance in Java lets a subclass reuse and extend a superclass. "
                "The subclass automatically gets the superclass’s fields and methods and "
                "can add new ones or override behavior. This supports the substitution principle: "
                "a subclass instance can be used wherever a superclass is expected."
            )

        if ("is my code correct" in q or "is my code right" in q) and (run_err or run_out):
            # Summarize first error line if available
            first_err_line = ""
            if run_err:
                first_err_line = "\n".join(run_err.splitlines()[:2]).strip()
            tip = (
                "It compiled and ran without errors." if not run_err else
                "Fix the first reported error, then re-run."
            )
            return (
                ("Your recent run shows errors:\n" + first_err_line + "\n\n" if run_err else "") +
                ("Recent output:\n" + "\n".join(run_out.splitlines()[:3]) + "\n\n" if run_out else "") +
                f"{tip} Keep changes minimal and test again."
            ).strip()

        # 2) Generic programming fallback using context snippets
        # Look for short definitional lines in context
        defs = []
        for h in hits[:3]:
            t = (h.get("text") or "")
            m = re.findall(r'([A-Z][A-Za-z ]{2,50}):\s*([^\n]{10,200})', t)
            defs.extend([f"- {k.strip()}: {v.strip()}" for k, v in m[:2]])
        if defs:
            return "Here's the concise answer based on the class materials:\n" + "\n".join(defs[:3])

        # 3) Absolute minimal fallback
        return "Here’s the short answer: focus on the key concept and apply it with a minimal example. If you share the exact code or error, I’ll pinpoint the fix."


    # ---------- TA-style explanation of the last run ----------
    def explain_last_run(self, verbose: bool = False):
        """
        Summarize the last compile/run in a friendly TA style (ChatGPT-like).
        Shows only a clean explanation by default.
        Use verbose=True to also print context/debug refs.
        """
        has_any_run = bool(self.last_run_output or self.last_run_errors)
        if not has_any_run:
            print("ℹ️ No recent run to explain. Run some code first (e.g., `run Hello.java`).")
            return

        # diagnostics bundle
        diag = ""
        if self.last_run_errors:
            diag += f"--- ERRORS ---\n{self.last_run_errors.strip()}\n"
        if self.last_run_output:
            if diag:
                diag += "\n"
            diag += f"--- OUTPUT ---\n{self.last_run_output.strip()}\n"

        # language hint
        lower_err = (self.last_run_errors or "").lower()
        lower_out = (self.last_run_output or "").lower()
        if "javac:" in lower_err or " error:" in lower_err or "java" in lower_err:
            lang_hint = "java"
        elif "traceback" in lower_err or ".py" in lower_err:
            lang_hint = "python"
        else:
            lang_hint = "java" if "class" in lower_err or "public static void main" in lower_err else "python"

        # a few short instructor snippets for grounding (if available)
        hits = self.mdb.search("grading focus rubric assignment requirements", k=3)
        inst_snips = []
        for i, h in enumerate(hits, 1):
            t = h["text"].strip().replace("\r", " ")
            inst_snips.append(f"[{i}] {t[:400]}")
        inst_ctx = "\n\n".join(inst_snips) if inst_snips else "(none)"

        system = (
            "You are a helpful, concise TA. Given the student's last compile/run diagnostics and any assignment notes, "
            "explain like ChatGPT in four parts. Keep it compact and actionable.\n\n"
            "Return exactly:\n"
            "1) What this error/output means (plain English)\n"
            "2) Likely root cause(s) (1–3 bullets)\n"
            "3) Minimal patch (code)\n"
            "4) ✅ Try again (one concrete next step)\n"
        )

        user = (
            f"Language hint: {lang_hint}\n\n"
            f"Diagnostics:\n{diag}\n"
            f"Assignment/context snippets:\n{inst_ctx}\n"
        )

        try:
            ans = self.provider.generate(system, user, max_tokens=450).strip()
        except Exception:
            ans = ""

        # 🔁 Fallback if model echoed prompt or returned nothing
        looks_like_prompt = (
            not ans
            or "Return exactly:" in ans
            or "You are a helpful" in ans
            or "explain like ChatGPT" in ans
        )
        if looks_like_prompt:
            ans = self._fallback_ta(diag, lang_hint)

        print("\n🧑‍🏫 TA\n" + "-"*60 + "\n" + (ans if ans else "(no answer)") + "\n")

        if verbose:
            print("\n[debug] prompt sent to model:\n" + "-"*60)
            print(system)
            print("\n[user]:\n" + user)

    def _fallback_ta(self, diag: str, lang_hint: str) -> str:
        """
        Rule-based, readable TA explanation when LLM answer is missing/echoed.
        Covers common Java/Python compile/runtime errors with minimal patches.
        """
        errors_section = ""
        outputs_section = ""
        if "--- ERRORS ---" in diag:
            errors_section = diag.split("--- ERRORS ---", 1)[1].split("--- OUTPUT ---")[0].strip()
        if "--- OUTPUT ---" in diag:
            outputs_section = diag.split("--- OUTPUT ---", 1)[1].strip()

        err = errors_section.lower()

        # --- Java common cases ---
        if lang_hint == "java":
            # Missing class wrapper / missing main
            if "class, interface, or enum expected" in err:
                return (
                    "1) What this means:\n"
                    "   Your Java code is not inside a class (and probably missing a main method). Java requires all code to be inside a class.\n\n"
                    "2) Likely causes:\n"
                    "   • You pasted `System.out.println(...)` at the top level\n"
                    "   • No `public static void main(String[] args)`\n"
                    "   • File/class name mismatch\n\n"
                    "3) Minimal patch:\n```java\n"
                    "public class Hello {\n"
                    "    public static void main(String[] args) {\n"
                    "        System.out.println(\"Hello Capstone\");\n"
                    "    }\n"
                    "}\n"
                    "```\n\n"
                    "4) ✅ Try again:\n"
                    "   Run: `code Hello.java` → paste the class → `run Hello.java`"
                )

            # public class name vs file name
            m = re.search(r"is public, should be declared in a file named (\w+\.java)", errors_section, re.I)
            if m:
                filename = m.group(1)
                return (
                    "1) What this means:\n"
                    "   The public class name must match the filename exactly.\n\n"
                    "2) Likely causes:\n"
                    "   • File named differently than the `public class` name.\n\n"
                    "3) Minimal patch:\n"
                    f"   Rename the file to `{filename}` or change the class name to match the filename.\n\n"
                    "4) ✅ Try again:\n"
                    f"   Save as `{filename}` and run again."
                )

            # cannot find symbol
            if "cannot find symbol" in err:
                return (
                    "1) What this means:\n"
                    "   You referenced a class/method/variable that the compiler can't find.\n\n"
                    "2) Likely causes:\n"
                    "   • Missing class files (e.g., `Manager`, `parttimeWorker`) in the same folder\n"
                    "   • Typos or wrong capitalization in class names\n\n"
                    "3) Minimal patch:\n"
                    "   Ensure each class is defined in its own `.java` file, with matching case. Example:\n"
                    "```java\n"
                    "public class Manager extends Employee {\n"
                    "    private double bonus;\n"
                    "    public Manager(double bonus) { super(\"\", 0.0); this.bonus = bonus; }\n"
                    "    @Override public double getSalary() { return super.getSalary() + bonus; }\n"
                    "}\n"
                    "```\n\n"
                    "4) ✅ Try again:\n"
                    "   Add missing class files via `code Manager.java` etc., then `run testExtends.java`."
                )

            # no main method
            if "no 'public static void main'" in err or "main method not found" in err:
                return (
                    "1) What this means:\n"
                    "   Your code compiled, but there is no entry point to run.\n\n"
                    "2) Likely causes:\n"
                    "   • No `public static void main(String[] args)` in any class you tried to run\n\n"
                    "3) Minimal patch:\n```java\n"
                    "public class Test {\n"
                    "    public static void main(String[] args) {\n"
                    "        // call your logic here\n"
                    "    }\n"
                    "}\n"
                    "```\n\n"
                    "4) ✅ Try again:\n"
                    "   Add a main method and `run Test.java`."
                )

        # --- Python common cases ---
        if lang_hint == "python":
            if "syntaxerror" in err and "never closed" in err:
                return (
                    "1) What this means:\n"
                    "   A parenthesis or quote was opened but never closed.\n\n"
                    "2) Likely causes:\n"
                    "   • Missing `)` after `print(`, or unmatched quotes\n\n"
                    "3) Minimal patch:\n```python\n"
                    "print(\"Missing bracket\")\n"
                    "```\n\n"
                    "4) ✅ Try again:\n"
                    "   Fix the line and run again."
                )
            if "indentationerror" in err:
                return (
                    "1) What this means:\n"
                    "   Unexpected or inconsistent indentation.\n\n"
                    "2) Likely causes:\n"
                    "   • Extra spaces/tabs before a line that shouldn't be indented\n\n"
                    "3) Minimal patch:\n"
                    "   Remove extra indentation or align blocks under `if/for/def` consistently.\n\n"
                    "4) ✅ Try again:\n"
                    "   Fix indentation and rerun."
                )

        # Success path: Only output
        if outputs_section.strip() and not errors_section.strip():
            return (
                "1) What this means:\n"
                "   Your program ran successfully and produced output.\n\n"
                "2) Likely root cause(s):\n"
                "   • None — looks good.\n\n"
                "3) Minimal patch (if output not as expected):\n"
                "   Adjust your print logic/inputs.\n\n"
                "4) ✅ Try again:\n"
                "   Modify code and rerun."
            )

        # Generic fallback
        head = "\n".join((errors_section or outputs_section).splitlines()[:4])
        return (
            "1) What this means:\n"
            "   The compiler/runtime reported an issue.\n\n"
            "2) Likely root cause(s):\n"
            "   • Syntax error or missing symbol\n"
            "   • File/class name mismatch (Java) or missing imports\n\n"
            "3) Minimal patch:\n"
            "   Fix the reported line/symbol and ensure filenames match classes.\n\n"
            f"   First lines:\n```\n{head}\n```\n\n"
            "4) ✅ Try again:\n"
            "   Apply the fix and rerun the same file."
        )

    def status(self):
        print(f"📦 Code files uploaded: {len(self.student_code_files)}")
        for p in self.student_code_files:
            in_sbx = (p.parent == self.sandbox_dir)
            mark = " (sandbox)" if in_sbx else ""
            print(f"   • {p.name}{mark} — {p}")
        print("ℹ️  You can ingest instructions/slides/notes, paste or upload code, run, then ask.\n")


def main():
    print_banner()
    app = StudentApp()

    while True:
        try:
            raw = input("👤 You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n🤖 Tutor: Bye! 👋")
            break

        if not raw:
            continue

        cmd = raw.split()[0].lower()

        if cmd in {"quit", "exit", "bye"}:
            print("🤖 Tutor: Bye! 👋")
            break
        elif cmd == "help":
            print_banner()
        elif cmd == "status":
            app.status()
        elif cmd == "list":
            app.list_sandbox()
        elif cmd == "open":
            rest = raw[len("open"):].strip()
            name = rest.strip().strip('"')
            if not name:
                print('Usage: open "filename.ext"')
            else:
                app.open_sandbox(name)
        elif cmd == "paste":
            rest = raw[len("paste"):].strip()
            name = rest.strip().strip('"')
            if not name:
                print('Usage: paste "filename.ext"')
            else:
                app.paste_code(name)
        elif cmd.startswith("code"):
            args = cmd.split(maxsplit=1)
            arg = args[1] if len(args) > 1 else None
            app.handle_code_command(arg)
        elif cmd == "ingest":
            try:
                # ingest "C:/path/file.ext" slides
                rest = raw[len("ingest"):].strip()
                if rest.startswith('"'):
                    path, rest2 = rest[1:].split('"', 1)
                    source_type = rest2.strip()
                else:
                    path, source_type = rest.split(" ", 1)
                source_type = source_type.strip().lower()
                if source_type not in {"instructions", "slides", "notes", "working_solution"}:
                    print("Usage: ingest \"full\\path.ext\" <instructions|slides|notes|working_solution>")
                    continue
                app.ingest_reference(path, source_type)
            except Exception:
                print("Usage: ingest \"full\\path.ext\" <instructions|slides|notes|working_solution>")
        elif cmd == "upload":
            try:
                rest = raw[len("upload"):].strip()
                path = rest.strip().strip('"')
                app.upload_code(path)
            except Exception:
                print("Usage: upload \"full\\path\\to\\file.py|.java\"")
        elif cmd == "run":
            target = raw[len("run"):].strip().strip('"')
            target = target if target else None
            app.run_code(target)
        elif cmd == "why":
            app.explain_last_run(verbose=False)
        elif cmd == "ask":
            question = raw[len("ask"):].strip()
            app.ask(question)
        else:
            print("I didn't recognize that. Type 'help' to see commands.")


if __name__ == "__main__":
    main()
