# Content submission kit

Everything the content guide asks for, drafted from this repo. Your job: add your voice, publish, record.

| File | What it is | Guide step |
|---|---|---|
| [titles.md](titles.md) | 20 title options + recommended pick | Prompt 1 |
| [article.md](article.md) | Full article draft (~1,480 words of prose) | Prompt 2 |
| [linkedin-post.md](linkedin-post.md) | LinkedIn post (under 800 chars) + the comments to add | Prompt 3 |
| [video-script.md](video-script.md) | 3-minute video script with on-screen cues, 5 YouTube titles, thumbnail prompt | Prompts 5–6 |
| [../docs/img/](../docs/img/) | Screenshots + architecture diagram for the article | Step 3 |

**Hard rule: never mention the event or competition** (not even as a hashtag) in the article, post, video title or description; content that does is disqualified. All drafts here are clean. Keep them that way when you edit.

## Checklist

### 0. Repo (once per team)
- [x] Pushed to https://github.com/manoj101918/hackonhyd. Make sure it's set to **Public** (Settings → General → Danger Zone → Change visibility).
- [x] Repo link filled into the article, post and video description.
- [x] `.env` is not in the repo (gitignored).
- [ ] Once published, replace `[ARTICLE_URL]` / `[YOUTUBE_URL]` in the main README and video description.

### 1. Article (every team member, each their own)
- [ ] Pick a title from `titles.md` (or keep the recommended one).
- [ ] Edit `article.md` into your own voice. If you worked on a specific part, lean into it; teammates can cover different angles.
- [ ] Publish publicly on **Medium, Dev.to, Hashnode, Substack or a LinkedIn Article** (not Google Drive).
- [ ] Upload the images from `docs/img/` where the article references them (`architecture.png`, `compare.png`, `avoid-steps.png`, `memory-write.png`).
- [ ] Check the three links survived formatting: [Hindsight GitHub](https://github.com/vectorize-io/hindsight), [Hindsight docs](https://hindsight.vectorize.io/), [agent memory page](https://vectorize.io/what-is-agent-memory).
- [ ] Tag **Code.in** on the article.
- [ ] Submit the article as a **Link post** to one of r/llmdevs, r/sideproject, r/aiagents, r/aimemory.

Guide's pre-submit checklist, as drafted:
- [x] Title is about the idea/result, not the event
- [x] Opens with something specific and surprising
- [x] Problem explained in concrete terms
- [x] Shows where and how Hindsight is integrated
- [x] Real code snippets from the repo (3)
- [x] Concrete before/after example (memory off vs on)
- [x] Honest lessons and limitations
- [x] Screenshots/images included
- [ ] Published to a public, linkable URL ← you

### 2. LinkedIn post (every team member)
- [ ] Publish the post from `linkedin-post.md` with your repo link in the body.
- [ ] First comment: your article URL.
- [ ] Comment: `Here's a link to Hindsight if you want to check it out: https://github.com/vectorize-io/hindsight`
- [ ] Tag **Code.in**.

### 3. Video (one per team)
- [ ] Reset memory (`python scripts/seed_memory.py --reset`), restart the backend, practice once.
- [ ] Record 2–5 min at 1080p+ following `video-script.md` (talking head + screen preferred).
- [ ] Make a thumbnail with Google Nano Banana using the prompt in `video-script.md`.
- [ ] Upload to **YouTube as Public** with the thumbnail.

### Honest-content notes
- The drafts don't quote invented performance numbers. The MTTR curve in the app comes from synthetic history, so the article doesn't claim it as a measured result.
- The before/after quotes in the article come from real runs of the agent. Memory-off answers vary a little between runs, so re-check the quote if you re-record.
