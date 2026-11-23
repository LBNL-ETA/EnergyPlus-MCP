#!/usr/bin/env python3
"""
Test script for SQLite query functionality
"""

import sys
import json
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from energyplus_mcp_server.energyplus_tools import EnergyPlusManager
from energyplus_mcp_server.config import get_config

def test_sqlite_queries():
    """Test SQLite query methods"""

    config = get_config()
    manager = EnergyPlusManager(config)

    sql_path = "outputs/1ZoneUncontrolled_simulation_20251114_060713/1ZoneUncontrolled.sql"

    print("=" * 80)
    print("TEST 1: Query SQL Variables (with summary)")
    print("=" * 80)
    try:
        result = manager.query_sql_variables(
            sql_path=sql_path,
            include_summary=True
        )
        data = json.loads(result)
        print(f"✓ Found {data['variables_count']} variables")
        if 'database_summary' in data:
            summary = data['database_summary']
            print(f"  - Variables: {summary['variables_count']}")
            print(f"  - Meters: {summary['meters_count']}")
            print(f"  - Timesteps: {summary['timesteps_count']}")
            print(f"  - Data records: {summary['data_records_count']}")
            print(f"  - Reporting frequencies: {summary['reporting_frequencies']}")
        print()
    except Exception as e:
        print(f"✗ Error: {e}\n")
        return False

    print("=" * 80)
    print("TEST 2: Query SQL Variables (filter by frequency)")
    print("=" * 80)
    try:
        result = manager.query_sql_variables(
            sql_path=sql_path,
            frequency="Hourly",
            include_summary=False
        )
        data = json.loads(result)
        print(f"✓ Found {data['variables_count']} hourly variables")
        if data['variables_count'] > 0:
            print(f"  Example: {data['variables'][0]['Name']} ({data['variables'][0]['KeyValue']})")
        print()
    except Exception as e:
        print(f"✗ Error: {e}\n")
        return False

    print("=" * 80)
    print("TEST 3: Query SQL Variables (filter by name)")
    print("=" * 80)
    try:
        result = manager.query_sql_variables(
            sql_path=sql_path,
            name_filter="%Temperature%",
            include_summary=False
        )
        data = json.loads(result)
        print(f"✓ Found {data['variables_count']} temperature-related variables")
        if data['variables_count'] > 0:
            for i, var in enumerate(data['variables'][:3]):  # Show first 3
                print(f"  {i+1}. {var['Name']} ({var['KeyValue']}) - {var['Units']}")
        print()
    except Exception as e:
        print(f"✗ Error: {e}\n")
        return False

    print("=" * 80)
    print("TEST 4: Query SQL Tabular (list reports)")
    print("=" * 80)
    try:
        result = manager.query_sql_tabular(
            sql_path=sql_path,
            list_reports=True
        )
        data = json.loads(result)
        print(f"✓ Found {data['reports_count']} tabular reports")
        if data['reports_count'] > 0:
            for i, report in enumerate(data['available_reports'][:5]):  # Show first 5
                print(f"  {i+1}. {report}")
        print()
    except Exception as e:
        print(f"✗ Error: {e}\n")
        return False

    print("=" * 80)
    print("TEST 5: Query SQL Time Series (by variable name)")
    print("=" * 80)
    try:
        # First find a variable
        vars_result = manager.query_sql_variables(
            sql_path=sql_path,
            name_filter="%Zone Mean Air Temperature%",
            include_summary=False
        )
        vars_data = json.loads(vars_result)

        if vars_data['variables_count'] > 0:
            var = vars_data['variables'][0]
            print(f"Testing with variable: {var['Name']} ({var['KeyValue']})")

            # Query time series
            ts_result = manager.query_sql_timeseries(
                sql_path=sql_path,
                variable_id=var['ReportDataDictionaryIndex']
            )
            ts_data = json.loads(ts_result)

            print(f"✓ Retrieved {ts_data['data_points']} data points")
            if ts_data['data_points'] > 0:
                print(f"  First record: {ts_data['time_series'][0]}")
                print(f"  Last record: {ts_data['time_series'][-1]}")
        else:
            print("✗ No temperature variables found to test with")
        print()
    except Exception as e:
        print(f"✗ Error: {e}\n")
        import traceback
        traceback.print_exc()
        return False

    print("=" * 80)
    print("TEST 6: Create SQL Plot")
    print("=" * 80)
    try:
        # Get a few temperature variables
        vars_result = manager.query_sql_variables(
            sql_path=sql_path,
            name_filter="%Temperature%",
            frequency="Hourly",
            include_summary=False
        )
        vars_data = json.loads(vars_result)

        if vars_data['variables_count'] >= 1:
            # Take up to 3 variables for plotting
            var_ids = [var['ReportDataDictionaryIndex'] for var in vars_data['variables'][:3]]
            print(f"Creating plot with {len(var_ids)} variable(s)")

            plot_result = manager.create_sql_plot(
                sql_path=sql_path,
                variable_ids=var_ids,
                custom_title="Test Temperature Plot"
            )
            plot_data = json.loads(plot_result)

            print(f"✓ Plot created: {plot_data['output_file']}")
            print(f"  Variables plotted: {len(plot_data['variables_plotted'])}")
            print(f"  Data points: {plot_data['data_points']}")
        else:
            print("✗ Not enough variables found to create plot")
        print()
    except Exception as e:
        print(f"✗ Error: {e}\n")
        import traceback
        traceback.print_exc()
        return False

    print("=" * 80)
    print("ALL TESTS PASSED!")
    print("=" * 80)
    return True

if __name__ == "__main__":
    success = test_sqlite_queries()
    sys.exit(0 if success else 1)
