#!/usr/bin/env python3
import sqlite3
import csv
from datetime import datetime
import sys, os
sys.path.insert(0, os.getcwd())

from job_agent.storage.database import Database

def export_to_csv(output_file='jobs_for_notion.csv'):
    """Export jobs from SQLite to CSV for Notion import"""
    db = Database()
    jobs = db.get_all_jobs()
    
    print(f"📊 Exporting {len(jobs)} jobs to CSV...")
    
    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'Name',
            'Company',
            'Role',
            'Location',
            'Score',
            'Decision',
            'Status',
            'Source',
            'Apply URL',
            'Date Found',
            'Notes'
        ])
        
        writer.writeheader()
        
        for job in jobs:
            writer.writerow({
                'Name': f"{job.company} - {job.role}",
                'Company': job.company,
                'Role': job.role,
                'Location': job.location,
                'Score': job.score,
                'Decision': job.decision,
                'Status': job.status or 'Shortlisted',
                'Source': job.source,
                'Apply URL': job.apply_url,
                'Date Found': job.date_found,
                'Notes': job.notes or ''
            })
    
    print(f"✅ Exported to {output_file}")
    print(f"📍 Location: {os.path.abspath(output_file)}")
    return output_file

if __name__ == '__main__':
    export_to_csv()
