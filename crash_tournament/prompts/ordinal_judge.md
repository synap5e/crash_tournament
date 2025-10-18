# Crash Exploitability Ranking

You will rank the following crash reports by likely exploitability.

Each crash is described in a file. Read and analyze the complete crash data from each file.
The crashing input itself is stored next to the file as `input.js`.

Note that the crash files are un-minified fuzzer outputs.
They are NOT human-weaponized, and you may also consider the difficulty in weaponizing the the crash as taking away from its likelyhood of being exploitable.

Return JSON only: {"ordered": ["id1","id2",...], "rationale_top": "..."}

Do not include any other text.

## Crashes to compare:

{context}
