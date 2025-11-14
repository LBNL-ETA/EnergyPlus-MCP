from typing import Any, Optional, Literal, List
import json


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    @mcp.tool()
    async def post_processing(
        action: Literal["interactive_plot", "parse_errors", "list_output_files", "query_sql_variables", "query_sql_timeseries", "query_sql_tabular", "create_sql_plot", "capabilities"],
        output_directory: Optional[str] = None,
        err_file_path: Optional[str] = None,
        idf_name: Optional[str] = None,
        file_type: Literal["auto", "meter", "variable"] = "auto",
        custom_title: Optional[str] = None,
        sql_path: Optional[str] = None,
        frequency: Optional[str] = None,
        is_meter: Optional[bool] = None,
        name_filter: Optional[str] = None,
        include_summary: bool = True,
        variable_name: Optional[str] = None,
        variable_id: Optional[int] = None,
        key_value: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        output_format: str = "json",
        report_name: Optional[str] = None,
        list_reports: bool = False,
        variable_ids: Optional[List[int]] = None,
        variable_names: Optional[List[str]] = None,
        output_path: Optional[str] = None,
    ) -> str:
        """Post-processing tools for analyzing EnergyPlus simulation outputs.

        Actions:
        - list_output_files: List and analyze all output files in a directory
        - interactive_plot: Create interactive HTML plots from CSV output data
        - parse_errors: Parse and analyze error files
        - query_sql_variables: Query available variables/meters in SQLite database
        - query_sql_timeseries: Query time-series data from SQLite database
        - query_sql_tabular: Query tabular reports from SQLite database
        - create_sql_plot: Create interactive plot from SQLite time-series data
        - capabilities: Show available actions and parameters
        """
        if action == "capabilities":
            return json.dumps({
                "tool": "post_processing",
                "actions": [
                    {"name": "list_output_files", "required": ["output_directory"], "optional": ["idf_name"], "description": "List and analyze all simulation output files with recommendations"},
                    {"name": "interactive_plot", "required": ["output_directory"], "optional": ["idf_name", "file_type", "custom_title"], "description": "Create interactive HTML plot from CSV data"},
                    {"name": "parse_errors", "required": ["err_file_path"], "optional": [], "description": "Parse and analyze error/warning file"},
                    {"name": "query_sql_variables", "required": ["sql_path"], "optional": ["frequency", "is_meter", "name_filter", "include_summary"], "description": "Query available variables/meters in SQLite database with filtering and summary"},
                    {"name": "query_sql_timeseries", "required": ["sql_path"], "optional": ["variable_name", "variable_id", "key_value", "start_date", "end_date", "output_format"], "description": "Query time-series data from SQLite database"},
                    {"name": "query_sql_tabular", "required": ["sql_path"], "optional": ["report_name", "list_reports"], "description": "Query tabular reports from SQLite database"},
                    {"name": "create_sql_plot", "required": ["sql_path"], "optional": ["variable_ids", "variable_names", "start_date", "end_date", "custom_title", "output_path"], "description": "Create interactive plot from SQLite time-series data"}
                ],
            }, indent=2)
        if action == "list_output_files":
            if not output_directory:
                return "Missing required parameter: output_directory"
            result = ep_manager.list_output_files(output_directory, idf_name)
            return result
        if action == "interactive_plot":
            if not output_directory:
                return "Missing required parameter: output_directory"
            result = ep_manager.create_interactive_plot(output_directory, idf_name, file_type, custom_title)
            return f"Interactive plot created:\n{result}"
        if action == "parse_errors":
            if not err_file_path:
                return "Missing required parameter: err_file_path"
            result = ep_manager.parse_simulation_errors(err_file_path)
            return json.dumps(result, indent=2)
        if action == "query_sql_variables":
            if not sql_path:
                return "Missing required parameter: sql_path"
            result = ep_manager.query_sql_variables(
                sql_path=sql_path,
                frequency=frequency,
                is_meter=is_meter,
                name_filter=name_filter,
                include_summary=include_summary
            )
            return result
        if action == "query_sql_timeseries":
            if not sql_path:
                return "Missing required parameter: sql_path"
            result = ep_manager.query_sql_timeseries(
                sql_path=sql_path,
                variable_name=variable_name,
                variable_id=variable_id,
                key_value=key_value,
                start_date=start_date,
                end_date=end_date,
                output_format=output_format
            )
            return result
        if action == "query_sql_tabular":
            if not sql_path:
                return "Missing required parameter: sql_path"
            result = ep_manager.query_sql_tabular(
                sql_path=sql_path,
                report_name=report_name,
                list_reports=list_reports
            )
            return result
        if action == "create_sql_plot":
            if not sql_path:
                return "Missing required parameter: sql_path"
            result = ep_manager.create_sql_plot(
                sql_path=sql_path,
                variable_ids=variable_ids,
                variable_names=variable_names,
                start_date=start_date,
                end_date=end_date,
                custom_title=custom_title,
                output_path=output_path
            )
            return result
        return f"Unsupported action: {action}"

