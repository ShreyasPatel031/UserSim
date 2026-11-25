// Slack -> Claude Code relay. Slack calls this on every @mention of the QA bot (Events API, app_mention);
// it checks Slack's signature, then fires the Claude Code scheduled task bound to the client QA session, which wakes
// that session with the message. Env (set in Vercel, never in the repo):
//   SLACK_SIGNING_SECRET  from the Slack app's Basic Information page
//   CC_FIRE_URL           the task's Fire URL (claude.ai/code -> scheduled task -> Edit -> Trigger -> API)
//   CC_FIRE_TOKEN         the token generated there
const crypto = require("crypto");

module.exports.config = { api: { bodyParser: false } };

function rawBody(req) {
  return new Promise((resolve, reject) => {
    let d = "";
    req.on("data", (c) => (d += c));
    req.on("end", () => resolve(d));
    req.on("error", reject);
  });
}

function validSlack(req, body) {
  const ts = req.headers["x-slack-request-timestamp"];
  const sig = req.headers["x-slack-signature"] || "";
  if (!ts || Math.abs(Date.now() / 1000 - Number(ts)) > 300) return false;
  const mine = "v0=" + crypto.createHmac("sha256", process.env.SLACK_SIGNING_SECRET || "")
    .update(`v0:${ts}:${body}`).digest("hex");
  return sig.length === mine.length && crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(mine));
}

module.exports = async (req, res) => {
  if (req.method !== "POST") return res.status(200).send("ok");
  const body = await rawBody(req);
  if (!validSlack(req, body)) return res.status(401).send("bad signature");
  const p = JSON.parse(body);
  if (p.type === "url_verification") return res.status(200).json({ challenge: p.challenge });
  if (req.headers["x-slack-retry-num"]) return res.status(200).send("retry ignored"); // fire once per mention
  const e = p.event || {};
  if (p.type === "event_callback" && (e.type === "app_mention" || (e.type === "message" && e.channel_type === "im" && !e.bot_id))) {
    const text = [
      `Slack ${e.type} in channel ${e.channel}`,
      `thread_ts ${e.thread_ts || e.ts}, ts ${e.ts}, from user ${e.user}`,
      `text: ${e.text || ""}`,
      (e.files || []).length ? `files: ${(e.files || []).map((f) => f.name).join(", ")}` : "",
    ].filter(Boolean).join("\n");
    const r = await fetch(process.env.CC_FIRE_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${process.env.CC_FIRE_TOKEN}`,
        "anthropic-beta": "experimental-cc-routine-2026-04-01",
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ text: text.slice(0, 60000) }),
    });
    console.log("fire", r.status);
  }
  return res.status(200).send("ok");
};
