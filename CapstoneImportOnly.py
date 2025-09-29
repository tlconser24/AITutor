# CapstoneImportOnly.py
# -------------------------------------------------------------------
# Reads text from PDF/DOCX/TXT/MD + extracts embedded IMAGES.
# - For PDFs: uses PyMuPDF (fitz) to extract both text and images.
# - For DOCX: uses python-docx to extract both text and images.
# - Adds [IMAGE EXTRACTED: ...] placeholders into the text stream.
# - (Optional) OCR any extracted images if pytesseract+PIL are installed.
#
# After extraction, your existing analysis/weighting/MemoryDB indexing runs
# unchanged — now with image placeholders (and OCR text if enabled).
#
# Dependencies (install in your venv):
#   pip install python-docx PyMuPDF pillow pytesseract
# For OCR (optional): install Tesseract binary (macOS via brew: `brew install tesseract`)
# -------------------------------------------------------------------

import os
import re
from pathlib import Path

import docx          # python-docx
import fitz          # PyMuPDF
# PyPDF2 no longer needed for PDFs because we use fitz for better fidelity

# Optional OCR
try:
    from PIL import Image
    import pytesseract
    _HAS_TESSERACT = True
except Exception:
    _HAS_TESSERACT = False

# ------------------- CONFIG -------------------

ALLOWED_FILE_TYPES = {
    "instructions": {"pdf", "docx", "txt", "md"}
}

MAX_FILE_MB = 50  # PDFs with images can be bigger; adjust as you like
PYTHON_VERSION_MIN = "3.6"

# Where to save extracted images
IMAGE_DIR = Path("extracted_images")
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

# Weight configuration for content prioritization
CONTENT_WEIGHTS = {
    "learning_objectives": 1.0,    # What students must learn/do
    "grading_criteria": 1.0,       # How they'll be evaluated
    "deliverables": 1.0,           # What they must submit
    "task_descriptions": 0.8,      # Problem setup
    "requirements": 0.8,           # Constraints and specs
    "examples": 0.6,               # Supporting information
    "context": 0.4                 # Background info
}


# ------------------- UTILITIES -------------------

def _ocr_image(image_path: Path) -> str:
    """Run OCR on an image if pytesseract is available; else empty string."""
    if not _HAS_TESSERACT:
        return ""
    try:
        with Image.open(image_path) as im:
            text = pytesseract.image_to_string(im)
        # Basic cleanup
        text = re.sub(r"\s+\n", "\n", text).strip()
        return text
    except Exception:
        return ""


def _extract_docx_text_and_images(filepath: str, do_ocr: bool = False) -> str:
    """
    Extracts text and images from a DOCX file.
    - Text: concatenates paragraphs.
    - Images: dumps all embedded images to IMAGE_DIR, adds placeholders to text.
      (Note: DOCX is not a page-based format, so we append images after text with labels.)
    - Optional OCR text appended after each image placeholder.
    """
    fp = Path(filepath)
    try:
        d = docx.Document(str(fp))
    except Exception:
        return ""

    # 1) Text
    paragraphs = [p.text for p in d.paragraphs if p.text]
    text_block = "\n".join(paragraphs)

    # 2) Images
    #   Traverse relationships and extract image parts
    #   This approach gets all images even if not in inline_shapes.
    image_notes = []
    rels = d.part.rels
    img_idx = 0
    for rel in rels.values():
        try:
            if "image" in rel.target_ref:
                img_idx += 1
                image_part = rel.target_part
                img_bytes = image_part.blob
                # Try to guess extension; fallback to png
                ext = Path(rel.target_ref).suffix or ".png"
                out_path = IMAGE_DIR / f"{fp.stem}_img{img_idx}{ext}"
                with open(out_path, "wb") as f:
                    f.write(img_bytes)

                note = f"[IMAGE EXTRACTED: {out_path}]"
                if do_ocr:
                    ocr_text = _ocr_image(out_path)
                    if ocr_text:
                        note += f"\n[OCR TEXT] {ocr_text}"
                image_notes.append(note)
        except Exception:
            # Skip broken rels gracefully
            continue

    if image_notes:
        text_block += "\n\n" + "\n".join(image_notes)

    return text_block


def _extract_pdf_text_and_images(filepath: str, do_ocr: bool = False) -> str:
    """
    Extracts text and images from a PDF using PyMuPDF.
    - Page by page: append text, then for each image on the page:
      save image and insert a placeholder + optional OCR text.
    """
    fp = Path(filepath)
    if not fp.exists():
        return ""

    out_parts = []
    try:
        doc = fitz.open(str(fp))
    except Exception:
        return ""

    for page_num, page in enumerate(doc, start=1):
        try:
            # Text extraction
            txt = page.get_text() or ""
            if txt.strip():
                out_parts.append(f"[PAGE {page_num} TEXT]\n{txt}")

            # Images
            images = page.get_images(full=True)
            for img_i, img in enumerate(images, start=1):
                xref = img[0]
                base = doc.extract_image(xref)
                img_bytes = base.get("image", b"")
                ext = "." + (base.get("ext") or "png")
                out_path = IMAGE_DIR / f"{fp.stem}_p{page_num}_img{img_i}{ext}"
                try:
                    with open(out_path, "wb") as f:
                        f.write(img_bytes)
                    note = f"[IMAGE EXTRACTED: {out_path}]"
                    if do_ocr:
                        ocr_text = _ocr_image(out_path)
                        if ocr_text:
                            note += f"\n[OCR TEXT] {ocr_text}"
                    out_parts.append(note)
                except Exception:
                    # Skip if we can't write file
                    continue
        except Exception:
            # Skip problematic pages gracefully
            continue

    doc.close()
    return "\n\n".join(out_parts).strip()


def _extract_txt_or_md(filepath: str) -> str:
    try:
        return Path(filepath).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


# ------------------- MAIN CLASS -------------------

class ImportInstructions:
    def __init__(self, enable_ocr: bool = False):
        self.state = "Draft"
        self.highlights = {}
        self.extracted_text = ""
        self.enable_ocr = enable_ocr  # NEW: toggle OCR on/off

        self.assignment_goals = {
            "artifact_types": [],
            "inputs": [],
            "expected_outputs": [],
            "constraints": [f"Language: Python", f"Python >= {PYTHON_VERSION_MIN}"],
            "grading_focus": [],
            "open_questions": [],
            "source_citations": [],
            "confidence": 0.0
        }

    # ---------- main API ----------
    def upload_and_parse(self, file_path: str):
        # 1) basic checks
        if self.is_google_doc_link(file_path):
            return {"error": "Download as .docx and upload (no direct fetch in v1)"}

        if self.size_mb(file_path) > MAX_FILE_MB:
            return {"error": f"File exceeds {MAX_FILE_MB} MB"}

        if self.get_ext(file_path) not in ALLOWED_FILE_TYPES["instructions"]:
            return {"error": "Unsupported instructions format"}

        # 2) extract (NOW WITH IMAGES + optional OCR)
        text = self.extract_text_with_images(file_path, self.enable_ocr)
        if not text:
            return {"error": "Scanned/image-only document and OCR disabled or failed. Try enable_ocr=True."}

        # 3) analyze
        self.extracted_text = text
        self.analyze_text_content(text)

        self.highlights = self.extract_highlights(text)
        inferred = self.infer_goals_from(self.highlights, text)
        self.assignment_goals = self.merge_defaults(
            inferred,
            constraints_defaults=[f"Language: Python", f"Python >= {PYTHON_VERSION_MIN}"]
        )
        self.state = "Draft"

        # 4) add weights
        self.assign_content_weights()

        # 5) index into MemoryDB so it’s searchable by the tutor
        try:
            from memory_db import MemoryDB
            mdb = MemoryDB()
            chunks = []

            # a) full text (low priority, but searchable)
            if self.extracted_text:
                chunks.append({
                    "text": self.extracted_text[:8000],  # give more room now that images add lines
                    "source_type": "instructions",
                    "file_path": str(file_path),
                    "section": "full_text_with_images",
                    "weight": 0.5,
                    "priority": "low",
                    "tags": ["instructions"]
                })

            # b) weighted, important excerpts (high priority)
            for cit in self.assignment_goals.get("source_citations", []):
                excerpt = cit.get("excerpt", "")
                if not excerpt:
                    continue
                chunks.append({
                    "text": excerpt,
                    "source_type": "instructions",
                    "file_path": str(file_path),
                    "section": cit.get("location", "excerpt"),
                    "weight": float(cit.get("weight", 0.7)),
                    "priority": "high",
                    "tags": ["instructions", "key_requirement"]
                })

            if chunks:
                mdb.add_documents(chunks)
                print(f"✅ Indexed {len(chunks)} instruction chunk(s) into MemoryDB")
        except Exception as e:
            print(f"[MemoryDB] Skipped indexing instructions: {e}")

        return {"highlights": self.highlights, "assignment_goals": self.assignment_goals}

    def extract_text_with_images(self, filepath: str, do_ocr: bool = False) -> str:
        """Dispatch by extension, performing text + image extraction (and OCR if enabled)."""
        ext = self.get_ext(filepath)
        if ext in {"txt", "md"}:
            return _extract_txt_or_md(filepath)
        if ext == "docx":
            return _extract_docx_text_and_images(filepath, do_ocr)
        if ext == "pdf":
            return _extract_pdf_text_and_images(filepath, do_ocr)
        return ""

    def merge_defaults(self, inferred: dict, constraints_defaults: list[str]):
        """
        Merge default constraints with the inferred goals dict.
        Safe if inferred is None or missing keys.
        """
        inferred = dict(inferred or {})
        existing = inferred.get("constraints", []) or []
        inferred["constraints"] = [*constraints_defaults, *existing]
        return inferred

    # ---------- weighting ----------
    def assign_content_weights(self):
        # Weight the source citations you already create
        for citation in self.assignment_goals["source_citations"]:
            citation["weight"] = self.classify_content_weight(citation.get("excerpt", ""))

        # Weight the action verbs by importance
        weighted_verbs = []
        for verb in self.highlights.get("action_verbs", []):
            if verb in ["calculate", "compute", "solve", "derive", "implement"]:
                weighted_verbs.append({"verb": verb, "weight": 1.0})
            elif verb in ["analyze", "evaluate", "compare"]:
                weighted_verbs.append({"verb": verb, "weight": 0.8})
            else:
                weighted_verbs.append({"verb": verb, "weight": 0.6})
        self.highlights["weighted_verbs"] = weighted_verbs

        # Weight technical concepts by relevance
        weighted_concepts = []
        for concept in self.highlights.get("technical_concepts", []):
            if concept in ["hash", "probability", "algorithm"]:
                weighted_concepts.append({"concept": concept, "weight": 1.0})
            else:
                weighted_concepts.append({"concept": concept, "weight": 0.7})
        self.highlights["weighted_concepts"] = weighted_concepts

    def classify_content_weight(self, content: str) -> float:
        content_lower = (content or "").lower()

        # CRITICAL (1.0)
        math_patterns = [
            r"\([^)]*\)\s*\^\s*[^)]*",   # exponents
            r"expected\s+fraction",
            r"probability",
            r"formula",
            r"calculate|compute",
            r"bit\s+array",
            r"hash\s+function",
            r"bloom\s+filter",
            r"false\s+positive",
        ]
        if any(re.search(p, content_lower) for p in math_patterns):
            return 1.0

        if any(k in content_lower for k in ["learning objective", "deliverable", "must demonstrate", "grading criteria"]):
            return CONTENT_WEIGHTS["learning_objectives"]

        # HIGH (0.9)
        task_patterns = [r"task\s+\d+", r"suppose\s+we", r"what\s+is\s+the", r"detail\s+how\s+you"]
        if any(re.search(p, content_lower) for p in task_patterns):
            return 0.9

        # MEDIUM (0.8)
        if any(k in content_lower for k in ["requirement", "constraint", "specification", "parameter"]):
            return CONTENT_WEIGHTS["requirements"]

        # LOW (0.3)
        admin_patterns = [r"submit.*via\s+canvas", r"due\s+date", r"upload"]
        if any(re.search(p, content_lower) for p in admin_patterns):
            return 0.3

        # DEFAULT (0.5)
        return CONTENT_WEIGHTS["context"]

    def get_priority_content_for_response(self, question_type: str = "general"):
        weighted_citations = sorted(
            self.assignment_goals["source_citations"],
            key=lambda x: x.get("weight", 0.4),
            reverse=True
        )
        priority_verbs = [i["verb"] for i in self.highlights.get("weighted_verbs", []) if i["weight"] >= 0.8]
        priority_concepts = [i["concept"] for i in self.highlights.get("weighted_concepts", []) if i["weight"] >= 0.8]
        return {
            "priority_citations": weighted_citations[:3],
            "priority_verbs": priority_verbs,
            "priority_concepts": priority_concepts,
            "grading_focus": self.assignment_goals["grading_focus"],
            "expected_outputs": self.assignment_goals["expected_outputs"],
        }

    # ---------- analysis helpers / extraction ----------
    def analyze_text_content(self, text: str):
        print("\nDETAILED TEXT ANALYSIS:")
        print(f"Total text length: {len(text)} characters")
        print(f"Number of lines: {len(text.splitlines())}")

        assignment_keywords = {
            "action_verbs": ["implement", "create", "develop", "analyze", "evaluate", "compare",
                             "visualize", "calculate", "compute", "solve", "derive", "prove", "show"],
            "deliverables": ["submit", "deliverable", "report", "code", "plot", "analysis"],
            "requirements": ["due", "grade", "rubric", "constraint", "requirement"],
            "technical_terms": ["python", "data", "hash", "probability", "algorithm", "function"]
        }

        found_by_category = {}
        tl = text.lower()
        for category, keywords in assignment_keywords.items():
            found = []
            for keyword in keywords:
                count = tl.count(keyword)
                if count > 0:
                    found.append(f"{keyword}({count}x)")
            if found:
                found_by_category[category] = found

        print("Keywords found by category:")
        for category, keywords in found_by_category.items():
            print(f"  {category}: {', '.join(keywords)}")

        preview = text[:500]
        print("\nFirst 500 characters:")
        print("'" + (preview + "..." if len(text) > 500 else preview) + "'\n")

    def extract_highlights(self, text: str):
        sections = self.detect_sections(text, ["Objectives", "Deliverables", "Grading", "Submission", "Instructions", "Task"])
        action_verbs = self.find_action_verbs(text)
        requirements = self.find_requirements(text)
        concepts = self.find_technical_concepts(text)
        deliverables = self.find_deliverables(text)
        return {
            "sections": sections,
            "action_verbs": action_verbs,
            "requirements": requirements,
            "technical_concepts": concepts,
            "deliverables": deliverables
        }

    def find_action_verbs(self, text: str):
        verbs = [
            "implement", "create", "build", "develop", "write", "code", "program",
            "analyze", "evaluate", "compare", "assess", "examine", "study",
            "calculate", "compute", "solve", "derive", "prove", "show", "find", "determine",
            "visualize", "plot", "graph", "chart", "display",
            "explain", "describe", "discuss", "report", "document"
        ]
        tl = text.lower()
        return [v for v in verbs if v in tl]

    def find_requirements(self, text: str):
        out = []
        for line in text.splitlines():
            s = line.strip()
            if any(st in s.lower() for st in ["submit:", "use:", "constraint:", "requirement:", "must:", "should:"]):
                out.append(s)
            elif "due" in s.lower() and any(w in s.lower() for w in ["date", "by", "before"]):
                out.append(s)
        return out

    def find_technical_concepts(self, text: str):
        concepts, tl = [], text.lower()
        tech_patterns = [
            "hash", "probability", "algorithm", "function", "array", "data structure",
            "machine learning", "statistics", "python", "pandas", "numpy", "matplotlib",
            "database", "sql", "api", "json", "csv", "regression", "classification"
        ]
        for p in tech_patterns:
            if p in tl:
                concepts.append(p)
        return concepts

    def find_deliverables(self, text: str):
        dl, tl = [], text.lower()
        patterns = ["submit", "deliver", "provide", "create", "generate", "produce",
                    "report", "analysis", "code", "script", "plot", "graph", "chart"]
        for p in patterns:
            if p in tl:
                dl.append(p)
        return dl

    def infer_goals_from(self, highlights: dict, text: str):
        artifact_types, verbs = [], highlights.get("action_verbs", [])

        if any(v in verbs for v in ["implement", "code", "program", "write"]):
            artifact_types.append("code_implementation")
        if any(v in verbs for v in ["calculate", "compute", "solve", "derive", "prove"]):
            artifact_types.append("mathematical_analysis")
        if any(v in verbs for v in ["analyze", "evaluate", "compare", "examine"]):
            artifact_types.append("data_analysis")
        if any(v in verbs for v in ["visualize", "plot", "graph", "chart"]):
            artifact_types.append("data_visualization")
        if any(v in verbs for v in ["explain", "describe", "discuss", "report"]):
            artifact_types.append("written_report")

        inputs = self.extract_specific_inputs(text, highlights)
        outputs = self.extract_specific_outputs(text, highlights)
        grading_focus = self.identify_grading_focus(text, verbs)
        open_questions = self.generate_open_questions(text, highlights)
        citations = self.create_source_citations(text)

        return {
            "artifact_types": artifact_types,
            "inputs": inputs,
            "expected_outputs": outputs,
            "constraints": self.extract_constraints(text),
            "grading_focus": grading_focus,
            "open_questions": open_questions,
            "source_citations": citations,
            "confidence": self.calculate_confidence(highlights)
        }

    def extract_specific_inputs(self, text: str, highlights: dict):
        inputs, tl = [], text.lower()
        if "set s" in tl and "members" in tl:
            inputs.append("Set S with specified number of members")
        if "bit array" in tl:
            inputs.append("Bit array data structure")
        if "hash function" in tl:
            inputs.append("Hash function parameters")
        if "dataset" in tl or "data file" in tl:
            inputs.append("Dataset files")
        if "csv" in tl:
            inputs.append("CSV data files")
        if not inputs:
            inputs.append("Assignment parameters" if "data" not in tl else "Data inputs")
        return inputs

    def extract_specific_outputs(self, text: str, highlights: dict):
        outputs, verbs, tl = [], highlights.get("action_verbs", []), text.lower()
        if "expected fraction" in tl:
            outputs.append("Expected fraction calculations")
        if any(v in verbs for v in ["calculate", "compute"]):
            outputs.append("Numerical calculations")
        if any(v in verbs for v in ["prove", "derive", "show"]):
            outputs.append("Mathematical proofs/derivations")
        if any(v in verbs for v in ["plot", "visualize", "graph"]):
            outputs.append("Data visualizations")
        if any(v in verbs for v in ["implement", "code"]):
            outputs.append("Code implementation")
        if "report" in tl or "explain" in verbs:
            outputs.append("Written explanations")
        return outputs or ["Solution deliverables"]

    def identify_grading_focus(self, text: str, verbs: list):
        f, tl = [], text.lower()
        if "detail how you arrived" in tl:
            f.append("Solution methodology")
        if any(v in verbs for v in ["prove", "show", "derive"]):
            f.append("Mathematical rigor")
        if any(v in verbs for v in ["implement", "code"]):
            f.append("Code correctness")
        if any(v in verbs for v in ["analyze", "evaluate"]):
            f.append("Analysis quality")
        # NEW: de-dupe while preserving order
        seen = set()
        out = []
        for item in f:
            k = item.lower()
            if k not in seen:
                seen.add(k)
                out.append(item)
        return out


    def generate_open_questions(self, text: str, highlights: dict):
        q = []
        if not highlights.get("requirements"):
            q.append("Submission format not clearly specified")
        tl = text.lower()
        if "python" not in tl and any(w in tl for w in ["code", "implement", "program"]):
            q.append("Programming language requirement unclear")
        return q

    def create_source_citations(self, text: str):
        citations = []
        sentences = re.split(r"[.!?]+", text)
        for i, sentence in enumerate(sentences):
            s = sentence.strip()
            if len(s) > 20 and any(k in s.lower() for k in ["submit", "due", "calculate", "implement", "analyze"]):
                citations.append({
                    "excerpt": s[:100] + "..." if len(s) > 100 else s,
                    "location": f"sentence_{i+1}"
                })
        return citations[:5]

    def extract_constraints(self, text: str):
        constraints = []
        for line in text.splitlines():
            if any(w in line.lower() for w in ["constraint", "requirement", "must", "only"]):
                constraints.append(line.strip())
        return constraints

    def calculate_confidence(self, highlights: dict):
        score = 0.5
        if highlights.get("action_verbs"): score += 0.2
        if highlights.get("requirements"): score += 0.1
        if highlights.get("technical_concepts"): score += 0.1
        if highlights.get("deliverables"): score += 0.1
        return min(score, 1.0)

    # ---------- low-level helpers ----------
    def detect_sections(self, text: str, section_names: list):
        sections = {}
        for section in section_names:
            pattern = rf"(?i)^.*{section}.*$"
            matches = re.findall(pattern, text, re.MULTILINE)
            if matches:
                sections[section] = matches
        return sections

    def is_google_doc_link(self, link: str):
        return "docs.google.com" in str(link)

    def size_mb(self, filepath: str):
        try:
            return os.path.getsize(filepath) / (1024 * 1024)
        except Exception:
            return 0

    def get_ext(self, filepath: str):
        return Path(filepath).suffix.lower().lstrip(".")

    # ---------- printing ----------
    def print_results(self):
        print("=" * 60)
        print("AI ASSIGNMENT ANALYSIS - KNOWLEDGE BASE BUILT")
        print("=" * 60)
        print(f"State: {self.state}\n")

        print("🎯 WHAT STUDENTS NEED TO DO (Action Verbs Found):")
        if self.highlights.get("action_verbs"):
            for verb in self.highlights["action_verbs"]:
                print(f"   • {verb}")
        print()

        print("📋 ASSIGNMENT TYPES IDENTIFIED:")
        for artifact in self.assignment_goals["artifact_types"]:
            print(f"   • {artifact.replace('_', ' ').title()}")
        print()

        print("📥 SPECIFIC INPUTS REQUIRED:")
        for input_item in self.assignment_goals["inputs"]:
            print(f"   • {input_item}")
        print()

        print("📤 EXPECTED OUTPUTS/DELIVERABLES:")
        for output in self.assignment_goals["expected_outputs"]:
            print(f"   • {output}")
        print()

        if self.assignment_goals["grading_focus"]:
            print("🎯 GRADING FOCUS AREAS:")
            for focus in self.assignment_goals["grading_focus"]:
                print(f"   • {focus}")
            print()

        if self.highlights.get("technical_concepts"):
            print("🔧 TECHNICAL CONCEPTS STUDENTS NEED:")
            for concept in self.highlights["technical_concepts"]:
                print(f"   • {concept}")
            print()

        if self.assignment_goals["source_citations"]:
            print("📑 KEY EXCERPTS IDENTIFIED:")
            for citation in self.assignment_goals["source_citations"]:
                print(f"   • {citation['excerpt']}")
            print()

        # Priority content
        priority_content = self.get_priority_content_for_response()

        print("🔥 HIGHEST PRIORITY FOR AI RESPONSES:")
        if priority_content["priority_citations"]:
            print("   Key Requirements:")
            for citation in priority_content["priority_citations"]:
                weight = citation.get("weight", 0.4)
                print(f"      • (Weight: {weight:.1f}) {citation['excerpt'][:60]}...")
        if priority_content["priority_verbs"]:
            print(f"   Critical Actions: {', '.join(priority_content['priority_verbs'])}")
        if priority_content["priority_concepts"]:
            print(f"   Core Concepts: {', '.join(priority_content['priority_concepts'])}")
        print()

        print(f"🎯 AI CONFIDENCE LEVEL: {self.assignment_goals['confidence']:.1%}")
        print("💡 This knowledge base will help the AI tutor provide targeted assistance!")


# ---------- convenience function ----------
def analyze_assignment_file(file_path: str, enable_ocr: bool = False):
    importer = ImportInstructions(enable_ocr=enable_ocr)
    print(f"Analyzing: {file_path}  (OCR={'ON' if enable_ocr else 'OFF'})")
    result = importer.upload_and_parse(file_path)
    if isinstance(result, dict) and "error" in result:
        print(f"Error: {result['error']}")
        return None
    importer.print_results()
    return importer


# ---------- hybrid CLI (args first, else prompt) ----------
if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 2:
        file_path = sys.argv[1]
        enable_ocr = ("--ocr" in sys.argv[2:])
    else:
        file_path = input("Enter path to assignment file (.pdf/.docx/.txt/.md): ").strip()
        ocr_in = input("Enable OCR for images? (y/N): ").strip().lower()
        enable_ocr = (ocr_in == "y")

    if not file_path:
        print("❌ No file path provided. Exiting.")
    else:
        analyze_assignment_file(file_path, enable_ocr=enable_ocr)
