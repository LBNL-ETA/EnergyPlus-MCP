---
name: diagnose-simulation-errors
description: >-
  Find and fix the cause of an EnergyPlus run that failed, crashed, or finished
  with Severe errors or suspicious warnings. Use when simulation_manager reports
  success=false, an error summary shows a terminated or incomplete run, a
  completed run still has Severe errors or very frequent recurring warnings, or
  the user asks what an EnergyPlus error or warning means.
---

# Diagnose EnergyPlus simulation errors

EnergyPlus writes every message to the run's `.err` file. The server parses it
into the run status, EnergyPlus's own totals, each message with its context
lines and object, a category, and the repeat counts from the recurring
summary. Fix the first real cause, one at a time, on a copy, and prove the fix
with a new run. `error-catalog.md` in this skill maps each category to real
EnergyPlus 26.1 messages, where to look, and the usual fix.

## Ground rules

- Edit a copy, never the user's source model or library files.
- Fix one cause, rerun, then look again. Later errors are often consequences.
- Never make a model run by deleting the object named in the error, by
  loosening convergence limits or tolerances, or by swapping the weather file
  or location, unless the user asks for that change.
- Run EnergyPlus only when the user asked for it or approved it. A design-day
  run is the cheap check; ask before an annual run.

## Procedure

1. **Get the evidence.**
   - `simulation_manager(action="status", run_id=...)` returns
     `runs[0].error_summary` for a finished run: `err_file`, `run_status`,
     `totals`, `primary_issue`, `primary_category`, `primary_object`, and
     flags (`completed_with_severe`, `incomplete_run`, `frequent_recurring`).
   - `post_processing(action="parse_errors", err_file_path=<err_file>)` returns
     every message with `context`, `object_reference`, `field`, `category`, and
     `occurrences`, plus `recurring` and an `analysis` block. The file is
     `<model name>.err` in the run directory (`eplusout.err` for runs with
     `runs_dir`); `<model name>Sqlite.err` beside it is the SQLite writer's
     log, not the simulation's. `post_processing(action="list_output_files", output_directory=...)`
     lists the run's files.

2. **Read the run status before any message.** `summary.status` is one of:
   - `terminated`: EnergyPlus stopped. With `stopped_before_simulation`, the
     problem is in the input or setup, not the physics.
   - `incomplete`: no final summary line. EnergyPlus crashed (or is still
     running). The last Severe message is the lead; there may be no Fatal line.
   - `completed`: the run finished, but check `totals.severe` and the
     recurring counts. A completed run can carry Severe errors and millions of
     repeated warnings.
   Use `summary.totals`, not `counts`, for the size of the problem: `counts`
   only counts messages printed in full.

3. **Pick the lead error.** It is the first Severe in file order
   (`analysis.primary_issue`), read together with its `context` lines and
   `object_reference`. Fatal lines such as "Preceding condition(s) cause
   termination" only announce the stop. Several Severe messages with the same
   category usually share one cause (one missing setpoint manager can produce
   six). In schema errors (`<root>[Object][Name][field]`) the field is the
   snake_case form of the IDD field name.

4. **Classify and inspect.** Use the lead's `category` to choose the
   inspection; `error-catalog.md` gives the details and real messages.
   `idf_modification(action="find", ...)` is read-only: it looks objects up by
   type (wildcards allowed) or by a name used in any field, case-insensitively.

   | Category | First inspection |
   |---|---|
   | `version` | `model_preflight(action="info")`, then `model_upgrade(action="plan")` |
   | `input_schema` | `reference_docs(action="get_field", object_type=..., field=...)` |
   | `missing_reference`, `duplicate_name` | `idf_modification(action="find", references=<name>)` shows whether the name is defined and who uses it; the owning manager's `inspect` (e.g. `schedule_manager(action="inspect")`, `envelope_manager(action="inspect", focus="constructions")`) for candidates |
   | `node_connection`, `setpoint` | `idf_modification(action="find", references=<node>)` lists every object on the node, including setpoint managers that reach it through a NodeList; `hvac_manager(action="discover")` and `hvac_manager(action="topology", loop_name=...)` for the loop around it |
   | `sizing`, `weather` | `model_preflight(action="readiness", weather_file=...)`, `model_preflight(action="info")` |
   | `geometry` | `geometry_manager(action="extract_and_summary")`, `envelope_manager(action="inspect", focus="surfaces")` |
   | other or none | `reference_docs(action="search", query=...)` with the message's key words |

5. **Confirm what the message means.** Look it up rather than guess:
   - field limits, units, and choices: `reference_docs(action="get_field", ...)`;
   - the object: `reference_docs(action="get_section", object_type=...)`;
   - message levels and the error file: `reference_docs(action="get_section", label="eplusout.err")`;
   - node lists and branch checks: `reference_docs(action="get_section", label="eplusout.bnd")`;
   - physics and convergence warnings: `reference_docs(action="search", query=..., doc="engineering-reference")`.
   Cite the document and section in the report.

6. **Fix one cause on a copy.** If the model is not already a derived copy,
   `file_utils(action="copy", source_path=..., target_path=...)` first. Prefer a
   domain manager operation (run `dry_run` first where offered); use
   `idf_modification(action="modify" | "add" | "delete", ...)` only when none
   fits, and check its `errors`. If the fix needs an object the model lacks
   (a setpoint manager, a design day), follow `get_skill("learn-from-examples")`.
   Record each change: object, field, old value, new value, reason.

7. **Verify.** `model_preflight(action="validate")` is shallow (required
   objects and construction layers). With the user's approval, run
   `simulation_manager(action="run", idf_path=<copy>, annual=False, design_day=True)`
   and compare `run_status`, `totals`, and the lead error with the previous run.
   Repeat from step 3 until no Severe remains, then ask before an annual run.

8. **Review warnings after a clean run.** Sort `recurring` by `occurrences`.
   Decide for each frequent or physics-related warning whether it affects the
   results (see the catalog's warning table). Explain the ones you leave.

9. **Report.** Give the run status, the lead error and its cause with the
   documentation you relied on, each edit, totals before and after, the
   warnings that remain with your judgement, and anything unresolved.

## Pitfalls

- "EnergyPlus Completed Successfully" is not a clean bill: read `totals.severe`
  and the recurring counts.
- A version mismatch is only a Warning; the run continues and later field
  errors may follow. Never upgrade implicitly; plan with `model_upgrade(action="plan")`
  and ask.
- Names in messages are often upper-cased (`SUPPLY FAN 1`). IDF names are not
  case-sensitive; `idf_modification(action="find")` compares them that way.
- A recurring message can be worded differently from its first printed
  instance; trust the `recurring` list for counts.
- With HVACTemplate objects, messages name the expanded objects. Fix the
  template inputs, not the expanded file (`reference_docs(action="get_section", label="hvactemplate-processing")`).
- A crash (`incomplete`) can come from a plain input mistake. In EnergyPlus
  26.1 a `Lights` object naming a missing schedule ends the run with a
  segmentation fault right after the Severe message.
