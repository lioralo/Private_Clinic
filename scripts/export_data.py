#!/usr/bin/env python3
"""
Export all data from clinic.db to JSON format
This script creates a comprehensive backup of all clinic data
"""

import sqlite3
import json
import os
from datetime import datetime, date
from decimal import Decimal
from pathlib import Path

def json_serializer(obj):
    """Custom JSON serializer for non-standard types"""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Type {type(obj)} not serializable")

def export_database(db_path, output_file):
    """Export entire database to JSON"""
    if not os.path.exists(db_path):
        print(f"Error: Database file {db_path} not found")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence' ORDER BY name;")
        tables = [t[0] for t in cursor.fetchall()]
        
        export_data = {
            'export_metadata': {
                'exported_at': datetime.now().isoformat(),
                'source_database': db_path,
                'total_tables': len(tables),
            },
            'data': {}
        }
        
        total_rows = 0
        
        # Export each table
        for table in tables:
            cursor.execute(f"SELECT * FROM {table}")
            rows = cursor.fetchall()
            
            # Convert rows to dictionaries
            table_data = []
            for row in rows:
                table_data.append(dict(row))
            
            export_data['data'][table] = {
                'row_count': len(rows),
                'records': table_data
            }
            
            total_rows += len(rows)
            print(f"✓ Exported {table}: {len(rows)} rows")
        
        export_data['export_metadata']['total_rows'] = total_rows
        
        # Write to file
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, default=json_serializer, indent=2, ensure_ascii=False)
        
        print(f"\n✓ Successfully exported {total_rows} rows from {len(tables)} tables")
        print(f"✓ Saved to {output_file}")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"Error exporting database: {e}")
        return False

def verify_export(json_file):
    """Verify the exported JSON file"""
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print(f"\n=== Export Verification ===")
        print(f"Export Date: {data['export_metadata']['exported_at']}")
        print(f"Total Tables: {data['export_metadata']['total_tables']}")
        print(f"Total Rows: {data['export_metadata']['total_rows']}")
        print(f"\nTable Summary:")
        
        for table in sorted(data['data'].keys()):
            count = data['data'][table]['row_count']
            print(f"  {table}: {count} rows")
        
        return True
    except Exception as e:
        print(f"Error verifying export: {e}")
        return False

def main():
    db_path = 'clinic.db'
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file = f'clinic_data_backup_{timestamp}.json'

    print(f"Exporting database to {output_file}...")
    print("=" * 50)

    if export_database(db_path, output_file):
        verify_export(output_file)
    else:
        print("Export failed")
        exit(1)


if __name__ == '__main__':
    main()
