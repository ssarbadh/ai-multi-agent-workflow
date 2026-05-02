#!/usr/bin/env python3
"""Comprehensive test of the RAG system."""
import asyncio
import logging
from app.services.haystack_query import query_pipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_rag_system():
    """Test RAG system with various queries."""
    
    test_queries = [
        # VMware/vSphere queries (should find Google Drive SOPs)
        {
            "query": "How to fix ESXi host not accessible?",
            "expected_source": "google_drive",
            "description": "VMware ESXi troubleshooting"
        },
        {
            "query": "Purple screen of death resolution steps",
            "expected_source": "google_drive", 
            "description": "VMware PSOD troubleshooting"
        },
        # Kubernetes queries (should find K8s training data)
        {
            "query": "Kubernetes pod crash loop back off troubleshooting",
            "expected_source": "k8s_training_data",
            "description": "K8s pod troubleshooting"
        },
        {
            "query": "How to fix persistent volume claim pending?",
            "expected_source": "k8s_training_data",
            "description": "K8s storage troubleshooting"
        }
    ]
    
    print("=== RAG System Comprehensive Test ===")
    print(f"Testing {len(test_queries)} queries across both data sources")
    print()
    
    success_count = 0
    
    for i, t