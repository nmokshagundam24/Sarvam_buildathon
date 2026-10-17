// Vercel serverless function: /api/chat
// Holds the Sarvam key server-side and enforces the Socratic behaviour.
// No npm dependencies needed — Node 18+ has global fetch.

const SOCRATIC_PROMPT = `You are the Bhasha Doubt Solver, a patient Socratic tutor for school students in India (Class 5-10). A student has brought you a doubt.

ABSOLUTE RULES - never break these:
1. NEVER state the final answer, and never solve the problem for the student.
2. Make the student reason. End your reply with a question that moves them one small step forward.
3. Prefer the smallest possible nudge: surface a contradiction in the student's OWN reasoning, or offer a tiny analogous case they can test themselves. Do NOT teach the rule or lecture.
4. Use the student's error history (below) - if a misconception is known to recur, probe for it early instead of waiting.
5. Be warm and brief: 2-4 sentences. Match the student's language exactly (English, Hindi, or Hinglish as they wrote it).

Return EXACTLY this block and nothing else:
MISCONCEPTION: <short tag for the underlying misconception, or NONE if they are correct>
SKILL: <the topic, e.g. "adding unlike fractions">
RESOLVED: <YES if the student's current understanding is now correct, else NO>
REPLY: <your Socratic reply to the student>`;

const ELICIT = "Before I help — I won't just give you the answer. Tell me what YOU think the answer is, and how you got there. Even a guess is useful.";

const SARVAM_URL = "https://api.sarvam.ai/v1/chat/completions";

function historySummary(learner) {
  if (!learner || !learner.length) return "No prior error history for this student.";
  return (
    "Known error patterns for THIS student, accumulated over past sessions. Probe for these early and adapt your guidance to pre-empt them:\n" +
    learner.map((e) => `- ${e.misconception} (skill: ${e.skill || "general"}) — seen ${e.count || 1}x`).join("\n")
  );
}

function parseOutput(text) {
  const out = { misconception: "NONE", skill: "", resolved: false, reply: text };
  const grab = (k) => { const m = text.match(new RegExp(k + ":\\s*(.*)")); return m ? m[1].split("\n")[0].trim() : null; };
  const misc = grab("MISCONCEPTION"); if (misc) out.misconception = misc;
  const skill = grab("SKILL"); if (skill) out.skill = skill;
  const res = grab("RESOLVED"); if (res) out.resolved = res.toUpperCase().startsWith("Y");

  const r = text.match(/REPLY:\s*([\s\S]*)/);
  let reply = r ? r[1].trim() : text;
  // Safety net: if the model leaked its own tag lines into the visible reply
  // (happens when it doesn't follow the format exactly), strip them out.
  reply = reply.replace(/^\s*(MISCONCEPTION|SKILL|RESOLVED)\s*:.*$/gim, "").trim();
  out.reply = reply || text;
  return out;
}

module.exports = async (req, res) => {
  // --- Health check: open https://<your-app>.vercel.app/api/chat in a browser ---
  if (req.method === "GET") {
    return res.status(200).json({
      ok: true,
      keySet: Boolean(process.env.SARVAM_API_KEY),
      keyPrefix: (process.env.SARVAM_API_KEY || "").slice(0, 6),
      model: process.env.SARVAM_MODEL || "sarvam-105b",
      node: process.version,
      hasFetch: typeof fetch === "function",
    });
  }
  if (req.method !== "POST") return res.status(405).json({ error: "Use POST" });

  // Vercel normally parses JSON, but be defensive.
  let body = req.body;
  if (typeof body === "string") { try { body = JSON.parse(body); } catch { body = {}; } }
  const { messages = [], learner = [], studentId = "student" } = body || {};
  const userMsgs = Array.isArray(messages) ? messages.filter((m) => m && m.role === "user") : [];

  // Rule 1, enforced server-side: never answer the very first message.
  if (userMsgs.length <= 1) {
    return res.status(200).json({ reply: ELICIT, misconception: "NONE", skill: "", resolved: false });
  }

  const key = process.env.SARVAM_API_KEY;
  if (!key) {
    return res.status(200).json({
      reply: "[No SARVAM_API_KEY on the server. Add it in Vercel → Settings → Environment Variables, then REDEPLOY — env changes only apply to new deployments.]",
      misconception: "NONE", skill: "", resolved: false,
    });
  }

  const model = process.env.SARVAM_MODEL || "sarvam-105b";
  const system = SOCRATIC_PROMPT + "\n\n--- STUDENT HISTORY ---\n" + historySummary(learner);
  const payload = {
    model,
    temperature: 0.4,
    // sarvam-105b is a hybrid reasoning model: it "thinks" before answering, so a
    // small budget gets consumed by reasoning and returns content:null. Give it room.
    max_tokens: Number(process.env.SARVAM_MAX_TOKENS || 4096),
    messages: [{ role: "system", content: system }, ...messages.map((m) => ({ role: m.role, content: m.content }))],
  };

  try {
    const r = await fetch(SARVAM_URL, {
      method: "POST",
      // Sarvam's canonical auth header. (It also accepts Authorization: Bearer,
      // but this is the one its own cURL examples use.)
      headers: { "Content-Type": "application/json", "api-subscription-key": key },
      body: JSON.stringify(payload),
    });
    const text = await r.text();
    if (!r.ok) {
      return res.status(200).json({
        reply: `[Sarvam error ${r.status} · model=${model} · ${text.slice(0, 300)}]`,
        misconception: "NONE", skill: "", resolved: false,
      });
    }
    let data = null;
    try { data = JSON.parse(text); } catch { /* not JSON */ }
    const raw = (data && data.choices && data.choices[0] && data.choices[0].message && data.choices[0].message.content) || "";
    if (!raw) {
      const fr = (data && data.choices && data.choices[0] && data.choices[0].finish_reason) || "unknown";
      return res.status(200).json({
        reply: `[Sarvam returned no text (finish_reason: ${fr}). This model reasons before answering, so it needs a larger budget — raise SARVAM_MAX_TOKENS, or set SARVAM_MODEL=sarvam-105b-conversations.]`,
        misconception: "NONE", skill: "", resolved: false,
      });
    }
    return res.status(200).json(parseOutput(raw));
  } catch (e) {
    return res.status(200).json({
      reply: `[Couldn't reach Sarvam: ${e.message}. Check the model id and that the key is valid.]`,
      misconception: "NONE", skill: "", resolved: false,
    });
  }
};
