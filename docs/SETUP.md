# SETUP — manual steps (do these yourself, once)

Everything here is the stuff Claude Code can't do for you: getting the key, the environment, and the secrets file.

---

## A. Get a free Gemini API key (~2 minutes, no credit card)

1. Go to **aistudio.google.com** and sign in with a Google account.
2. Click **Get API key** in the left sidebar.
3. Click **Create API key** → "Create API key in new project" (cleanest start).
4. **Copy the key immediately** (it starts with `AIza…`) — the UI won't show it again.

Free tier gives you Gemini **Flash** models (`gemini-2.5-flash`, `gemini-2.5-flash-lite`) at no cost. That's what we use. Don't call a `pro` model on a free key — it'll be rejected until you enable billing.

---

## B. Python environment

```bash
python --version            # need 3.11+
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Make sure `requirements.txt` includes: `google-genai`, `python-dotenv`, `pandas`, `rapidfuzz`, `chromadb`, `pydantic`, `fastapi`, `uvicorn`.

> ⚠️ If Claude Code ever writes `import google.generativeai` or `pip install google-generativeai`, that's the **old deprecated** package. Correct it to `pip install google-genai` and `from google import genai`.

---

## C. Secrets file (`.env`)

Create a file named `.env` in the repo root:

```
GEMINI_API_KEY=AIza...your-key-here...
```

Then make sure git ignores it — add this line to `.gitignore`:

```
.env
```

**Never commit the key.** Google auto-scans public GitHub and will revoke a leaked key (and someone could burn your quota). If it ever leaks: revoke it on the AI Studio keys page, create a new one, update `.env`.

---

## D. 30-second test that the key works

Save as `test_key.py`, run `python test_key.py`. If you see Arabic text, you're done.

```python
import os
from dotenv import load_dotenv
from google import genai

load_dotenv()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

resp = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="قل مرحبا بجملة واحدة.",
)
print(resp.text)
```

This is exactly the call shape `engine/explain.py` will use — just with your real prompt and the transaction aggregates.

---

## E. Gotchas to know before the demo

- **Rate limits (free tier):** ~250 requests/day and ~15/minute with an API key. Fine for building and the demo, but don't loop the LLM over 30k rows — Layer 3 only runs on aggregates, a handful of calls. If you hit a `429`, wait and add a short retry/backoff.
- **Free-tier data is used for Google's training.** This is fine for us — our data is **synthetic mock data**, nothing real. Never send real bank data over a free key. (Nice pitch point: in production you'd move to paid/on-prem for data residency — which is exactly the SAMA/"in-Kingdom" claim on your market-fit slide.)
- **"Get code" button:** if the SDK call signature ever looks different from the test above, AI Studio has a "Get code" button that prints the current working snippet for whatever you type — copy from there.
- **Region note:** free tier without billing works outside the EEA/UK/Switzerland, so you're fine.

---

## F. What's automatic (you don't do these manually)

CORS, the endpoints, the corrections store, running `uvicorn` — all handled by Claude Code from the specs. The only commands you'll run are the venv/pip ones above and `uvicorn api.main:app --reload` at the end.
