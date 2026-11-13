# Agent architecture (draft figure source)

Draft source for the paper's architecture figure. GitHub renders the Mermaid
block below; it can also be pasted into https://mermaid.live to export PNG/SVG,
or redrawn in draw.io / TikZ. Everything here matches the code in
`src/grocery_agent/llm_agents.py` (graph) and `src/grocery_agent/prompts.py` (prompts).

Legend: **blue = LLM call**, **green = deterministic code**, **orange = benchmark tools / environment**.

## Main diagram

```mermaid
flowchart TD
    %% ---------- inputs ----------
    subgraph IN["Public input (per episode)"]
        I1["Shopper instruction<br/>(high / medium / low specificity)"]
        I2["Household context<br/>(lists, pantry, budget, dietary notes)"]
        I3["Initial cart"]
    end

    %% ---------- agent ----------
    subgraph AG["Intent-grounded agent (LangGraph state machine)"]
        OBS["① Observe<br/>view_cart"]
        INT["② Intent extraction<br/>LLM, JSON mode<br/>→ requirements with measure + min/max,<br/>required tags, budget, preferences,<br/>keep/remove rules, open questions"]
        Q{"Mandatory info<br/>missing?"}
        CLA["③ Clarify<br/>ask_user (≤3 questions, 1 round)"]
        SHOP["④ Shopping loop<br/>LLM + tool calling (≤30 turns)<br/>search → inspect → add / update / remove"]
        SUB["submit_cart<br/>(product → requirement assignment)"]
        VER["⑤ Verifier<br/>deterministic check vs. structured intent:<br/>quantity in [min,max] per unit/measure,<br/>required tags (unknown ≠ satisfied),<br/>budget, unassigned extras,<br/>kept items, out-of-stock"]
        V{"Violations?"}
        FIN["⑥ Finish"]
    end

    %% ---------- state ----------
    ST[("Typed graph state<br/>intent · clarifications ·<br/>message history · product cache ·<br/>verifier reports")]

    %% ---------- environment ----------
    subgraph ENV["Benchmark environment (shared by all agents)"]
        TOOLS["Tools: search_products · get_product · view_cart ·<br/>add_to_cart · update_quantity · remove_from_cart ·<br/>ask_user · finish"]
        CAT[("Fixed catalog<br/>+ stock events")]
        RESP["Scripted clarification responder"]
    end

    I1 --> OBS
    I2 --> OBS
    I3 --> OBS
    OBS --> INT
    INT --> Q
    Q -- "yes (first time)" --> CLA
    CLA -- "answers appended" --> INT
    Q -- "no" --> SHOP
    SHOP <-->|"tool calls / observations"| TOOLS
    SHOP --> SUB
    SUB --> VER
    VER --> V
    V -- "yes, ≤2 repair rounds:<br/>violation list fed back" --> SHOP
    V -- "no / rounds exhausted" --> FIN
    FIN --> TOOLS
    CLA --> RESP
    TOOLS --- CAT

    INT -.-> ST
    CLA -.-> ST
    SHOP -.-> ST
    VER -.-> ST

    classDef llm fill:#dbe9fb,stroke:#2a78d6,color:#0d366b
    classDef det fill:#d9f2e6,stroke:#1baf7a,color:#0b4d34
    classDef env fill:#fde4d8,stroke:#eb6834,color:#6b2a0e
    classDef dec fill:#ffffff,stroke:#888780
    class INT,SHOP llm
    class OBS,CLA,SUB,VER,FIN det
    class TOOLS,CAT,RESP env
    class Q,V dec
```

## Plain-text fallback

```
 instruction + household context + initial cart
                     |
                     v
              (1) Observe ---------------------------------------------+
                     |                                                  |
                     v                                                  |
        (2) Intent extraction  [LLM, JSON]  <---- answers ----+         |
                     |                                         |         |
          mandatory info missing? --yes--> (3) Clarify (ask_user)        |
                     | no                                                |
                     v                                                   v
        (4) Shopping loop [LLM + tools]  <------ tool calls ------>  Benchmark tools
                     |   ^                                          (catalog, stock events,
               submit_cart|                                          scripted responder)
                     v   | violation list (<= 2 repair rounds)
        (5) Verifier [deterministic code] --no violations--> (6) Finish
```

## Components

| # | Component | LLM? | Input | Output | Purpose |
|---|---|---|---|---|---|
| ① | Observe | no | environment | current cart | Starts from the true cart state (some tasks prefill the cart) |
| ② | Intent extraction | **yes** (JSON mode) | instruction, context, cart, clarification answers | structured intent: requirements (`measure` ∈ units / count / volume_ml / weight_g / portions:role, `min`, `max`, `required_tags`, `brand`), `budget_cents`, global tags, preferences, keep/remove flags, `open_questions` | Turns language into checkable, unit-aware constraints |
| ③ | Clarify | no (questions come from ②) | `open_questions` | answers from the shopper | Asks only for *mandatory* missing information, then re-runs ② |
| ④ | Shopping loop | **yes** (tool calling) | context + structured intent as a checklist; verifier feedback | cart actions, then `submit_cart` with product→requirement assignment | Searches, inspects tags/sizes/portions, chooses products jointly under the budget, substitutes after stock failures |
| ⑤ | Verifier | no | cart, product details, intent, assignment | list of violations | Separates "tool calls succeeded" from "goal satisfied"; violations go back to ④ |
| ⑥ | Finish | no | — | ends episode | Cart is scored by the benchmark evaluator (outside the agent) |

**Memory/state:** typed LangGraph state holding the intent, clarification Q&A, the full shopping message history (kept across repair rounds), a product-detail cache, and verifier reports.
**Error handling:** tool failures are returned to the LLM as observations (e.g. "Out of stock"); invalid JSON from ② is retried once; API errors are retried by the client; the environment enforces 100 tool calls / 100 model calls / 300 s.

## Comparison with the baselines (same model, same tools, same caps)

| | Direct function calling | ReAct | Ours |
|---|---|---|---|
| Sees tool results before acting again | only after its single information turn | yes | yes |
| Can recover from stock failures | no | yes | yes |
| Explicit structured intent | no | no | **yes** |
| Deterministic verification before finishing | no | no | **yes** |
| Dedicated clarification step | no | no (can call `ask_user`) | **yes** |
| LLM calls per episode (main split, mean) | 2.0 | 4.6 | 5.2 |

Ablations used in the paper: *w/o verifier* (④ → ⑥ directly), *w/o dedicated clarify node* (skip ③; `ask_user` still available in ④), *w/o any clarification* (no ③ and no `ask_user`).
