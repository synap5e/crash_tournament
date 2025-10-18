# Crash Exploitability Ranking

You will rank the following crash reports by likely exploitability.

Each crash is described in a JSON file. Read and analyze the complete crash data from each file.

## Exploitability Criteria

Consider these factors when ranking crashes:

1. **Memory Corruption Severity**
   - Buffer overflows (stack/heap) > Use-after-free > Double-free > Null pointer dereference
   - Write primitives > Read primitives > Information leaks

2. **Exploitation Prerequisites**
   - No mitigations (ASLR, DEP, CFI) > Partial mitigations > Full mitigations
   - Predictable memory layout > Randomized layout
   - Direct control over corruption > Indirect control

3. **Code Execution Potential**
   - Direct EIP/RIP control > Function pointer corruption > Return address corruption
   - ROP/JOP gadgets available > No gadgets
   - Shellcode injection possible > Code reuse only

4. **Reliability & Consistency**
   - Deterministic crashes > Race conditions > Heisenbugs
   - Easy to trigger > Complex trigger conditions
   - No authentication required > Authentication bypass needed

5. **Impact Assessment**
   - Remote code execution > Local privilege escalation > Denial of service
   - Root/admin access > User-level access
   - Persistent effects > Temporary effects

Return JSON only: {"ordered": ["id1","id2",...], "rationale_top": "..."}

Do not include any other text.

## Crashes to compare:

{context}
