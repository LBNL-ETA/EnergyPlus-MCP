"""
Error parser utility module for EnergyPlus MCP Server.
Handles parsing and analysis of EnergyPlus error files (.err).

Structure of an ``eplusout.err`` file (EnergyPlus 26.1):

* ``Program Version,...`` on the first line.
* Messages: ``** Warning **``, ``** Severe  **``, ``**  Fatal  **``, each
  followed by zero or more ``**   ~~~   **`` continuation (context) lines.
* Progress and summary lines prefixed with ``*************``.
* An optional ``===== Recurring Error Summary =====`` block listing messages
  that repeated, each with "This error occurred N total times" and, for some,
  ``Max=... Min=...``.  A message that occurred millions of times appears
  only once or twice in full, so these counts are the real size of the issue.
* An optional ``===== Final Error Summary =====`` block naming categories.
* The phase lines ``During Warmup: a Warning; b Severe Errors.`` and
  ``During Sizing: ...``, which are subsets of the final totals, and then
  ``EnergyPlus Completed Successfully-- W Warning; S Severe Errors`` or
  ``EnergyPlus Terminated--Fatal Error Detected. W Warning; S Severe Errors``.
  A file with neither line comes from a run that crashed or is still running.
"""

import difflib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Category tags for messages, checked in order against the message and its
# context lines.  Patterns come from real EnergyPlus 26.1 output.
CATEGORY_PATTERNS = (
    ("version", re.compile(r"^Version: in IDF=")),
    ("input_schema", re.compile(r"^<root>\[")),
    ("duplicate_name", re.compile(r"Duplicate name found")),
    ("weather", re.compile(r"weather file", re.I)),
    ("sizing", re.compile(r"no design environments|Sizing for .* has been requested", re.I)),
    ("node_connection", re.compile(r"Node Connection Error|Node Types are still UNDEFINED|not on any Branch", re.I)),
    ("setpoint", re.compile(r"setpoint not found|Missing temperature setpoint|No Setpoint Manager", re.I)),
    ("missing_reference", re.compile(r"item not found|was not found|not found in", re.I)),
    ("geometry", re.compile(r"GetVertices|upside down|Zone volume|non-?planar|non-?convex", re.I)),
    ("psychrometrics", re.compile(r"\(Psy[A-Za-z]+\)")),
    ("termination", re.compile(
        r"terminat|correct either the branch nodes|Errors occurred on processing input file", re.I)),
)

_ROOT_REF = re.compile(r"^<root>\[([^\]]+)\]\[([^\]]*)\](?:\[([^\]]+)\])?")
_TYPE_NAME_REF = re.compile(r"type=([A-Za-z][A-Za-z0-9:]*) Name=\"([^\"]+)\"")
_QUOTED_REF = re.compile(r"([A-Za-z][A-Za-z0-9:]*)=\"([^\"]+)\"")
_OBJECT_NAME_REF = re.compile(r"for object ([A-Za-z][A-Za-z0-9:]*), name=(.+)$")
_TYPE_EQUALS_REF = re.compile(r"^[A-Za-z]+: ([A-Za-z][A-Za-z0-9:]*) = (.+)$")
_TOTALS = re.compile(r"(\d+)\s+Warning;\s+(\d+)\s+Severe Errors")


@dataclass
class EnergyPlusError:
    """Represents a single error from EnergyPlus output"""
    severity: str  # Warning, Severe, Fatal
    message: str
    context: List[str] = field(default_factory=list)
    line_number: int = 0
    object_reference: Optional[str] = None
    field_name: Optional[str] = None
    category: Optional[str] = None
    occurrences: Optional[int] = None


class ErrorParser:
    """Parser for EnergyPlus error files"""

    def __init__(self):
        self.error_patterns = {
            'warning': re.compile(r'\*\*\s+Warning\s+\*\*\s+(.+)'),
            'severe': re.compile(r'\*\*\s+Severe\s+\*\*\s+(.+)'),
            'fatal': re.compile(r'\*\*\s+Fatal\s+\*\*\s+(.+)'),
            'context': re.compile(r'\*\*\s+~~~\s+\*\*\s*(.+)'),
            'summary': re.compile(r'\*{5,}(.*)'),
            'recurring_message': re.compile(r'\*{5,}\s+\*\*\s+(Warning|Severe)\s+\*\*\s+(.+)'),
            'recurring_context': re.compile(r'\*{5,}\s+\*\*\s+~~~\s+\*\*\s+(.+)'),
        }

    def parse_error_file(self, err_path: str) -> Dict[str, Any]:
        """Parse an EnergyPlus .err file and return structured error data.

        ``counts`` counts the messages printed in full; ``summary.totals``
        is EnergyPlus's own total, which includes every repetition.
        """
        err_file = Path(err_path)

        if not err_file.exists():
            return {
                "file_path": str(err_path),
                "exists": False,
                "error": "Error file not found"
            }

        errors: Dict[str, List[EnergyPlusError]] = {
            "warnings": [],
            "severe_errors": [],
            "fatal_errors": []
        }
        recurring: List[Dict[str, Any]] = []
        summary_info: List[str] = []
        categories: List[str] = []
        current_error: Optional[EnergyPlusError] = None
        version_info = None
        block = None  # None | "recurring" | "final"

        try:
            with open(err_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()

            for line_num, line in enumerate(lines, 1):
                # EnergyPlus indents every message ("   ** Severe  ** ..."),
                # and the patterns below match from the start of the line.
                line = line.strip()
                if not line:
                    continue

                if line_num == 1 and line.startswith("Program Version"):
                    version_info = line
                    continue

                if line.startswith("*****"):
                    if current_error:
                        self._store_error(errors, current_error)
                        current_error = None
                    if "===== Recurring Error Summary =====" in line:
                        block = "recurring"
                        continue
                    if "===== Final Error Summary =====" in line:
                        block = "final"
                        continue
                    if "Error Summary." in line or "Completed Successfully" in line or "Terminated--" in line:
                        block = None
                    if block == "recurring":
                        self._parse_recurring_line(line, recurring)
                        continue
                    if block == "final":
                        text = line.lstrip("*").strip()
                        if text and not text.startswith(("..", "The following")):
                            categories.append(text)
                        continue
                    summary_info.append(line)
                    continue

                matched = False
                for key, severity in (("warning", "Warning"), ("severe", "Severe"), ("fatal", "Fatal")):
                    match = self.error_patterns[key].match(line)
                    if match:
                        if current_error:
                            self._store_error(errors, current_error)
                        current_error = EnergyPlusError(
                            severity=severity,
                            message=match.group(1).strip(),
                            line_number=line_num,
                        )
                        matched = True
                        break
                if matched:
                    continue

                context_match = self.error_patterns['context'].match(line)
                if context_match and current_error:
                    current_error.context.append(context_match.group(1).strip())

            if current_error:
                self._store_error(errors, current_error)

            all_errors = errors["warnings"] + errors["severe_errors"] + errors["fatal_errors"]
            for error in all_errors:
                self._classify(error)
            self._attach_occurrences(all_errors, recurring)

            stats = self._parse_summary(summary_info)
            if categories:
                stats["error_categories"] = categories

            return {
                "file_path": str(err_path),
                "exists": True,
                "version": version_info,
                "warnings": [self._error_to_dict(e) for e in errors["warnings"]],
                "severe_errors": [self._error_to_dict(e) for e in errors["severe_errors"]],
                "fatal_errors": [self._error_to_dict(e) for e in errors["fatal_errors"]],
                "recurring": recurring,
                "counts": {
                    "warnings": len(errors["warnings"]),
                    "severe": len(errors["severe_errors"]),
                    "fatal": len(errors["fatal_errors"]),
                    "recurring": len(recurring),
                },
                "summary": stats
            }

        except Exception as e:
            logger.error(f"Error parsing file {err_path}: {e}")
            return {
                "file_path": str(err_path),
                "exists": True,
                "error": f"Failed to parse: {str(e)}"
            }

    # ------------------------------------------------------------------
    def _parse_recurring_line(self, line: str, recurring: List[Dict[str, Any]]) -> None:
        message = self.error_patterns['recurring_message'].match(line)
        if message:
            recurring.append({
                "severity": message.group(1),
                "message": message.group(2).strip(),
                "occurrences": None,
                "during_warmup": None,
                "during_sizing": None,
            })
            return
        context = self.error_patterns['recurring_context'].match(line)
        if not context or not recurring:
            return
        text = context.group(1).strip()
        entry = recurring[-1]
        total = re.search(r"This error occurred (\d+) total times", text)
        if total:
            entry["occurrences"] = int(total.group(1))
            return
        warmup = re.search(r"during Warmup (\d+) times", text)
        if warmup:
            entry["during_warmup"] = int(warmup.group(1))
            return
        sizing = re.search(r"during Sizing (\d+) times", text)
        if sizing:
            entry["during_sizing"] = int(sizing.group(1))
            return
        if text.startswith("Max=") or " Min=" in text or text.startswith("Min="):
            entry["range"] = text
        else:
            entry.setdefault("context", []).append(text)

    @staticmethod
    def _norm(message: str) -> str:
        text = message.lower().replace("error continues...", "")
        text = re.sub(r"\d+|\bmax\b", "#", text)
        return " ".join(text.split())

    def _attach_occurrences(self, all_errors: List[EnergyPlusError], recurring: List[Dict[str, Any]]) -> None:
        """Give each printed message the repeat count from the recurring summary."""
        for entry in recurring:
            if entry.get("occurrences") is None:
                continue
            target = self._norm(entry["message"])
            for error in all_errors:
                if error.severity != entry["severity"] or error.occurrences is not None:
                    continue
                candidate = self._norm(error.message)
                # The summary may drop the routine prefix ("CalcEquipmentFlowRates: ")
                # or word the message slightly differently.
                if (
                    candidate == target
                    or (len(target) >= 30 and target[:40] in candidate)
                    or difflib.SequenceMatcher(None, candidate, target).ratio() >= 0.85
                ):
                    error.occurrences = entry["occurrences"]
                    break

    def _classify(self, error: EnergyPlusError) -> None:
        text = " ".join([error.message] + error.context)
        for category, pattern in CATEGORY_PATTERNS:
            if pattern.search(error.message) or (category != "termination" and pattern.search(text)):
                error.category = category
                break
        root = _ROOT_REF.match(error.message)
        if root:
            error.object_reference = f"{root.group(1)}={root.group(2)}"
            error.field_name = root.group(3)
            return
        for pattern in (_TYPE_NAME_REF, _QUOTED_REF, _OBJECT_NAME_REF, _TYPE_EQUALS_REF):
            match = pattern.search(error.message)
            if match:
                error.object_reference = f"{match.group(1)}={match.group(2).strip()}"
                return

    def _store_error(self, errors: Dict, error: EnergyPlusError):
        """Store error in appropriate category"""
        if error.severity == "Warning":
            errors["warnings"].append(error)
        elif error.severity == "Severe":
            errors["severe_errors"].append(error)
        elif error.severity == "Fatal":
            errors["fatal_errors"].append(error)

    def _error_to_dict(self, error: EnergyPlusError) -> Dict[str, Any]:
        """Convert error object to dictionary"""
        result = {
            "severity": error.severity,
            "message": error.message,
            "context": error.context,
            "line_number": error.line_number,
            "object_reference": error.object_reference,
            "category": error.category,
        }
        if error.field_name:
            result["field"] = error.field_name
        if error.occurrences is not None:
            result["occurrences"] = error.occurrences
        return result

    def _parse_summary(self, summary_lines: List[str]) -> Dict[str, Any]:
        """Parse run status, EnergyPlus's totals, and phase subtotals."""
        stats: Dict[str, Any] = {"status": "incomplete"}

        for line in summary_lines:
            totals = _TOTALS.search(line)
            if "During Warmup:" in line and totals:
                stats.setdefault("phases", {})["warmup"] = {
                    "warnings": int(totals.group(1)), "severe": int(totals.group(2))}
            elif "During Sizing:" in line and totals:
                stats.setdefault("phases", {})["sizing"] = {
                    "warnings": int(totals.group(1)), "severe": int(totals.group(2))}
            elif "Completed Successfully" in line and totals:
                stats["status"] = "completed"
                stats["totals"] = {"warnings": int(totals.group(1)), "severe": int(totals.group(2))}
            elif "Terminated--Fatal Error" in line:
                stats["status"] = "terminated"
                stats["terminated"] = True
                if totals:
                    stats["totals"] = {"warnings": int(totals.group(1)), "severe": int(totals.group(2))}
            elif "before simulations began" in line:
                stats["stopped_before_simulation"] = True
            match = re.search(r'Elapsed Time=(.+)', line)
            if match:
                stats["elapsed_time"] = match.group(1).strip()

        if stats["status"] == "incomplete":
            stats["note"] = (
                "No final summary line: EnergyPlus crashed or is still running. "
                "Treat the last Severe message as the lead."
            )
        return stats

    def analyze_root_cause(self, parsed_errors: Dict[str, Any]) -> Dict[str, Any]:
        """Identify the message to fix first and summarize patterns.

        The first Severe in file order is the lead: Fatal messages usually
        only announce termination ("Preceding condition(s) cause
        termination"), and later Severe messages are often consequences.
        """
        analysis: Dict[str, Any] = {
            "primary_issue": None,
            "primary_category": None,
            "primary_object": None,
            "patterns": [],
            "affected_objects": set(),
        }

        severe = sorted(parsed_errors.get("severe_errors", []), key=lambda e: e["line_number"])
        fatal = sorted(parsed_errors.get("fatal_errors", []), key=lambda e: e["line_number"])
        lead = severe[0] if severe else (fatal[0] if fatal else None)
        if lead:
            analysis["primary_issue"] = lead["message"]
            analysis["primary_category"] = lead.get("category")
            analysis["primary_object"] = lead.get("object_reference")
            analysis["primary_context"] = lead.get("context", [])
            analysis["primary_line"] = lead["line_number"]

        all_errors = severe + fatal
        by_category: Dict[str, int] = {}
        for error in all_errors:
            if error.get("category") and error["category"] != "termination":
                by_category[error["category"]] = by_category.get(error["category"], 0) + 1
            if error.get("object_reference"):
                analysis["affected_objects"].add(error["object_reference"])
        analysis["patterns"] = [
            {"category": category, "count": count} for category, count in sorted(by_category.items())
        ]

        summary = parsed_errors.get("summary", {})
        if summary.get("status") == "completed" and severe:
            analysis["completed_with_severe"] = True
        if summary.get("status") == "incomplete":
            analysis["incomplete_run"] = True
        noisy = [
            r for r in parsed_errors.get("recurring", [])
            if (r.get("occurrences") or 0) >= 100
        ]
        if noisy:
            analysis["frequent_recurring"] = sorted(
                ({"message": r["message"], "occurrences": r["occurrences"]} for r in noisy),
                key=lambda r: -r["occurrences"],
            )

        analysis["affected_objects"] = sorted(analysis["affected_objects"])
        return analysis
