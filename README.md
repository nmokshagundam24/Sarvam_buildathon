# Bhasha Doubt Solver

A Socratic doubt-solving tutor for students. It **never gives the answer** — it asks the
student to explain their thinking first, detects the underlying misconception, and keeps a
persistent learner model that adapts how it guides them across sessions.

- **Frontend:** a static chat UI (`index.html`) — no build step.
- **Backend:** one Vercel serverless function (`api/chat.js`) that holds your Sarvam API key
  and calls `sarvam-105b`. The key never reaches the browser.
- **Learner model:** stored in the browser's `localStorage`, keyed by Student ID, so it
  persists across visits.

## Files

```
index.html          the chat UI
api/chat.js         serverless function -> Sarvam (holds the key, runs the Socratic logic)
.env.example        sample env file
.gitignore
```

## Deploy in ~10 minutes

### 1. Put this on GitHub
- Create a new **empty** repository on github.com (no README, no .gitignore).
- On your computer, in this folder, run:
  ```bash
  git init
  git add .
  git commit -m "Bhasha Doubt Solver"
  git branch -M main
  git remote add origin https://github.com/<your-username>/<your-repo>.git
  git push -u origin main
  ```
- *(No git? On github.com open the repo → "Add file" → "Upload files", drag in
  `index.html` and the `api` folder, and commit.)*

### 2. Import it on Vercel
- Go to vercel.com → **Add New → Project** → **Import Git Repository** → pick your repo.
- Framework Preset: **Other**. Leave build settings empty. Click **Deploy**.
- It will build once, then your site is live at `https://<project>.vercel.app`.

### 3. Add your Sarvam key
- In the Vercel project → **Settings → Environment Variables**:
  - Name: `SARVAM_API_KEY`  → Value: your Indus/Sarvam key
  - (optional) Name: `SARVAM_MODEL` → Value: `sarvam-105b`
- Click **Save**, then go to **Deployments → ⋯ → Redeploy** so the function picks it up.

That's it. Open the `.vercel.app` URL and start chatting.

## Run locally

### Option A — plain Node, no Vercel (simplest)
```bash
cp .env.example .env      # then paste your key into .env
node server.js
```
Open http://localhost:3000. That's it — `server.js` serves the page and runs the
same `/api/chat` function, with no extra tools.

### Option B — Vercel CLI (mirrors production exactly)
```bash
npm i -g vercel
cp .env.example .env      # then paste your key into .env
vercel dev
```
Then open http://localhost:3000.

## How the Socratic rules are enforced
- `api/chat.js` returns the fixed "explain your thinking first" line whenever the student has
  sent only their opening doubt — so the model literally cannot answer too early.
- After that, the model is forced to reply in a fixed `MISCONCEPTION / SKILL / RESOLVED / REPLY`
  block. The server splits it: `REPLY` goes to the student, the tags update the learner model.
- The learner model is sent back with every request and injected into the system prompt, so the
  tutor pre-empts known misconceptions.

## Troubleshooting: "error on the second message"

The first message is answered locally (the "explain your thinking" line), so the model —
and your key — is only used from the **second** message onward. An error there means the
setup, not the UI. Open the health check in a browser:

```
https://<your-app>.vercel.app/api/chat
```

You'll get something like `{"ok":true,"keySet":true,"model":"sarvam-105b",...}`. Then:

| What you see | Meaning | Fix |
| --- | --- | --- |
| `keySet: false` | The function has no key | Add `SARVAM_API_KEY` in Settings → Environment Variables, then **Redeploy** |
| `[Sarvam error 403 …]` | Key rejected | Re-copy the key (no spaces/quotes); confirm it's active |
| `[Sarvam error 404 …]` | Model id wrong for your key | Set `SARVAM_MODEL` (e.g. `sarvam-105b`) and redeploy |
| `[Couldn't reach Sarvam: …]` | Bad model id or network | Check `SARVAM_MODEL` spelling |
| `[No SARVAM_API_KEY …]` | Env var added but not redeployed | **Redeploy** — env changes only apply to new deployments |

The error text shown in the chat bubble (between the square brackets) is the exact message
from Sarvam — that's the fastest clue.

### "no text (finish_reason: length)"
`sarvam-105b` is a **hybrid reasoning** model — it "thinks" before it answers, so it spends
tokens on reasoning before writing anything. If `max_tokens` is too small, the budget is
used up by the reasoning and the reply comes back empty (`content: null`,
`finish_reason: length`). Two fixes:

- Raise the budget: set `SARVAM_MAX_TOKENS=4096` (the default) or higher.
- Or use the dialogue-tuned variant: set `SARVAM_MODEL=sarvam-105b-conversations`, which is
  post-trained for real-time dialogue and answers more directly.

## Notes
- The API key lives only in Vercel's environment variables — never commit it.
- Data is per-browser (`localStorage`). For a shared, server-side learner model you'd add a
  database (Vercel KV / Postgres) later.
