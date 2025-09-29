# CapstoneImportSample.py
from __future__ import annotations
from pathlib import Path
import re
import sys

# Minimal multi-language comment parsing:
# - Python: # line comments, triple-quoted docstrings treated as comments
# - JS/Java/C/C++: // line, /* ... */ block
# - HTML: <!-- ... -->
COMMENT_PATTERNS = {
    ".py": {
        "line": r"#[^\n]*",
        "block": r'("""|\'\'\')[\s\S]*?\1',
    },
    ".js": {
        "line": r"//[^\n]*",
        "block": r"/\*[\s\S]*?\*/",
    },
    ".java": {
        "line": r"//[^\n]*",
        "block": r"/\*[\s\S]*?\*/",
    },
    ".c": {
        "line": r"//[^\n]*",
        "block": r"/\*[\s\S]*?\*/",
    },
    ".cpp": {
        "line": r"//[^\n]*",
        "block": r"/\*[\s\S]*?\*/",
    },
    ".h": {
        "line": r"//[^\n]*",
        "block": r"/\*[\s\S]*?\*/",
    },
    ".hpp": {
        "line": r"//[^\n]*",
        "block": r"/\*[\s\S]*?\*/",
    },
    ".html": {
        "line": None,
        "block": r"<!--[\s\S]*?-->",
    },
}

LANG_BY_EXT = {
    ".py": "python",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".h": "c",
    ".js": "javascript",
    ".html": "html",
    ".ts": "typescript",
    ".tsx": "typescript",
}

class ImportSample:
    """
    Analyzes a sample solution (source file) and extracts:
      - comments_only (why, rationale)
      - code_no_comments (bare code)
      - learning_explanations (weighted)
      - essential_libraries (imports/uses)
      - key_learning_outcomes (functions/classes)
      - mapping_summary (artifacts_found etc.)
    Compatible with CapstoneIntegration. 
    """

    def __init__(self, assignment_goals: dict | None = None):
        self.assignment_goals = assignment_goals or {}
        self.detected = {
            "language": None,
            "comments_only": "",
            "code_no_comments": "",
            "file_path": "",
        }
        self.learning_explanations = []
        self.key_learning_outcomes = []
        self.essential_libraries = []
        self.mapping_summary = {
            "artifacts_found": [],
            "line_counts": {"total": 0, "comments": 0, "code": 0},
        }

    # ---------- main API ----------
    def upload_and_analyze(self, file_path: str):
        p = Path(file_path)
        if not p.exists() or not p.is_file():
            return {"error": "Sample solution file not found"}

        self.detected["file_path"] = str(p)
        ext = p.suffix.lower()
        language = LANG_BY_EXT.get(ext, "text")
        self.detected["language"] = language

        text = p.read_text(encoding="utf-8", errors="ignore")
        comments_only, code_no_comments = self._split_code_and_comments(text, ext)
        self.detected["comments_only"] = comments_only
        self.detected["code_no_comments"] = code_no_comments

        self.mapping_summary["line_counts"]["total"] = len(text.splitlines())
        self.mapping_summary["line_counts"]["comments"] = len(comments_only.splitlines())
        self.mapping_summary["line_counts"]["code"] = len(code_no_comments.splitlines())

        # mark basic artifact
        if code_no_comments.strip():
            self.mapping_summary["artifacts_found"].append("code_implementation")

        # analyze content
        self.learning_explanations = self._extract_learning_explanations(comments_only)
        self.key_learning_outcomes = self._extract_key_learning_outcomes(code_no_comments, ext)
        self.essential_libraries = self._detect_libraries(code_no_comments, ext)

        # index to MemoryDB
        try:
            from memory_db import MemoryDB
            mdb = MemoryDB()
            chunks = []
            if comments_only.strip():
                chunks.append({
                    "text": comments_only[:6000],
                    "source_type": "working_solution",
                    "file_path": str(p),
                    "section": "comments",
                    "weight": 0.95,
                    "priority": "high",
                    "tags": ["working_solution", "comments", "benchmark"],
                    "language": language,
                })
            if code_no_comments.strip():
                chunks.append({
                    "text": code_no_comments[:6000],
                    "source_type": "working_solution",
                    "file_path": str(p),
                    "section": "code_no_comments",
                    "weight": 0.65,
                    "priority": "medium",
                    "tags": ["working_solution", "code"],
                    "language": language,
                })
            if chunks:
                mdb.add_documents(chunks)
                print(f"✅ Indexed {len(chunks)} sample chunk(s) into MemoryDB")
        except Exception as e:
            print(f"[MemoryDB] Skipped indexing sample: {e}")

        return {
            "status": "ok",
            "language": language,
            "artifacts_found": self.mapping_summary["artifacts_found"],
        }

    def print_results(self):
        print("=" * 60)
        print("SAMPLE SOLUTION ANALYSIS")
        print("=" * 60)
        print(f"Language: {self.detected['language']}")
        print(f"File: {self.detected['file_path']}")
        lc = self.mapping_summary["line_counts"]
        print(f"Lines - total: {lc['total']} | comments: {lc['comments']} | code: {lc['code']}\n")

        print("📘 Learning Explanations (from comments, weighted):")
        for i, ex in enumerate(self.learning_explanations[:8], 1):
            print(f"  {i}. (w={ex['weight']:.1f}) {ex['text'][:100]}{'...' if len(ex['text'])>100 else ''}")
        if not self.learning_explanations:
            print("  (none found)")
        print()

        print("🎯 Key Learning Outcomes (functions/classes):")
        for out in self.key_learning_outcomes[:10]:
            print(f"  • {out}")
        if not self.key_learning_outcomes:
            print("  (none found)")
        print()

        print("🧰 Essential Libraries:")
        for lib in self.essential_libraries:
            print(f"  • {lib['name']} (w={lib.get('weight',0.7)})")
        if not self.essential_libraries:
            print("  (none found)")
        print()

        print("🗂️  Mapping Summary:")
        print(f"  Artifacts found: {', '.join(self.mapping_summary['artifacts_found']) or '(none)'}")

    def get_learning_focused_content_for_response(self):
        return {
            "learning_explanations": self.learning_explanations,   # list of {text, weight, scope?}
            "key_learning_outcomes": [{"text": k, "weight": 0.75} for k in self.key_learning_outcomes],
            "essential_libraries": [{"name": l["name"], "weight": l.get("weight", 0.7)} for l in self.essential_libraries],
            "artifacts_found": self.mapping_summary["artifacts_found"],
        }

    # ---------- splitting & detectors ----------
    def _split_code_and_comments(self, text: str, ext: str):
        """
        Returns (comments_only, code_no_comments) for a given file extension.
        If extension unknown, treat lines starting with # or // as comments.
        """
        patterns = COMMENT_PATTERNS.get(ext, None)
        comments = []

        code_only = text
        if patterns:
            # block comments
            block_pat = patterns.get("block")
            if block_pat:
                for m in re.finditer(block_pat, text, flags=re.MULTILINE):
                    comments.append(m.group())
            # line comments
            line_pat = patterns.get("line")
            if line_pat:
                for m in re.finditer(line_pat, text, flags=re.MULTILINE):
                    comments.append(m.group())

            # remove both from code
            if block_pat:
                code_only = re.sub(block_pat, "", code_only, flags=re.MULTILINE)
            if line_pat:
                code_only = re.sub(line_pat, "", code_only, flags=re.MULTILINE)
        else:
            # generic fallback
            line_comments = []
            for ln in text.splitlines():
                if ln.strip().startswith("#") or ln.strip().startswith("//"):
                    line_comments.append(ln)
            comments.extend(line_comments)
            # strip generic
            code_only = "\n".join(
                ln for ln in text.splitlines()
                if not (ln.strip().startswith("#") or ln.strip().startswith("//"))
            )

        comments_text = "\n".join(comments).strip()
        code_text = code_only.strip()
        return comments_text, code_text

    def _extract_learning_explanations(self, comments_only: str):
        """
        Heuristics: treat sentences in comments that contain explanations
        (e.g., 'because', 'so that', 'in order to', 'why') as higher-weight.
        """
        if not comments_only:
            return []

        # Split into sentences crudely
        sents = re.split(r"(?<=[.!?])\s+", comments_only)
        outs = []
        for s in sents:
            s_clean = s.strip(" #/*\t-")
            if not s_clean or len(s_clean) < 12:
                continue
            lw = 0.75
            lower = s_clean.lower()
            if any(k in lower for k in ["because", "so that", "in order to", "why", "therefore"]):
                lw = 0.95
            elif any(k in lower for k in ["note:", "hint:", "tip:"]):
                lw = 0.85
            outs.append({"text": s_clean, "weight": lw, "scope": "comment"})
        # keep top reasonable amount
        outs = sorted(outs, key=lambda x: x["weight"], reverse=True)[:40]
        return outs

    def _extract_key_learning_outcomes(self, code_no_comments: str, ext: str):
        """
        Simple signal: function and class names, plus main entry points.
        """
        outcomes = set()
        tl = code_no_comments

        if ext == ".py":
            outcomes.update(re.findall(r"^\s*def\s+([A-Za-z_]\w*)\s*\(", tl, flags=re.MULTILINE))
            outcomes.update(re.findall(r"^\s*class\s+([A-Za-z_]\w*)\s*[:\(]", tl, flags=re.MULTILINE))
            if re.search(r"if\s+__name__\s*==\s*['\"]__main__['\"]", tl):
                outcomes.add("python_entrypoint_main")
        elif ext in (".js", ".ts"):
            outcomes.update(re.findall(r"function\s+([A-Za-z_]\w*)\s*\(", tl))
            outcomes.update(re.findall(r"class\s+([A-Za-z_]\w*)\s*\{", tl))
        elif ext in (".java",):
            outcomes.update(re.findall(r"class\s+([A-Za-z_]\w*)\s*\{", tl))
            if "static void main" in tl:
                outcomes.add("java_main")
        elif ext in (".c", ".cpp", ".h", ".hpp"):
            outcomes.update(re.findall(r"\b([A-Za-z_]\w*)\s*\(", tl))  # rough
            if re.search(r"\bint\s+main\s*\(", tl):
                outcomes.add("c_cpp_main")
        elif ext == ".html":
            # key sections
            if "<script" in tl:
                outcomes.add("html_script_logic")
            if "<form" in tl:
                outcomes.add("html_form_handling")

        # map to human-ish phrases
        return [f"Defines: {name}" for name in sorted(outcomes)]

    def _detect_libraries(self, code_no_comments: str, ext: str):
        libs = []
        if ext == ".py":
            for m in re.finditer(r"^\s*(?:import|from)\s+([A-Za-z_][A-Za-z0-9_\.]*)", code_no_comments, flags=re.MULTILINE):
                libs.append({"name": m.group(1).split(".")[0], "weight": 0.7})
        elif ext in (".js", ".ts"):
            for m in re.finditer(r"(?:import\s+.*?\s+from\s+['\"]([^'\"]+)['\"])|(?:require\(['\"]([^'\"]+)['\"]\))", code_no_comments):
                name = m.group(1) or m.group(2)
                if name:
                    libs.append({"name": name.split("/")[0], "weight": 0.7})
        elif ext == ".java":
            for m in re.finditer(r"^\s*import\s+([A-Za-z0-9_\.]+)\s*;", code_no_comments, flags=re.MULTILINE):
                libs.append({"name": m.group(1).split(".")[0], "weight": 0.7})
        elif ext in (".c", ".cpp", ".h", ".hpp"):
            for m in re.finditer(r"#\s*include\s*[<\"]([^>\"]+)[>\"]", code_no_comments):
                libs.append({"name": m.group(1).split("/")[0], "weight": 0.7})
        # dedupe
        seen = set()
        uniq = []
        for l in libs:
            if l["name"] not in seen:
                seen.add(l["name"])
                uniq.append(l)
        return uniq

# ---------- hybrid CLI (args first, else prompt) ----------
if __name__ == "__main__":
    if len(sys.argv) >= 2:
        sample_path = sys.argv[1]
    else:
        sample_path = input("Enter path to sample solution file (e.g., .py, .java, .cpp, .js, .html): ").strip()

    analyzer = ImportSample({})
    res = analyzer.upload_and_analyze(sample_path)
    if isinstance(res, dict) and "error" in res:
        print(f"Error: {res['error']}")
        sys.exit(1)
    analyzer.print_results()
