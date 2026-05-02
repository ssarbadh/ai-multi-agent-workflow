#!/usr/bin/env python3
"""Check Google Drive integration and SOP indexing status."""
import psycopg2
import json
from app.core.config import settings

def check_google_drive_integration():
    print("=== Checking Google Drive Integration ===")
    
    # Check Google Drive configuration
    print(f"Google Drive Folder ID: {settings.google_drive_folder_id}")
    print(f"Google Service Account configured: {'Yes' if settings.google_service_account_json else 'No'}")
    
    # Check database for Google Drive documents
    conn = psycopg2.connect('postgresql://postgres:postgres@localhost:5433/aegisops')
    cur = conn.cursor()
    
    # Check documents by source
    cur.execute("SELECT source, COUNT(*) FROM rag_documents GROUP BY source")
    sources = cur.fetchall()
    print(f"\nDocuments by source:")
    for source, count in sources:
        print(f"  {source}: {count} documents")
    
    # Check for Google Drive documents specifically
    cur.execute("SELECT COUNT(*) FROM rag_documents WHERE source = 'google_drive'")
    gdrive_count = cur.fetchone()[0]
    print(f"\nGoogle Drive documents: {gdrive_count}")
    
    if gdrive_count > 0:
        # Show sample Google Drive documents
        cur.execute("""
            SELECT title, file_path, mime_type, created_at 
            FROM rag_documents 
            WHERE source = 'google_drive' 
            LIMIT 5
        """)
        gdrive_docs = cur.fetchall()
        print(f"\nSample Google Drive documents:")
        for title, file_path, mime_type, created_at in gdrive_docs:
            print(f"  - {title} ({mime_type}) - {file_path}")
    
    # Check for SOPs specifically
    cur.execute("""
        SELECT COUNT(*) FROM rag_documents 
        WHERE (title ILIKE '%sop%' OR content ILIKE '%standard operating procedure%' 
               OR file_path ILIKE '%sop%')
    """)
    sop_count = cur.fetchone()[0]
    print(f"\nSOPs found: {sop_count}")
    
    if sop_count > 0:
        cur.execute("""
            SELECT title, source, file_path 
            FROM rag_documents 
            WHERE (title ILIKE '%sop%' OR content ILIKE '%standard operating procedure%' 
                   OR file_path ILIKE '%sop%')
            LIMIT 10
        """)
        sops = cur.fetchall()
        print(f"Sample SOPs:")
        for title, source, file_path in sops:
            print(f"  - {title} ({source}) - {file_path}")
    
    # Check indexing jobs
    try:
        cur.execute("SELECT COUNT(*) FROM rag_indexing_jobs")
        job_count = cur.fetchone()[0]
        print(f"\nIndexing jobs: {job_count}")
        
        if job_count > 0:
            cur.execute("""
                SELECT job_type, status, total_files, processed_files, started_at 
                FROM rag_indexing_jobs 
                ORDER BY started_at DESC 
                LIMIT 5
            """)
            jobs = cur.fetchall()
            print("Recent indexing jobs:")
            for job_type, status, total_files, processed_files, started_at in jobs:
                print(f"  - {job_type}: {status} ({processed_files}/{total_files}) - {started_at}")
    except Exception as e:
        print(f"No indexing jobs table or error: {e}")
    
    conn.close()

if __name__ == "__main__":
    check_google_drive_integration()