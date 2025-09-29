# memory_db.py
from typing import List, Dict, Any
import faiss, numpy as np, json, time
from pathlib import Path
from ai_provider import AIProvider

class MemoryDB:
    """
    FAISS index + JSONL metadata. Initializes index lazily using
    the dimension of the first vector you add (Gemini=768, OpenAI=1536, MiniLM=384).
    """
    def __init__(self, db_dir: str = "./memorydb"):
        self.db_dir = Path(db_dir)
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.ai = AIProvider()
        self.index = None
        self.metadata: List[Dict[str,Any]] = []
        self.index_path = self.db_dir/"faiss.index"
        self.meta_path  = self.db_dir/"meta.jsonl"

        # Only load if both files exist; otherwise we init lazily
        if self.index_path.exists() and self.meta_path.exists():
            self._load()

    def _save(self):
        if self.index is not None:
            faiss.write_index(self.index, str(self.index_path))
        with open(self.meta_path, "w", encoding="utf-8") as f:
            for m in self.metadata:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")

    def _load(self):
        self.index = faiss.read_index(str(self.index_path))
        self.metadata = []
        with open(self.meta_path, "r", encoding="utf-8") as f:
            for line in f:
                self.metadata.append(json.loads(line))

    def _ensure_index(self, dim: int):
        if self.index is None:
            self.index = faiss.IndexFlatIP(dim)

    def add_documents(self, chunks: List[Dict[str,Any]]):
        texts = [c["text"] for c in chunks]
        embs = self.ai.embed(texts)
        X = np.array(embs, dtype="float32")
        X = np.asarray(embs, dtype="float32")
        if X.ndim == 1:
            X = X[None, :]
        elif X.ndim > 2:
            X = X.reshape((X.shape[0], -1))

        # First call → decide dimension
        self._ensure_index(X.shape[1])
        faiss.normalize_L2(X)
        self.index.add(X)
        now = time.time()
        for c in chunks:
            c["_ts"] = now
            self.metadata.append(c)
        self._save()


    def search(self, query: str, k: int = 6) -> List[Dict[str,Any]]:
        if self.index is None:
            return []
        q = self.ai.embed([query])[0]
        q = np.array(q, dtype="float32")
        # Ensure query shape is (1, d) for FAISS
        if q.ndim == 1 and q.shape[0] == self.index.d:
            q = np.expand_dims(q, axis=0)
        if q.shape[1] != self.index.d:
            raise ValueError(f"Query dimension {q.shape} does not match index dimension {self.index.d}")
        faiss.normalize_L2(q)
        D, I = self.index.search(q, k)
        hits = []
        for d, idx in zip(D[0], I[0]):
            if idx == -1: continue
            meta = self.metadata[idx].copy()
            meta["_score"] = float(d)
            hits.append(meta)
        # Source-aware re-ranking (working_solution > instructions > slides)
        def boost(m):
            base = m.get("_score", 0.0)
            w = float(m.get("weight", 0.5))
            approved = 1.15 if "approved_concept" in (m.get("tags") or []) else 1.0
            src_boost = {"working_solution":1.2,"instructions":1.1,"slides":1.05}.get(m.get("source_type"),1.0)
            return base * (0.4 + 0.6*w) * approved * src_boost
        hits.sort(key=boost, reverse=True)
        return hits

    def explain(self, query: str, hits: List[Dict[str,Any]]) -> str:
        lines = [f"Backend: {self.ai.active_backend()} — why these results:"]
        from pathlib import Path
        for h in hits[:5]:
            lines.append(
                f"- [{h.get('source_type')}] {Path(h.get('file_path','?')).name} "
                f"(section={h.get('section')}, weight={h.get('weight')}, score≈{round(h.get('_score',0),3)})"
            )
        return "\n".join(lines)
