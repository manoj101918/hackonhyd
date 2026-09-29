# LinkedIn post (Prompt 3)

Paste everything between the lines. Replace `[REPO_URL]` with your public GitHub repo link (the guide requires the repo link in the main post).

---

Your AI on-call assistant will confidently recommend the fix that failed last month.

Mine said "restart the pods." That had failed three times.

So I gave it memory of every incident, including failed fixes.

What changed:
- Failed steps are stored as facts: "restart pods did NOT fix INC-031"
- Memory is recalled before the LLM speaks, not when it feels like it
- Recall by exact error string finds the same cause on other services
- Every cited incident ID is checked against what memory returned
- Only engineers write outcomes back

Before: "restart the pods."
After: "don't, it failed in INC-031, 038 and 044."

I picked Hindsight for agent memory; it even learned that lesson itself.

Code: [REPO_URL]

#AIAgents #AgentMemory #Hindsight #LLM

---

## After posting

1. **First comment:** your article URL, e.g. `Full write-up: [ARTICLE_URL]`
2. **Second comment** (from the guide): `Here's a link to Hindsight if you want to check it out: https://github.com/vectorize-io/hindsight`
3. Tag **Code.in** in the post (the guide asks for this on LinkedIn and on the article).
