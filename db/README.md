# db/ — Database folder (Fojle)



## ফাইলগুলো কী করে



| ফাইল | কী করে | কখন চালাবে |

|---|---|---|

| `schema.sql` | ৪টা table বানায় | প্রথমবার, একবার |

| `security.sql` | Row Level Security (RLS) চালু করে। Dashboard-এর key শুধু পড়তে পারে | `schema.sql`-এর পরে, একবার |

| `cleanup.sql` | প্রতি ঘণ্টায় ১ দিনের পুরনো `agent_metrics` মোছে (pg_cron) | একবার |
| `summary.sql` | `Store.summary()`-র জন্য একটা function (`agent_token_totals`), যাতে Supabase-এ প্রতি agent-এর জন্য আলাদা query না লাগে | `schema.sql`-এর পরে, একবার |

| `reset.py` | ৪টা table-র **সব** data মোছে | প্রতিটা demo-র আগে |

| `check_rls.py` | RLS ঠিকমতো কাজ করছে কিনা পরীক্ষা করে | `security.sql` চালানোর পর |
| `rogue_times.py` | সত্যিকারের Docker-এ ৪ ধরনের rogue কত সেকেন্ডে kill হয় মাপে, ফল `docs/RESULTS.md`-এ লেখে (আগে sentinel আর agent চালু রাখতে হয়, উপরে ফাইলের ভেতরে লেখা আছে) | demo-র আগে, দরকার হলে |



- `.sql` ফাইল চালাতে: Supabase → **SQL Editor** → ফাইলের সব লেখা paste করো → **Run**। সবগুলো আবার চালালেও ক্ষতি নেই।

- `.py` ফাইল repo-র ভেতর থেকে চালাও, যেমন `python db/reset.py`।



## দুটো key, দুটো কাজ



| Key | কে ব্যবহার করে | কী করতে পারে |

|---|---|---|

| `service_role` (secret) | **Sentinel** আর agent | সব কিছু। RLS এর ওপর খাটে না। এটাই `.env`-এর `SUPABASE_KEY` |

| `anon` (public) | শুধু **Dashboard** | চারটা table **পড়তে** পারে, আর `commands`-এ নতুন `KILL` বা `GO_ROGUE` (status `pending`) **যোগ** করতে পারে। আর কিছু না |



`anon` key দিয়ে কেউ update, delete, truncate করতে পারবে না, নকল metric, alert বা action লিখতে পারবে না, আর `done` অবস্থার command বানাতে পারবে না।



## Dashboard নিরাপদ key দিয়ে চালানো



1. `anon` key নাও: Supabase → **Project Settings → API Keys → "Legacy anon, service_role API keys"** tab → **`anon` `public`** row → copy।

   (নতুন `sb_publishable_...` key আমাদের setup-এ `401` দিয়েছিল, তাই legacy `anon` key ব্যবহার করো।)

2. Dashboard-এর terminal-এ (`.env`-এর `service_role` key বদলাবে না, শুধু এই terminal-এর জন্য):



```

$env:SUPABASE_KEY="<anon key এখানে>"

streamlit run dashboard/app.py

```



Mac/Linux:



```

SUPABASE_KEY="<anon key এখানে>" streamlit run dashboard/app.py

```



`python-dotenv` আগে থেকে সেট করা variable বদলায় না, তাই terminal-এর key-ই জেতে। Sentinel অন্য terminal-এ `.env`-এর `service_role` key দিয়ে চলে।



## পরীক্ষা



```

$env:DASHBOARD_KEY="<anon key এখানে>"

python db/check_rls.py

Remove-Item Env:DASHBOARD_KEY

```



শেষে `18/18 checks passed.` দেখলে সব ঠিক। এটা শুধু `rls-check-xxxx` নামের test row বানায় আর শেষে মুছে দেয়, আসল data ছোঁয় না।



## কখনো করবে না



- `service_role` key dashboard-এ, browser-এ, chat-এ বা GitHub-এ দেবে না।

- `.env` কখনো commit করবে না।



## কিছু কাজ না করলে



| সমস্যা | সম্ভাব্য কারণ |

|---|---|

| Sentinel-এর data Supabase-এ জমছে না | Sentinel ভুল করে `anon` key পেয়েছে। `.env`-এ `service_role` key থাকতে হবে |

| Dashboard-এ `401` | key কপি করার সময় কিছু কেটে গেছে, বা `...`/space থেকে গেছে |

| Dashboard-এর Kill button কাজ করে না | `anon` শুধু `pending` অবস্থার `KILL` ও `GO_ROGUE` command যোগ করতে পারে। অন্য কিছু পাঠালে RLS আটকাবে |

| `check_rls.py` `FAIL` দেখায় | `security.sql` আবার চালাও, তারপর `check_rls.py` |



## সীমা (জেনে রাখো)



যার কাছে `anon` key আছে সে সব data **পড়তে** পারে। হ্যাকাথনের জন্য এটা ঠিক আছে। তবে সে data মুছতে বা নকল data লিখতে পারবে না।

