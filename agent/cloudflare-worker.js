/**
 * Deal Assistant — optional generative brain (Cloudflare Worker proxy).
 *
 * Why this exists: the deal site is static (GitHub Pages), so an Anthropic API
 * key cannot live in the browser. This Worker keeps the key server-side and
 * exposes a single POST endpoint the site calls. The site already works fully
 * without it (local agent); deploy this only if you want true LLM reasoning.
 *
 * Deploy:
 *   1) npm i -g wrangler && wrangler login
 *   2) wrangler secret put ANTHROPIC_API_KEY        # paste your key
 *   3) wrangler deploy agent/cloudflare-worker.js --name ozb-deal-agent
 *   4) Put the resulting URL into user-prefs.json:
 *        "agent_llm_endpoint": "https://ozb-deal-agent.<you>.workers.dev"
 *   5) Tighten ALLOWED_ORIGIN below to your Pages origin.
 *
 * Request  body: { question, deals:[...], points:{}, history:[...] }
 * Response body: { reply: "..." }
 */

const ALLOWED_ORIGIN = "https://eswar67.github.io";
const MODEL = "claude-sonnet-4-6";

function cors(extra = {}) {
  return {
    "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    ...extra,
  };
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") return new Response(null, { headers: cors() });
    if (request.method !== "POST") return new Response("POST only", { status: 405, headers: cors() });

    let body;
    try { body = await request.json(); }
    catch { return new Response(JSON.stringify({ reply: "Bad request." }), { status: 400, headers: cors({ "Content-Type": "application/json" }) }); }

    const { question = "", deals = [], points = {}, history = [] } = body;
    if (!question.trim()) return new Response(JSON.stringify({ reply: "Ask me something about the deals." }), { headers: cors({ "Content-Type": "application/json" }) });

    const system = [
      "You are Deal Radar's assistant — a sharp, concise Australian deal analyst for one user (Eswar).",
      "You ONLY use the deals provided in the context; never invent deals, prices, or links.",
      "You understand savings, urgency, AI confidence, cashback stacking, price-beat, lowest-tracked price, and frequent-flyer points valuation.",
      "Point valuations: multiply points by the AUD-per-point rate in `points` (fall back to points.default). Show the math briefly.",
      "Be direct and numeric. Prefer 2–5 sentences. When listing deals, include the title and saving. Flag when a deal's market price is actually cheaper.",
      "Assume strong finance/tech literacy. Australian context and AUD.",
    ].join(" ");

    const context = {
      points,
      deals: deals.slice(0, 60),
      recent_questions: history.slice(-6),
    };

    const messages = [
      { role: "user", content: `Deal context (JSON):\n${JSON.stringify(context)}\n\nUser question: ${question}` },
    ];

    try {
      const r = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-api-key": env.ANTHROPIC_API_KEY,
          "anthropic-version": "2023-06-01",
        },
        body: JSON.stringify({ model: MODEL, max_tokens: 700, system, messages }),
      });
      if (!r.ok) {
        const t = await r.text();
        return new Response(JSON.stringify({ reply: "The assistant is unavailable right now." , detail: t.slice(0,200)}), { status: 502, headers: cors({ "Content-Type": "application/json" }) });
      }
      const data = await r.json();
      const reply = (data.content || []).filter(b => b.type === "text").map(b => b.text).join("\n").trim() || "(no reply)";
      return new Response(JSON.stringify({ reply }), { headers: cors({ "Content-Type": "application/json" }) });
    } catch (e) {
      return new Response(JSON.stringify({ reply: "The assistant hit an error." }), { status: 500, headers: cors({ "Content-Type": "application/json" }) });
    }
  },
};
