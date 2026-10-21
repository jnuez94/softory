# Smells and fixes

| Smell | Looks like | Refactoring |
| --- | --- | --- |
| Long function | More than about 30 lines, several comments marking sections | Extract function per section, and name it after the comment |
| Deep nesting | `if` inside `for` inside `if` | Guard clauses with early returns. Extract the loop body. |
| Long parameter list | More than 4 parameters, or boolean flags | Introduce a parameter object. Split the function per flag value. |
| Flag argument | `render(user, true)` | Two functions: `renderCompact`, `renderFull` |
| Duplicated logic | Same 5+ lines in 3 places | Extract function (rule of three) |
| Shotgun surgery | One change needs edits in many modules | Move the behavior to the module that owns the data |
| Feature envy | A method mostly uses another object's fields | Move the method to that object |
| Primitive obsession | Strings for emails, money as float | Small value types: `Email`, `Money` (in integer cents) |
| God object | One class or module does everything | Split by responsibility, one reason to change each |
| Hidden I/O in logic | `datetime.now()` or an HTTP call inside a calculation | Pass the value in, and keep the calculation pure |
| Temporal coupling | `init()` must be called before `run()` | Constructor establishes validity, or a builder |
| Speculative generality | Interfaces with one implementation, unused hooks | Inline them. Add the abstraction when the second case arrives. |
| Dead code | Unreferenced functions, commented-out blocks | Delete it |
| Comment explaining confusing code | `// this works because...` | Rename and restructure until the comment is unnecessary, and keep only the *why* |
| Swallowed error | `except: pass`, an empty `catch` | Handle it, or propagate it with context |
| Magic number | `if retries > 3` | Named constant with its reason |

Source: Martin Fowler, *Refactoring* (2nd ed.), and the [Refactoring catalog](https://refactoring.com/catalog/).
