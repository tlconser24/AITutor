# CapstoneIntegration.py
from pathlib import Path
import sys

# If this file sits next to CapstoneImportOnly.py and CapstoneImportSample.py,
# relative imports will just work. Otherwise, uncomment the next two lines:
# ROOT = Path(__file__).resolve().parent
# sys.path.append(str(ROOT))

try:
    from CapstoneImportOnly import ImportInstructions   # your weighted importer for instructions
    from CapstoneImportSample import ImportSample       # must exist and match the calls below
    print("✅ Imported ImportInstructions and ImportSample")
except ImportError as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)


class WeightedIntegratedAnalyzer:
    """Runs instruction + sample analysis, then builds a weighted knowledge object."""
    def __init__(self):
        self.instruction_analyzer = None
        self.sample_analyzer = None
        self.weighted_integrated_knowledge = {}

    def analyze_complete_assignment(self, instruction_file: str, sample_file: str):
        print("🚀 WEIGHTED INTEGRATED ASSIGNMENT ANALYSIS")
        print("=" * 70)

        # --- Step 1: Instructions ---
        print("\n📋 STEP 1: ANALYZING ASSIGNMENT INSTRUCTIONS (With Weights)")
        print("-" * 50)
        self.instruction_analyzer = ImportInstructions()
        instruction_result = self.instruction_analyzer.upload_and_parse(instruction_file)
        if isinstance(instruction_result, dict) and "error" in instruction_result:
            return {"error": f"Instruction analysis failed: {instruction_result['error']}"}
        self.instruction_analyzer.print_results()

        # --- Step 2: Sample Solution ---
        print("\n🔬 STEP 2: ANALYZING SAMPLE SOLUTION (With Weights)")
        print("-" * 50)
        assignment_goals = self.instruction_analyzer.assignment_goals
        self.sample_analyzer = ImportSample(assignment_goals)  # your class must accept goals
        sample_result = self.sample_analyzer.upload_and_analyze(sample_file)
        if isinstance(sample_result, dict) and "error" in sample_result:
            return {"error": f"Sample analysis failed: {sample_result['error']}"}
        self.sample_analyzer.print_results()

        # --- Step 3: Build integrated, weighted knowledge ---
        print("\n🎯 STEP 3: BUILDING WEIGHTED AI KNOWLEDGE BASE")
        print("-" * 50)
        self.weighted_integrated_knowledge = self.build_weighted_integrated_knowledge()
        self.print_weighted_integration_analysis()

        # Optional: index the **integrated** knowledge into MemoryDB
        try:
            from memory_db import MemoryDB
            mdb = MemoryDB()
            chunks = []

            instr_prior = self.instruction_analyzer.get_priority_content_for_response()
            # Approved/core concepts
            for c in instr_prior.get("priority_concepts", []):
                chunks.append({
                    "text": c,
                    "source_type": "instructions",
                    "file_path": "INSTRUCTOR_APPROVED_CONCEPTS",
                    "section": "approved_core_concepts",
                    "weight": 1.0,
                    "priority": "critical",
                    "tags": ["approved_concept", "core_concept"]
                })
            # Grading focus
            for gf in instr_prior.get("grading_focus", []):
                chunks.append({
                    "text": f"Grading focus: {gf}",
                    "source_type": "instructions",
                    "file_path": "GRADING_FOCUS",
                    "section": "rubric",
                    "weight": 0.95,
                    "priority": "high",
                    "tags": ["grading", "approved_concept"]
                })
            # High-weight sample learning explanations (if provided by your ImportSample)
            sample_prior = getattr(self.sample_analyzer, "get_learning_focused_content_for_response", lambda: {})()
            for le in sample_prior.get("learning_explanations", []):
                txt = le.get("text", "")
                w = float(le.get("weight", 0.8))
                if txt:
                    chunks.append({
                        "text": txt,
                        "source_type": "working_solution",
                        "file_path": "SAMPLE_SOLUTION",
                        "section": le.get("scope", "comment"),
                        "weight": w,
                        "priority": "high" if w >= 0.8 else "medium",
                        "tags": ["solution_explanation"]
                    })

            if chunks:
                mdb.add_documents(chunks)
                print(f"✅ Indexed {len(chunks)} integrated knowledge chunk(s) into MemoryDB")
        except Exception as e:
            print(f"[MemoryDB] Skipped indexing integrated knowledge: {e}")

        return {
            "instruction_analysis": instruction_result,
            "sample_analysis": sample_result,
            "weighted_integrated_knowledge": self.weighted_integrated_knowledge,
            "status": "success"
        }

    # ---------- Builders ----------
    def build_weighted_integrated_knowledge(self):
        instr = self.instruction_analyzer.get_priority_content_for_response()
        samp = self.sample_analyzer.get_learning_focused_content_for_response()
        return {
            "weighted_assignment_match": self.analyze_weighted_assignment_match(),
            "priority_learning_path": self.create_priority_learning_path(instr, samp),
            "weighted_tutoring_strategy": self.build_weighted_tutoring_strategy(instr, samp),
            "prioritized_student_guidance": self.create_prioritized_student_guidance(instr, samp),
            "essential_knowledge_map": self.create_essential_knowledge_map(instr, samp),
        }

    def analyze_weighted_assignment_match(self):
        instr = self.instruction_analyzer.get_priority_content_for_response()
        samp = self.sample_analyzer.get_learning_focused_content_for_response()

        expected_artifacts = set(self.instruction_analyzer.assignment_goals.get("artifact_types", []))
        found_artifacts = set(self.sample_analyzer.mapping_summary.get("artifacts_found", []))

        priority_concepts = set(instr.get("priority_concepts", []))
        sample_concepts = set()
        for comment in samp.get("learning_explanations", []):
            ct = comment.get("text", "").lower()
            for concept in priority_concepts:
                if concept.lower() in ct:
                    sample_concepts.add(concept)

        artifact_match = (len(expected_artifacts & found_artifacts) /
                          len(expected_artifacts | found_artifacts) * 100) if (expected_artifacts | found_artifacts) else 0.0
        concept_match = (len(priority_concepts & sample_concepts) /
                         len(priority_concepts) * 100) if priority_concepts else 0.0
        overall = artifact_match * 0.4 + concept_match * 0.6

        return {
            "artifact_match_score": artifact_match,
            "concept_match_score": concept_match,
            "overall_weighted_match": overall,
            "expected_artifacts": list(expected_artifacts),
            "found_artifacts": list(found_artifacts),
            "priority_concepts_matched": list(priority_concepts & sample_concepts),
            "missing_concepts": list(priority_concepts - sample_concepts),
            "learning_alignment": (
                "excellent" if overall >= 80 else "good" if overall >= 60 else "needs_improvement"
            ),
        }

    def create_priority_learning_path(self, instr, samp):
        lp = {"critical_first_steps": [], "core_learning_sequence": [], "implementation_guidance": [], "verification_steps": []}
        for cit in instr.get("priority_citations", []):
            if cit.get("weight", 0) >= 1.0:
                lp["critical_first_steps"].append({
                    "step": cit["excerpt"][:80] + "...",
                    "importance": "critical",
                    "weight": cit.get("weight", 1.0),
                })
        for ex in samp.get("learning_explanations", []):
            if ex.get("weight", 0) >= 0.8:
                lp["core_learning_sequence"].append({
                    "concept": ex["text"][:100] + "...",
                    "source": ex.get("scope", "unknown"),
                    "weight": ex.get("weight", 0.8),
                })
        for v in instr.get("priority_verbs", []):
            lp["implementation_guidance"].append({
                "action": v, "guidance": f"Focus on {v} using sample solution approach", "weight": 1.0
            })
        for gf in instr.get("grading_focus", []):
            lp["verification_steps"].append({"check": gf, "importance": "critical", "weight": 1.0})
        return lp

    def build_weighted_tutoring_strategy(self, instr, samp):
        return {
            "response_prioritization": self.create_response_prioritization_rules(),
            "question_detection": self.create_weighted_question_detection(),
            "explanation_hierarchy": self.create_explanation_hierarchy(instr, samp),
            "mistake_prevention": self.create_weighted_mistake_prevention(samp),
            "scaffolding_approach": self.create_weighted_scaffolding(instr),
        }

    def create_response_prioritization_rules(self):
        return {
            "rule_1": "Lead with weight 1.0 content (critical objectives/requirements).",
            "rule_2": "Then weight 0.8–0.9 (core concepts/explanations).",
            "rule_3": "Use 0.6–0.7 (implementation details) as support.",
            "rule_4": "Use <0.6 content only if asked.",
            "rule_5": "When ties exist, rank by question relevance.",
        }

    def create_weighted_question_detection(self):
        instr = self.instruction_analyzer.get_priority_content_for_response()
        samp = self.sample_analyzer.get_learning_focused_content_for_response()
        return {
            "priority_concepts": instr.get("priority_concepts", []),
            "priority_verbs": instr.get("priority_verbs", []),
            "learning_explanations_keywords": [ex["text"][:50].lower() for ex in samp.get("learning_explanations", [])],
            "essential_libraries": [lib["name"] for lib in samp.get("essential_libraries", [])],
        }

    def create_explanation_hierarchy(self, instr, samp):
        return {
            "level_1_critical": {
                "content": instr.get("priority_citations", [])[:2],
                "approach": "Start with these critical requirements."
            },
            "level_2_core_concepts": {
                "content": samp.get("learning_explanations", [])[:3],
                "approach": "Explain with high-weight solution insights."
            },
            "level_3_implementation": {
                "content": samp.get("key_learning_outcomes", [])[:3],
                "approach": "Show implementation tactics."
            },
            "level_4_supporting": {
                "content": samp.get("essential_libraries", []),
                "approach": "Add library-specific tips as needed."
            },
        }

    def create_weighted_mistake_prevention(self, samp):
        out = []
        for ex in samp.get("learning_explanations", []):
            t = ex.get("text", "").lower()
            if "calculate" in t and "probability" in t:
                out.append({"mistake": "Incorrect probability method",
                            "prevention": "Walk through step-by-step probability reasoning",
                            "weight": ex.get("weight", 0.8)})
            if "expected" in t:
                out.append({"mistake": "Confusing expected value",
                            "prevention": "Reinforce definition vs other statistics",
                            "weight": ex.get("weight", 0.8)})
        for lib in samp.get("essential_libraries", []):
            if lib.get("name") == "random":
                out.append({"mistake": "Misusing simulations",
                            "prevention": "Clarify simulation vs analytic solution",
                            "weight": lib.get("weight", 0.7)})
        return sorted(out, key=lambda x: x["weight"], reverse=True)

    def create_weighted_scaffolding(self, instr):
        out = []
        for v in instr.get("priority_verbs", []):
            if v in ["calculate", "compute"]:
                out.append({"step": f"Guide student to {v} step-by-step",
                            "approach": "Break down the math reasoning",
                            "weight": 1.0})
            elif v in ["implement", "code"]:
                out.append({"step": f"Guide student to {v} systematically",
                            "approach": "Start with pseudocode → implement",
                            "weight": 1.0})
        return out

    def create_prioritized_student_guidance(self, instr, samp):
        g = {"getting_started": [], "when_stuck": [], "checking_work": [], "common_questions": []}
        for cit in instr.get("priority_citations", [])[:2]:
            g["getting_started"].append({"guidance": f"Start by understanding: {cit['excerpt'][:60]}...", "weight": cit.get("weight", 1.0)})
        for ex in samp.get("learning_explanations", [])[:2]:
            g["when_stuck"].append({"guidance": f"Review this key concept: {ex['text'][:60]}...", "weight": ex.get("weight", 0.8)})
        for focus in instr.get("grading_focus", []):
            g["checking_work"].append({"guidance": f"Verify your {focus.lower()}", "weight": 1.0})
        return g

    def create_essential_knowledge_map(self, instr, samp):
        km = {"must_know": [], "should_know": [], "helpful_to_know": []}
        for cit in instr.get("priority_citations", []):
            w = cit.get("weight", 0.5)
            item = {"content": cit["excerpt"], "type": "requirement", "weight": w}
            (km["must_know"] if w >= 0.9 else km["should_know"] if w >= 0.7 else km["helpful_to_know"]).append(item)
        for ex in samp.get("learning_explanations", []):
            w = ex.get("weight", 0.5)
            item = {"content": ex["text"], "type": "explanation", "weight": w}
            (km["must_know"] if w >= 0.9 else km["should_know"] if w >= 0.7 else km["helpful_to_know"]).append(item)
        return km

    def print_weighted_integration_analysis(self):
        print("🎯 WEIGHTED INTEGRATION ANALYSIS")
        print("=" * 70)

        match = self.weighted_integrated_knowledge["weighted_assignment_match"]
        print(f"\n✅ WEIGHTED ASSIGNMENT-SOLUTION MATCH:")
        print(f"   Overall Weighted Score: {match['overall_weighted_match']:.1f}%")
        print(f"   Artifact Match: {match['artifact_match_score']:.1f}%")
        print(f"   Concept Match: {match['concept_match_score']:.1f}%")
        print(f"   Learning Alignment: {match['learning_alignment']}")
        if match["priority_concepts_matched"]:
            print(f"   Priority Concepts Covered: {', '.join(match['priority_concepts_matched'])}")
        if match["missing_concepts"]:
            print(f"   ⚠️ Missing Concepts: {', '.join(match['missing_concepts'])}")

        lp = self.weighted_integrated_knowledge["priority_learning_path"]
        print(f"\n🛤️  PRIORITY LEARNING PATH:")
        if lp["critical_first_steps"]:
            print("   🚨 Critical First Steps:")
            for step in lp["critical_first_steps"][:2]:
                print(f"      • (Weight: {step['weight']:.1f}) {step['step']}")
        if lp["core_learning_sequence"]:
            print("   🎯 Core Learning Sequence:")
            for concept in lp["core_learning_sequence"][:3]:
                print(f"      • (Weight: {concept['weight']:.1f}) {concept['concept']}")

        strat = self.weighted_integrated_knowledge["weighted_tutoring_strategy"]
        print(f"\n🎓 WEIGHTED AI TUTORING STRATEGY:")
        print("   📋 Response Prioritization Rules:")
        for _, rule in strat["response_prioritization"].items():
            print(f"      • {rule}")

        km = self.weighted_integrated_knowledge["essential_knowledge_map"]
        print(f"\n🧠 ESSENTIAL KNOWLEDGE MAP:")
        print(f"   Must Know (≥0.9): {len(km['must_know'])} items")
        print(f"   Should Know (≥0.7): {len(km['should_know'])} items")
        print(f"   Helpful (≥0.5): {len(km['helpful_to_know'])} items")
        if km["must_know"]:
            print("   🔥 Top Must-Know Items:")
            for item in km["must_know"][:3]:
                print(f"      • (Weight: {item['weight']:.1f}) {item['content'][:60]}...")

        print("\n🤖 AI TUTOR READINESS: WEIGHT-PRIORITIZED AND INDEXED")


# Convenience runner
def run_weighted_integrated_analysis(instruction_file: str, sample_file: str):
    analyzer = WeightedIntegratedAnalyzer()
    res = analyzer.analyze_complete_assignment(instruction_file, sample_file)
    if isinstance(res, dict) and "error" in res:
        print(f"❌ Analysis failed: {res['error']}")
        return None
    return analyzer


if __name__ == "__main__":
    import sys

    # --- Hybrid: arguments take priority ---
    if len(sys.argv) >= 3:
        instruction_path = sys.argv[1]
        sample_path = sys.argv[2]
    else:
        # Fallback to prompts
        instruction_path = input("Enter path to assignment instructions file: ").strip()
        sample_path = input("Enter path to sample solution file: ").strip()

    if not instruction_path or not sample_path:
        print("❌ Both files are required.")
        sys.exit(1)

    print("\n🚀 Starting Weighted Integrated Analysis...\n")
    analyzer = run_weighted_integrated_analysis(instruction_path, sample_path)

    if analyzer:
        print("\n" + "=" * 70)
        print("✅ WEIGHTED INTEGRATION COMPLETE!")
        print("The AI now has weight-prioritized understanding of your assignment and sample solution.")
