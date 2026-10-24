# Roles

| Agent ID | Name | Role | Lane | Recommended harness | Profile |
| --- | --- | --- | --- | --- | --- |
| `greg` | Greg | Product Manager | product | Codex | [profile](greg-product-manager.md) |
| `darwin` | Darwin | UX Designer | design | Claude | [profile](darwin-ux-designer.md) |
| `quinn` | Quinn | Principal Engineer | architecture | Claude | [profile](quinn-principal-engineer.md) |
| `jade` | Jade | Senior Software Engineer | frontend | Claude | [profile](jade-senior-software-engineer.md) |
| `gold` | Gold | Senior Software Engineer | backend, infra | Claude | [profile](gold-senior-software-engineer.md) |
| `toby` | Toby | Security Engineer | security | Codex | [profile](toby-security-engineer.md) |
| `owner` | (you) | Project Owner, human | – | – | [roster.json](roster.json) |

Jade and Gold share one craft bar: [Senior Software Engineer](senior-software-engineer.md).

## Model-agnostic by design

The agent ID is the durable identity. The harness and model are recorded per **session**, not in the ID, so any role can run on any harness:

```sh
.agents/softory/bin/softory start quinn                   # uses the recommended harness
.agents/softory/bin/softory start quinn --harness codex   # any harness works
```

The recommendations follow two principles: **each role on the model that scores best at its own kind of work**, and **the gates that decide "safe" and "done" on a different model from the builders**. Darwin, Quinn, Jade, and Gold run on Claude Opus 5.5, which leads the agent-coding and web-design benchmarks. Toby and Greg run on Codex with GPT-6 Astra, which leads the defensive-security benchmarks and long-horizon knowledge work. [docs/models.md](../../docs/models.md) has the benchmarks and prices behind this, and the charter's `models` setting overrides it.

## Where the boundaries live

- [governance/raci.md](../governance/raci.md): who is responsible, accountable, consulted, and informed for each activity.
- [governance/boundaries.md](../governance/boundaries.md): decision, review, and work boundaries, lanes, flex rules, and escalation paths.
- [governance/gates.json](../governance/gates.json): the reviews `softory gate` requires before a unit closes.
- [roster.json](roster.json): the machine-readable roster the installer registers in the coordination database.
