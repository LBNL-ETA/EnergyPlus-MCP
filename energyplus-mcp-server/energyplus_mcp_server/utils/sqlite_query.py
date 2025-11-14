"""
SQLite Query Manager for EnergyPlus Output Database

This module provides utilities for querying EnergyPlus SQLite output databases.
The SQLite database contains comprehensive simulation results including:
- Time-series data (ReportData, ReportDataDictionary, Time)
- Tabular reports (TabularData, Strings, etc.)
- Metadata (Zones, Surfaces, NominalLighting, etc.)

Schema Overview:
- ReportDataDictionary: Metadata for all output variables/meters
- ReportData: Time-series values linked to dictionary and time
- Time: Timestamp information for each data point
- TabularData: Summary reports and tables
"""

import sqlite3
import logging
from typing import Any, Dict, List, Optional, Literal, Tuple
from pathlib import Path
import pandas as pd

logger = logging.getLogger(__name__)


class SQLiteQueryManager:
    """Manager for querying EnergyPlus SQLite output databases."""

    def __init__(self, db_path: str):
        """Initialize the query manager.

        Args:
            db_path: Path to the SQLite database file

        Raises:
            FileNotFoundError: If database file doesn't exist
            sqlite3.DatabaseError: If file is not a valid SQLite database
        """
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database file not found: {db_path}")

        # Test connection
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.close()
        except sqlite3.DatabaseError as e:
            raise sqlite3.DatabaseError(f"Invalid SQLite database: {e}")

        logger.info(f"SQLiteQueryManager initialized for {db_path}")

    def _get_connection(self) -> sqlite3.Connection:
        """Get a connection to the database."""
        return sqlite3.connect(str(self.db_path))

    def list_available_variables(
        self,
        frequency: Optional[str] = None,
        is_meter: Optional[bool] = None,
        name_filter: Optional[str] = None
    ) -> pd.DataFrame:
        """List all available output variables/meters with metadata.

        Args:
            frequency: Filter by reporting frequency (e.g., 'Hourly', 'Zone Timestep')
            is_meter: Filter by type - True for meters, False for variables, None for both
            name_filter: SQL LIKE pattern for filtering variable names (e.g., '%Temperature%')

        Returns:
            DataFrame with columns:
                - ReportDataDictionaryIndex: Unique ID
                - IsMeter: 1 for meters, 0 for variables
                - Type: Variable or meter type
                - IndexGroup: Grouping information
                - TimestepType: Frequency of reporting
                - KeyValue: Zone, surface, or system name
                - Name: Variable/meter name
                - ReportingFrequency: How often reported
                - ScheduleName: Associated schedule if any
                - Units: Engineering units
        """
        query = """
        SELECT
            ReportDataDictionaryIndex,
            IsMeter,
            Type,
            IndexGroup,
            TimestepType,
            KeyValue,
            Name,
            ReportingFrequency,
            ScheduleName,
            Units
        FROM ReportDataDictionary
        WHERE 1=1
        """
        params = []

        if frequency is not None:
            query += " AND ReportingFrequency = ?"
            params.append(frequency)

        if is_meter is not None:
            query += " AND IsMeter = ?"
            params.append(1 if is_meter else 0)

        if name_filter is not None:
            query += " AND Name LIKE ?"
            params.append(name_filter)

        query += " ORDER BY Name, KeyValue"

        conn = self._get_connection()
        try:
            df = pd.read_sql_query(query, conn, params=params)
            logger.info(f"Found {len(df)} variables/meters matching criteria")
            return df
        finally:
            conn.close()

    def get_reporting_frequencies(self) -> List[str]:
        """Get list of all reporting frequencies available in the database.

        Returns:
            List of unique reporting frequency strings
        """
        query = "SELECT DISTINCT ReportingFrequency FROM ReportDataDictionary ORDER BY ReportingFrequency"

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query)
            frequencies = [row[0] for row in cursor.fetchall()]
            return frequencies
        finally:
            conn.close()

    def get_variable_metadata(self, variable_id: int) -> Optional[Dict[str, Any]]:
        """Get metadata for a specific variable/meter by its ID.

        Args:
            variable_id: ReportDataDictionaryIndex

        Returns:
            Dictionary with metadata or None if not found
        """
        query = """
        SELECT
            ReportDataDictionaryIndex,
            IsMeter,
            Type,
            IndexGroup,
            TimestepType,
            KeyValue,
            Name,
            ReportingFrequency,
            ScheduleName,
            Units
        FROM ReportDataDictionary
        WHERE ReportDataDictionaryIndex = ?
        """

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, (variable_id,))
            row = cursor.fetchone()

            if row is None:
                return None

            return {
                'ReportDataDictionaryIndex': row[0],
                'IsMeter': bool(row[1]),
                'Type': row[2],
                'IndexGroup': row[3],
                'TimestepType': row[4],
                'KeyValue': row[5],
                'Name': row[6],
                'ReportingFrequency': row[7],
                'ScheduleName': row[8],
                'Units': row[9]
            }
        finally:
            conn.close()

    def find_variable_id(self, variable_name: str, key_value: Optional[str] = None) -> Optional[int]:
        """Find the ReportDataDictionaryIndex for a variable by name.

        Args:
            variable_name: Name of the variable/meter
            key_value: Optional key value (zone, surface, etc.) for disambiguation

        Returns:
            ReportDataDictionaryIndex or None if not found/ambiguous
        """
        query = "SELECT ReportDataDictionaryIndex FROM ReportDataDictionary WHERE Name = ?"
        params = [variable_name]

        if key_value is not None:
            query += " AND KeyValue = ?"
            params.append(key_value)

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()

            if len(rows) == 0:
                logger.warning(f"No variable found with name: {variable_name}")
                return None
            elif len(rows) > 1:
                logger.warning(f"Multiple variables found with name: {variable_name}. Specify key_value to disambiguate.")
                return None

            return rows[0][0]
        finally:
            conn.close()

    def get_time_series(
        self,
        variable_id: Optional[int] = None,
        variable_name: Optional[str] = None,
        key_value: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """Get time-series data for a specific variable/meter.

        Args:
            variable_id: ReportDataDictionaryIndex (preferred if known)
            variable_name: Variable name (alternative to variable_id)
            key_value: Key value for disambiguation when using variable_name
            start_date: Start date filter (format: 'YYYY-MM-DD')
            end_date: End date filter (format: 'YYYY-MM-DD')

        Returns:
            DataFrame with columns:
                - TimeIndex: Time record ID
                - ReportDataDictionaryIndex: Variable ID
                - Value: Reported value
                - Month, Day, Hour, Minute: Timestamp components
                - DayType: Weekday/Weekend/Holiday
                - SimulationDays: Cumulative simulation days

        Raises:
            ValueError: If neither variable_id nor variable_name provided
        """
        # Resolve variable_id if name provided
        if variable_id is None:
            if variable_name is None:
                raise ValueError("Must provide either variable_id or variable_name")
            variable_id = self.find_variable_id(variable_name, key_value)
            if variable_id is None:
                raise ValueError(f"Could not find variable: {variable_name}")

        query = """
        SELECT
            rd.TimeIndex,
            rd.ReportDataDictionaryIndex,
            rd.Value,
            t.Month,
            t.Day,
            t.Hour,
            t.Minute,
            t.DayType,
            t.SimulationDays
        FROM ReportData rd
        JOIN Time t ON rd.TimeIndex = t.TimeIndex
        WHERE rd.ReportDataDictionaryIndex = ?
        """
        params = [variable_id]

        if start_date is not None:
            # Note: This is a simple filter; EnergyPlus dates may need more sophisticated handling
            query += " AND (t.Month || '-' || t.Day) >= ?"
            # Convert YYYY-MM-DD to MM-DD
            params.append('-'.join(start_date.split('-')[1:]))

        if end_date is not None:
            query += " AND (t.Month || '-' || t.Day) <= ?"
            params.append('-'.join(end_date.split('-')[1:]))

        query += " ORDER BY rd.TimeIndex"

        conn = self._get_connection()
        try:
            df = pd.read_sql_query(query, conn, params=params)
            logger.info(f"Retrieved {len(df)} time-series records for variable_id {variable_id}")
            return df
        finally:
            conn.close()

    def get_multiple_time_series(
        self,
        variable_ids: List[int],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """Get time-series data for multiple variables in a single query.

        Args:
            variable_ids: List of ReportDataDictionaryIndex values
            start_date: Start date filter (format: 'YYYY-MM-DD')
            end_date: End date filter (format: 'YYYY-MM-DD')

        Returns:
            DataFrame in wide format with TimeIndex as index and variable_ids as columns
        """
        if not variable_ids:
            return pd.DataFrame()

        # Build query with placeholders
        placeholders = ','.join('?' * len(variable_ids))
        query = f"""
        SELECT
            rd.TimeIndex,
            rd.ReportDataDictionaryIndex,
            rd.Value,
            t.Month,
            t.Day,
            t.Hour,
            t.Minute,
            t.SimulationDays
        FROM ReportData rd
        JOIN Time t ON rd.TimeIndex = t.TimeIndex
        WHERE rd.ReportDataDictionaryIndex IN ({placeholders})
        """
        params = variable_ids.copy()

        if start_date is not None:
            query += " AND (t.Month || '-' || t.Day) >= ?"
            params.append('-'.join(start_date.split('-')[1:]))

        if end_date is not None:
            query += " AND (t.Month || '-' || t.Day) <= ?"
            params.append('-'.join(end_date.split('-')[1:]))

        query += " ORDER BY rd.TimeIndex, rd.ReportDataDictionaryIndex"

        conn = self._get_connection()
        try:
            df = pd.read_sql_query(query, conn, params=params)

            # Pivot to wide format
            df_wide = df.pivot(
                index='TimeIndex',
                columns='ReportDataDictionaryIndex',
                values='Value'
            )

            # Add time columns back
            time_cols = df[['TimeIndex', 'Month', 'Day', 'Hour', 'Minute', 'SimulationDays']].drop_duplicates()
            df_wide = df_wide.merge(time_cols, left_index=True, right_on='TimeIndex')
            df_wide = df_wide.set_index('TimeIndex')

            logger.info(f"Retrieved time-series data for {len(variable_ids)} variables, {len(df_wide)} timesteps")
            return df_wide
        finally:
            conn.close()

    def get_zone_metadata(self) -> pd.DataFrame:
        """Get metadata about all zones in the model.

        Returns:
            DataFrame with zone information (ZoneIndex, ZoneName, RelNorth, etc.)
        """
        query = "SELECT * FROM Zones ORDER BY ZoneIndex"

        conn = self._get_connection()
        try:
            df = pd.read_sql_query(query, conn)
            return df
        finally:
            conn.close()

    def get_tabular_reports(self) -> List[str]:
        """Get list of all available tabular report names.

        Returns:
            List of unique report names
        """
        query = """
        SELECT DISTINCT s.Value as ReportName
        FROM TabularData td
        JOIN Strings s ON td.ReportNameIndex = s.StringIndex
        ORDER BY s.Value
        """

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query)
            reports = [row[0] for row in cursor.fetchall()]
            return reports
        finally:
            conn.close()

    def get_tabular_report_data(self, report_name: Optional[str] = None) -> pd.DataFrame:
        """Get tabular report data.

        Args:
            report_name: Specific report name to retrieve, or None for all reports

        Returns:
            DataFrame with tabular data including ReportName, TableName, RowName, ColumnName, Value
        """
        query = """
        SELECT
            rn.Value as ReportName,
            rt.Value as ReportForString,
            tn.Value as TableName,
            rw.Value as RowName,
            cn.Value as ColumnName,
            un.Value as Units,
            td.Value
        FROM TabularData td
        JOIN Strings rn ON td.ReportNameIndex = rn.StringIndex
        JOIN Strings rt ON td.ReportForStringIndex = rt.StringIndex
        JOIN Strings tn ON td.TableNameIndex = tn.StringIndex
        JOIN Strings rw ON td.RowNameIndex = rw.StringIndex
        JOIN Strings cn ON td.ColumnNameIndex = cn.StringIndex
        JOIN Strings un ON td.UnitsIndex = un.StringIndex
        """
        params = []

        if report_name is not None:
            query += " WHERE rn.Value = ?"
            params.append(report_name)

        query += " ORDER BY rn.Value, tn.Value, td.RowId, td.ColumnId"

        conn = self._get_connection()
        try:
            df = pd.read_sql_query(query, conn, params=params)
            logger.info(f"Retrieved {len(df)} tabular data records")
            return df
        finally:
            conn.close()

    def get_database_summary(self) -> Dict[str, Any]:
        """Get summary statistics about the database.

        Returns:
            Dictionary with counts of variables, meters, time steps, zones, etc.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Count variables and meters
            cursor.execute("SELECT COUNT(*) FROM ReportDataDictionary WHERE IsMeter = 0")
            var_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM ReportDataDictionary WHERE IsMeter = 1")
            meter_count = cursor.fetchone()[0]

            # Count time steps
            cursor.execute("SELECT COUNT(*) FROM Time")
            timestep_count = cursor.fetchone()[0]

            # Count data records
            cursor.execute("SELECT COUNT(*) FROM ReportData")
            data_count = cursor.fetchone()[0]

            # Count zones
            cursor.execute("SELECT COUNT(*) FROM Zones")
            zone_count = cursor.fetchone()[0]

            # Get reporting frequencies
            cursor.execute("SELECT DISTINCT ReportingFrequency FROM ReportDataDictionary")
            frequencies = [row[0] for row in cursor.fetchall()]

            return {
                'variables_count': var_count,
                'meters_count': meter_count,
                'total_outputs': var_count + meter_count,
                'timesteps_count': timestep_count,
                'data_records_count': data_count,
                'zones_count': zone_count,
                'reporting_frequencies': frequencies
            }
        finally:
            conn.close()
