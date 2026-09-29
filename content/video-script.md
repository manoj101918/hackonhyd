# Video script: ~3 minutes (Prompt 5)

One video per team, posted **publicly on YouTube** (not Google Drive). Record at 1080p or higher; screen recording with a talking-head overlay is preferred. Don't mention the event or competition in the video, title or description.

**Before you record**
- Wipe practice runs so live IDs start at INC-047: stop the backend, run `python scripts/seed_memory.py --reset`, restart the backend. Wait about 2 minutes for Hindsight to consolidate observations.
- Start the app: backend (`uvicorn dejavu.main:app --app-dir backend --port 8000`) and frontend (`cd frontend && npm run dev`). Open http://localhost:5173 in a 1920×1080 window and zoom the browser to 110–125%.
- Close notifications. The Groq free tier allows 8k tokens a minute per model, so leave about 20 seconds between analyses. The agent falls back to a second model if it's rate-limited, but that is slower.
- Practice once. Use this as an outline; don't read it word for word.

---

## 1. Intro (0:00–0:30)

**On screen:** your face (webcam), then the app's empty incident channel with the **Memory ON** toggle visible top-right.

> "Hi, I'm [YOUR NAME]. This is Déjà Vu, an on-call agent for production incidents. Every time something breaks, most tools, and most AI assistants, start from zero. But the same incident has almost always happened before, and someone already found out which fix works and which one makes it worse. Déjà Vu remembers all of that, using Hindsight as its long-term memory."

## 2. The problem: no memory (0:30–1:00)

**On screen:** flip the toggle to **Memory OFF**. Click **▶ 1 · checkout-api · HTTP 500s** in the demo bar. Let the timeline stream: *Read logs, Recent deploys*.

> "Here's a real-looking alert: checkout is throwing 500s, and Postgres is refusing connections. With memory off, the agent is actually decent. It reads the logs and figures out it's connection-pool exhaustion."

**On screen:** scroll to the recommended steps and point at the restart step, if the run includes one (memory-off runs vary).

> "But look: it tells me to restart the pods. We've tried that three times before, for this exact problem, and it failed every time. The agent has no way to know that."

## 3. Demo: recall, retain, learn (1:00–2:30)

**On screen:** flip to **Memory ON**. The analysis re-runs. Point at the three purple **Recall memory** rows as they stream, then at the **Memory** panel on the right filling up with `world` / `experience` / `observation` badges.

> "Now memory on. Before the model says anything, the agent recalls from Hindsight three ways: the whole picture, the exact error string, and 'what worked and what failed last time.' Those are the memories on the right, with the incident they came from."

**On screen:** scroll to **Don't do this: it failed before**, and hover the `INC-031 / INC-038 / INC-044` chips.

> "Same model, same tools, completely different answer. Don't restart the pods: it failed in these three incidents. And every incident ID it cites is checked against what memory actually returned. It can't invent one."

**On screen:** click **Mark worked** on the first recommended step. Scroll down to the purple **memory write** message and show the retained sentences. Then click **Resolve & retain postmortem**.

> "When I mark a step as worked, that's retained to Hindsight right away, including the agent's own advice and whether it was right. That's how it learns from its own mistakes."

**On screen:** click **▶ 2 · payment-service · DB errors**, then the **Compare ON vs OFF** tab. Show the scoreboard, then the right column's similar incidents including **INC-047**.

> "Now a different service hits the same underlying failure. Side by side: without memory, zero incidents cited, and it suggests restarting again. With memory, it cites the incident I resolved thirty seconds ago, INC-047. It learned that live."

**On screen:** click **▶ 3 · Deploy check**. Show the **HIGH RISK** verdict with `INC-033` and `INC-041`.

> "Same memory before deploys: this payment config change is high risk, because the last two changes like it both preceded SEV1 outages."

## 4. Takeaway (2:30–3:00)

**On screen:** the **Learning** tab. Show *What Déjà Vu has learned*, pointing at the observation "Restarting pods is an ineffective remediation … failed in INC-031, INC-038 and INC-044", then the playbook.

> "What surprised me most: I never wrote the rule 'restarts don't fix pool exhaustion.' Hindsight consolidated it on its own from individual outcomes. My takeaway: store the failures, not just the fixes. An agent that only remembers what worked will happily recommend what didn't. The code's linked below."

---

## YouTube titles (pick one)

1. My AI on-call agent kept suggesting the fix that failed
2. Same LLM, same tools: memory changed every answer
3. I gave my incident agent a memory of failed fixes
4. Watch an AI agent learn from an outage in real time
5. Why your AI assistant keeps repeating last month's mistake

**Description template:** one-line summary, then `Code: [REPO_URL]`, `Article: [ARTICLE_URL]`, `Hindsight: https://github.com/vectorize-io/hindsight`.

---

## Thumbnail prompt (Prompt 6, for Google Nano Banana)

Select **Create image**, attach a photo of one or more team members, and paste:

```
Generate a viral thumbnail for this YouTube video. Make the thumbnail attention grabbing and something
that people scrolling would want to click on if they see it. The aspect ratio needs to be 16:9

Here is the video script:
An on-call AI agent for production incidents. Without memory it confidently says "restart the pods",
a fix that already failed three times. With Hindsight long-term memory it says "Don't restart the
pods: it failed in INC-031, INC-038 and INC-044", learns from each fix the engineer marks as worked,
and cites an incident resolved 30 seconds earlier. Visual idea: a dark ops-console screen with a red
"RESTART PODS?" crossed out and a purple glowing brain labelled "It failed 3 times", with the person
in the photo looking at the screen in surprise. Big bold text: "IT REMEMBERED".
```
