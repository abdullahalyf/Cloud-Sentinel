# Test results

## Rogue agents in real Docker (2026-10-27 17:41)

Setup: real Docker (10 agents), fallback rules (no API key), local SQLite

|Rogue type|Agent|Result|Decided by|Why|
|-|-|-|-|-|
|loop|agent-01|killed after 12.3 s|fallback|Same prompt repeated 9× in a minute — stuck in a loop.|
|token_bomb|agent-04|killed after 5.9 s|rules|Hard limit: 98,092 tokens/min ≥ hard limit 60,000|
|memory_leak|agent-07|killed after 11.3 s|rules|Hard limit: memory 91% ≥ hard limit 90%|
|paraphrase_loop|agent-09|NOT killed in 60 s|fallback|27,548 tokens/min ≥ soft limit 25,000|





### Scale test: 10 agents at once



`docker-compose.scale.yml`: agent-01..03 loop, 04..06 token_bomb, 07..08 memory_leak, 09..10 paraphrase_loop. Only agent-01, agent-04 and agent-07 were sent "rogue". Result: exactly those 3 were killed. The 6 healthy agents (02, 03, 05, 06, 08, 10) ran for 5+ minutes and were never killed. agent-09 (paraphrase_loop) only got WARNs.



### How to read the table



- **loop, token_bomb, memory_leak**: the simple rules catch them in about 6 to 12 seconds. No AI needed (this is the circuit breaker).

- **memory_leak** is caught by memory (91%), not by call rate: the agent makes only 1 call per second.

- **paraphrase_loop**: the same job (order 4471) in new words on every call, about 30,000 tokens/min. The rules only WARN (above the soft limit of 25,000, below the hard limit of 60,000) and the "same prompt repeated" rule cannot see it. **This one needs the AI brain**, which is the reason to use Claude. It still has to be measured on a laptop that has an API key.

- Brain used for this table: fallback rules (no API key), local SQLite database.

