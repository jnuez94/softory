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

The recommendations follow one principle: **builders and their reviewers on different models where it matters most.** The engineers build on Claude. Toby reviews security on Codex, and Greg accepts stories on Codex, so the two gates that decide "safe" and "done" get an independent model.

## Where the boundaries live

- [governance/raci.md](../governance/raci.md): who is responsible, accountable, consulted, and informed for each activity.
- [governance/boundaries.md](../governance/boundaries.md): decision, review, and work boundaries, lanes, flex rules, and escalation paths.
- [governance/gates.json](../governance/gates.json): the reviews `softory gate` requires before a unit closes.
- [roster.json](roster.json): the machine-readable roster the installer registers in the coordination database.
