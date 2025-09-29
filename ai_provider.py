# ai_provider.py
import os
from typing import List, Optional

# Gemini
try:
    import google.generativeai as genai
    _HAS_GEMINI = True
except Exception:
    _HAS_GEMINI = False

# OpenAI
try:
    from openai import OpenAI
    _HAS_OPENAI = True
except Exception:
    _HAS_OPENAI = False


class AIProvider:
    """
    Unified wrapper for AI backends:
      1) Gemini (preferred, if GOOGLE_API_KEY is set)
      2) OpenAI (if OPENAI_API_KEY is set)
      3) Local summarizer (fallback)
    """

    def __init__(self,
                 gemini_chat_model: str = "gemini-1.5-flash",
                 gemini_embed_model: str = "models/text-embedding-004",
                 openai_chat_model: str = "gpt-4o-mini",
                 openai_embed_model: str = "text-embedding-3-small"):

        self.gemini_chat_model = gemini_chat_model
        self.gemini_embed_model = gemini_embed_model
        self.openai_chat_model = openai_chat_model
        self.openai_embed_model = openai_embed_model

        self.mode = "local"  # default
        self.client = None

        # ---- Initialize Gemini ----
        if _HAS_GEMINI and os.getenv("GOOGLE_API_KEY"):
            try:
                genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
                self.client = genai
                self.mode = "gemini"
                print("🔌 AIProvider initialized with backend: gemini")
                return
            except Exception as e:
                print(f"⚠️ Gemini init failed: {e}")

        # ---- Initialize OpenAI ----
        if _HAS_OPENAI and os.getenv("OPENAI_API_KEY"):
            try:
                self.client = OpenAI()
                self.mode = "openai"
                print("🔌 AIProvider initialized with backend: openai")
                return
            except Exception as e:
                print(f"⚠️ OpenAI init failed: {e}")

        # ---- Local fallback ----
        print("⚠️ No valid AI backend found, falling back to local summarizer.")

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------
    def embed(self, texts: List[str]) -> List[List[float]]:
        try:
            if self.mode == "gemini":
                resp = self.client.embed_content(model=self.gemini_embed_model, content=texts)
                # Gemini returns a dict; get embedding(s) from resp
                if 'embedding' in resp:
                    return [resp['embedding']]
                elif 'embeddings' in resp:
                    return [e['embedding'] for e in resp['embeddings']]
                else:
                    raise ValueError("No embedding found in Gemini response")
            elif self.mode == "openai":
                resp = self.client.embeddings.create(
                    model=self.openai_embed_model,
                    input=texts
                )
                return [d.embedding for d in resp.data]
            else:
                return [[0.0] * 384 for _ in texts]  # dummy vector
        except Exception as e:
            print(f"❌ ERROR in embed(): {e}")
            return [[0.0] * 384 for _ in texts]

    # ------------------------------------------------------------------
    # Text generation
    # ------------------------------------------------------------------
    def generate(self, system: str, user: str, max_tokens: int = 512) -> str:
        try:
            # ---- Gemini ----
            if self.mode == "gemini":
                prompt = f"{system}\n\n{user}"
                resp = self.client.generate_content(
                    model=self.gemini_chat_model,
                    contents=[{"role": "user", "parts": [prompt]}],
                    generation_config={"max_output_tokens": max_tokens},
                )
                # Gemini returns a dict; get text from resp
                if 'candidates' in resp and resp['candidates']:
                    text = resp['candidates'][0]['content']['parts'][0]['text']
                    print(">>> RAW RESPONSE (Gemini):", text[:300], "...")
                    return text.strip()
                else:
                    raise ValueError("No candidates found in Gemini response")

            # ---- OpenAI ----
            elif self.mode == "openai":
                resp = self.client.chat.completions.create(
                    model=self.openai_chat_model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user}
                    ],
                    max_tokens=max_tokens,
                )
                text = resp.choices[0].message.content
                print(">>> RAW RESPONSE (OpenAI):", text[:300], "...")
                return text.strip()

            # ---- Fallback ----
            else:
                return self._local_summarize(system, user)

        except Exception as e:
            print(f"❌ ERROR in generate(): {e}")
            return self._local_summarize(system, user)

    # ------------------------------------------------------------------
    # Local summarizer (dummy fallback)
    # ------------------------------------------------------------------
    def _local_summarize(self, system: str, user: str) -> str:
        """
        If no backend is available, or an API call fails, return
        a safe summary instead of echoing the raw prompt.
        """
        return "⚠️ AI backend unavailable. Please check your API key or quota."

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------
    def active_backend(self) -> str:
        return self.mode
