"""
Bhasha Doubt Solver
===================
A Socratic doubt-solving tutor for students, with a persistent longitudinal
learner model.

Core behaviours (the three things that make it "Bhasha Doubt Solver" and not
a generic chatbot):
  1. It NEVER gives the answer. It always asks the student to explain their
     thinking first, then guides with the smallest possible nudge.
  2. It detects the underlying conceptual misconception behind the student's
     reasoning (via Sarvam-105B).
  3. It stores every misconception in a per-student SQLite model and, on every
     future turn, feeds that error history back into the prompt so guidance
     adapts across sessions.

Run:
    export SARVAM_API_KEY=...        # get one at https://dashboard.sarvam.ai
    python bhasha_doubt_solver.py

Without a key it runs in MOCK mode (rule-based Socratic replies) so you can
demo the full flow offline.
"""

import os
import re
import json
import sqlite3
import datetime

# --------------------------------------------------------------------------
# Config  (all overridable by env var)
# --------------------------------------------------------------------------
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "").strip()
BASE_URL = os.getenv("SARVAM_BASE_URL", "https://api.sarvam.ai/v1")
MODEL = os.getenv("SARVAM_MODEL", "sarvam-105b")
DB_PATH = os.getenv("DB_PATH", "learner_model.db")
MOCK = not SARVAM_API_KEY  # no key -> offline mock mode


# --------------------------------------------------------------------------
# 1. The persistent longitudinal learner model  (SQLite)
# --------------------------------------------------------------------------
def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS errors (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id    TEXT,
            skill         TEXT,
            misconception TEXT,
            created_at    TEXT,
            resolved      INTEGER DEFAULT 0
        )
        """
    )
    con.commit()
    con.close()


def log_error(student_id, skill, misconception, resolved=False):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT INTO errors (student_id, skill, misconception, created_at, resolved) "
        "VALUES (?,?,?,?,?)",
        (student_id, skill, misconception,
         datetime.datetime.now().isoformat(timespec="seconds"), int(resolved)),
    )
    con.commit()
    con.close()


def history_summary(student_id):
    """Aggregate a student's past errors into a short prompt-ready summary."""
    con = sqlite3.connect(DB_PATH)
    rows = con.execute(
        "SELECT skill, misconception, COUNT(*) AS n, SUM(resolved) AS fixed "
        "FROM errors WHERE student_id=? "
        "GROUP BY skill, misconception ORDER BY n DESC",
        (student_id,),
    ).fetchall()
    con.close()
    if not rows:
        return "No prior error history for this student."
    lines = []
    for skill, misc, n, fixed in rows:
        status = "resolved" if fixed else "still recurring"
        lines.append(f"- {misc} (skill: {skill}) — seen {n}x, {status}")
    return (
        "Known error patterns for THIS student, accumulated over past sessions. "
        "Probe for these early and adapt your guidance to pre-empt them:\n"
        + "\n".join(lines)
    )


# --------------------------------------------------------------------------
# 2. The Socratic system prompt  (this is the whole pedagogy)
# --------------------------------------------------------------------------
SOCRATIC_PROMPT = """You are the Bhasha Doubt Solver, a patient Socratic tutor for school \
students in India (Class 5-10). A student has brought you a doubt.

ABSOLUTE RULES — never break these:
1. NEVER state the final answer, and never solve the problem for the student.
2. Make the student reason. End your reply with a question that moves them one
   small step forward.
3. Prefer the smallest possible nudge: surface a contradiction in the student's
   OWN reasoning, or offer a tiny analogous case they can test themselves.
   Do NOT teach the rule or lecture.
4. Use the student's error history (below) — if a misconception is known to
   recur, probe for it early instead of waiting.
5. Be warm and brief: 2-4 sentences. Match the student's language exactly
   (English, Hindi, or Hinglish as they wrote it).

Return EXACTLY this block and nothing else:
MISCONCEPTION: <short tag for the underlying misconception, or NONE if they are correct>
SKILL: <the topic, e.g. "adding unlike fractions">
RESOLVED: <YES if the student's current understanding is now correct, else NO>
REPLY: <your Socratic reply to the student>"""


def build_system_prompt(student_id):
    return SOCRATIC_PROMPT + "\n\n--- STUDENT HISTORY ---\n" + history_summary(student_id)


# --------------------------------------------------------------------------
# 3. LLM call + output parsing
# --------------------------------------------------------------------------
def call_llm(system, messages):
    if MOCK:
        return mock_llm(messages)
    from openai import OpenAI  # imported lazily so mock mode needs no network
    client = OpenAI(api_key=SARVAM_API_KEY, base_url=BASE_URL)
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": system}] + messages,
            temperature=0.4,
            max_tokens=500,
        )
        return resp.choices[0].message.content
    except Exception as e:  # keep the app alive if the key/model/network hiccups
        return ("MISCONCEPTION: NONE\nSKILL: \nRESOLVED: NO\n"
                f"REPLY: [API error - check your SARVAM_API_KEY / model / network. {e}]")


def parse_output(text):
    """Pull the structured fields out of the model's reply."""
    out = {"misconception": "NONE", "skill": "", "resolved": False, "reply": text}
    m = re.search(r"REPLY:\s*(.*)", text, re.DOTALL)
    if m:
        out["reply"] = m.group(1).strip()
    for key, field in (("MISCONCEPTION", "misconception"),
                       ("SKILL", "skill"), ("RESOLVED", "resolved")):
        m = re.search(rf"{key}:\s*(.*)", text)
        if m:
            val = m.group(1).strip().splitlines()[0].strip()
            if field == "resolved":
                out["resolved"] = val.upper().startswith("Y")
            else:
                out[field] = val
    return out


# --------------------------------------------------------------------------
# 4. Mock brain (offline demo) — mimics the structured output
# --------------------------------------------------------------------------
def mock_llm(messages):
    student_text = messages[-1]["content"].lower()
    # a couple of canned misconceptions so the demo has something to log
    if "2/5" in student_text or ("add" in student_text and "fraction" in student_text):
        return (
            "MISCONCEPTION: Adds numerators and denominators separately "
            "(treats fractions as two whole numbers)\n"
            "SKILL: adding unlike fractions\n"
            "RESOLVED: NO\n"
            "REPLY: Good that you explained your thinking. Quick test: by your "
            "rule, 1/2 + 1/2 would be 2/4. Is a half plus a half really equal to "
            "a half? What does that tell you about adding the bottoms?"
        )
    if "denominator" in student_text or "common" in student_text:
        return (
            "MISCONCEPTION: NONE\n"
            "SKILL: adding unlike fractions\n"
            "RESOLVED: YES\n"
            "REPLY: Nice — you are converting to a common denominator before "
            "adding. Can you say in your own words why the denominators have to "
            "match before the pieces can be combined?"
        )
    return (
        "MISCONCEPTION: NONE\n"
        "SKILL: general\n"
        "RESOLVED: NO\n"
        "REPLY: Thanks for sharing your reasoning. Which part of your own "
        "explanation are you least sure about — can you walk me through just "
        "that step?"
    )


# --------------------------------------------------------------------------
# 5. Conversation logic (the state machine)
# --------------------------------------------------------------------------
ELICIT = ("Before I help — I won't just give you the answer. Tell me what YOU "
          "think the answer is, and how you got there. Even a guess is useful.")

# Per-session state lives in Gradio's gr.State: {"messages": [...], "logged": [...]}

def respond(student_id, user_msg, state):
    state = state or {"messages": [], "logged": []}
    msgs = state["messages"]

    # --- Turn 1: the student only stated the doubt. Always elicit reasoning. ---
    if not msgs:
        msgs.append({"role": "user", "content": user_msg})
        state["messages"] = msgs
        return state, ELICIT, f"[student: {student_id}] doubt received — awaiting reasoning"

    # --- Student explained their reasoning: diagnose + guide ---
    msgs.append({"role": "user", "content": user_msg})
    raw = call_llm(build_system_prompt(student_id), msgs)
    parsed = parse_output(raw)
    msgs.append({"role": "assistant", "content": parsed["reply"]})
    state["messages"] = msgs

    # Persist any newly-seen misconception to the longitudinal model
    status = "guiding"
    misc = parsed["misconception"]
    if misc and misc.upper() != "NONE" and misc not in state["logged"]:
        log_error(student_id, parsed["skill"], misc, resolved=parsed["resolved"])
        state["logged"].append(misc)
        status = f"logged misconception: {misc} (skill: {parsed['skill']})"
    if parsed["resolved"]:
        status = "student understanding looks correct now"

    return state, parsed["reply"], f"[student: {student_id}] {status}"


# --------------------------------------------------------------------------
# 6. UI (Gradio)
# --------------------------------------------------------------------------
def build_ui():
    import gradio as gr

    def on_send(student_id, user_msg, chat, state):
        if not user_msg.strip():
            return chat, state, "", history_view(student_id)
        state, reply, _status = respond(student_id, user_msg, state)
        chat = chat + [{"role": "user", "content": user_msg},
                       {"role": "assistant", "content": reply}]
        return chat, state, "", history_view(student_id)

    def new_session():
        return [], None, "", ""

    def history_view(student_id):
        return f"Learner model — {student_id}\n" + history_summary(student_id)

    with gr.Blocks(title="Bhasha Doubt Solver") as demo:
        gr.Markdown(
            "# Bhasha Doubt Solver\n"
            "*It never gives the answer. It asks you to explain first, then guides "
            "you — and remembers how you think.*"
            + ("\n\n**MOCK MODE** (no `SARVAM_API_KEY` set — using rule-based replies)"
               if MOCK else f"\n\n*model: `{MODEL}`*")
        )
        state = gr.State(None)
        with gr.Row():
            with gr.Column(scale=3):
                chat = gr.Chatbot(label="Tutor", height=420)
                student_id = gr.Textbox(label="Student ID (try the same ID twice to see it adapt)",
                                        value="aarav")
                msg = gr.Textbox(label="Your doubt", placeholder="e.g. how do I add 1/2 + 1/3?")
                with gr.Row():
                    send = gr.Button("Send", variant="primary")
                    reset = gr.Button("New session (keep learner model)")
            with gr.Column(scale=2):
                hist = gr.Textbox(label="Persistent learner model", lines=14, interactive=False)

        send.click(on_send, [student_id, msg, chat, state], [chat, state, msg, hist])
        msg.submit(on_send, [student_id, msg, chat, state], [chat, state, msg, hist])
        reset.click(new_session, None, [chat, state, msg, hist])
    return demo


def live_check():
    """One real API call so you can verify your key + model in ~10 seconds."""
    init_db()
    if MOCK:
        print("No SARVAM_API_KEY found. Set it, then re-run:  python bhasha_doubt_solver.py --check")
        return
    print(f"Calling {MODEL} at {BASE_URL} ...")
    msgs = [{"role": "user",
             "content": "i think 1/2 + 1/3 = 2/5 because you add the tops and the bottoms"}]
    raw = call_llm(build_system_prompt("__check__"), msgs)
    print("\n--- RAW MODEL OUTPUT ---\n" + raw)
    print("\n--- PARSED ---\n" + json.dumps(parse_output(raw), indent=2))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Bhasha Doubt Solver")
    ap.add_argument("--check", action="store_true", help="make one live API call and exit")
    ap.add_argument("--share", action="store_true", help="launch with a temporary public link")
    ap.add_argument("--port", type=int, default=None, help="port for the local server")
    args = ap.parse_args()

    if args.check:
        live_check()
    else:
        init_db()
        build_ui().launch(share=args.share, server_port=args.port)
