# Team guide — setup আর Git (নতুনদের জন্য ধাপে ধাপে)

## ১. একবারই install করতে হবে
1. **Python 3.11+** → python.org থেকে নামাও। Windows-এ install করার সময় **"Add Python to PATH"** অবশ্যই টিক দেবে।
2. **Git** → git-scm.com
3. **Docker Desktop** → docker.com (শুধু Alif, Fojle আর Taseen-এর বাধ্যতামূলক; অন্যরা `--fake` mode দিয়েই কাজ চালাতে পারবে)
4. **Editor**: AntiGravity / VS Code / Codex, যার যেটা আছে।
5. GitHub account খুলে Alif-কে username পাঠাও। ও repo-তে collaborator হিসেবে add করে দেবে, তারপর email-এ আসা invite accept করবে।

## ২. Project নিজের কম্পিউটারে আনা
Terminal খোলো (Windows-এ "PowerShell"), তারপর:
```bash
git clone https://github.com/abdullahalyf/Cloud-Sentinel.git
cd Cloud-Sentinel
python -m venv .venv
# Windows:      .venv\Scripts\activate
# Mac/Linux:    source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env        # Mac/Linux-এ: cp .env.example .env
python scripts/check_setup.py
```
সব ✅ (বা ⚠️) দেখালে তুমি কাজ শুরু করার জন্য তৈরি। ❌ দেখালে তার ঠিক নিচের লাইনে কী করতে হবে লেখা থাকবে।

চালিয়ে দেখো:
```bash
python -m brain --fake             # এই terminal খোলা রাখো
streamlit run dashboard/app.py     # নতুন একটা terminal-এ (সেখানেও আগে activate করে নিও)
```
Browser-এ dashboard খুলবে। ২০ সেকেন্ড পর "beta" rogue হবে, আর কয়েক সেকেন্ডের মধ্যে 🟡 PAUSED হয়ে যাবে। এটাই আমাদের পুরো demo।

## ৩. প্রতিদিন কাজ করার নিয়ম (Git)
`main` branch-এ কেউ সরাসরি কাজ করবে না। প্রত্যেকে নিজের branch-এ কাজ করবে, শেষ হলে Pull Request খুলবে, Taseen review করে merge করবেন।

```bash
git checkout main
git pull                                  # সবার আগে নতুন কাজগুলো টেনে আনো
git checkout -b fojle/rogue-agent         # নিজের নাম/কাজের নাম দিয়ে branch
# ... কাজ করো ...
python -m pytest -q                       # সব pass করছে কিনা দেখো
git add .
git commit -m "Add memory-leak rogue mode"
git push -u origin fojle/rogue-agent
```
তারপর GitHub-এ গিয়ে **"Compare & pull request"** বাটনে চাপ দাও, Taseen-কে reviewer হিসেবে দাও।

**সোনালি নিয়মগুলো**
- শুধু নিজের folder-এ কাজ করবে (README-র টেবিলটা দেখো)। অন্যের folder-এ কিছু বদলাতে হলে আগে তাকে জানাবে।
- `.env` কখনো commit করবে না। API key, Supabase key শুধু WhatsApp/Discord-এ private-ভাবে শেয়ার করবে।
- `shared/contracts.py` বদলানোর দরকার মনে হলে আগে Alif আর Taseen-কে বলবে। এটা সবার কোডের মাঝখানের "চুক্তি"।
- Branch ছোট রাখবে। ১–২ দিনের কাজ হলেই PR খুলে দেবে।

## ৪. AI tool দিয়ে কাজ করার নিয়ম
যেকোনো AI tool-কে (Codex, AntiGravity, Puku) প্রথম message-এ এটা দেবে:

> Read AGENTS.md, docs/CONTRACTS.md and docs/tasks/<তোমার নাম>.md first. Then do task <নম্বর>.
> Only edit files in the folders I own. Run `python -m pytest -q` before you finish
> and tell me which files you changed and how to test it by hand.

AI কাজ শেষ করার পর **নিজে চালিয়ে দেখবে**, তারপর commit করবে। AI যদি `shared/contracts.py` বা অন্য কারো folder বদলায়, সেই অংশ বাদ দেবে (`git checkout -- <file>`)।

## ৫. কোথায় আটকালে কাকে বলবে
- Setup, Git, merge → Taseen
- Sentinel, Claude, Docker, "data আসছে না" → Alif
- Database, Supabase → Fojle (Alif সাহায্য করবে)
- Dashboard → Tamjid
