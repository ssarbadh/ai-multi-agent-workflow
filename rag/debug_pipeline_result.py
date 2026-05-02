n#!/usr/bin/env python3
"""Debug the actual pipeline result structure."""
import asyncio
import json
from app.services.haystack_store import get_document_store
from app.services.embeddings import embedding_service
from app.core.config import settings
from haystack import Pipeline
from haystack_integrations.components.retrievers.pgvector import PgvectorEmbeddingRetriever
from app.services.custom_reranker import FixedSentenceTransformersSimilarityRanker
from haystack.components.builders import PromptBuilder
from haystack.components.generators import OpenAIGenerator
from haystack.utils import Secret

async def debug_pipeline_result():
    print("=== Debugging Pipeline Result Structure ===")
    
    # Load embedding service
    embedding_service.load_model()
    
    # Get document store
    document_store = get_document_store()
    
    # Build pipeline manually
    pipeline = Pipeline()
    
    # Add components
    pipeline.add_component("vector_retriever", PgvectorEmbeddingRetriever(document_store=document_store))
    
    if settings.rag_use_reranker:
        pipeline.add_component(
            "reranker",
            FixedSentenceTransformersSimilarityRanker(
                model=settings.rag_reranker_model,
                top_k=settings.rag_rerank_top_k,
                device=settings.rag_reranker_device,
                trust_remote_code=False
            )
        )
        pipeline.connect("vector_retriever.documents", "reranker.documents")
    
    prompt_template = """
    Answer the following question based on the provided context.
    
    Context:
    {% for doc in documents %}
    [{{ loop.index }}] {{ doc.content }}
    {% endfor %}
    
    Question: {{ query }}
    
    Answer:
    """
    
    pipeline.add_component(
        "prompt_builder",
        PromptBuilder(template=prompt_template, required_variables=["documents", "query"])
    )
    
    pipeline.add_component(
        "llm",
        OpenAIGenerator(
            api_key=Secret.from_token(settings.openrouter_api_key),
            api_base_url="https://openrouter.ai/api/v1",
            model=settings.rag_llm_model,
            generation_kwargs={"max_tokens": 100, "temperature": 0.7}
        )
    )
    
    # Connect components
    if settings.rag_use_reranker:
        pipeline.connect("reranker.documents", "prompt_builder.documents")
    else:
        pipeline.connect("vector_retriever.documents", "prompt_builder.documents")
    
    pipeline.connect("prompt_builder", "llm")
    
    # Run pipeline
    query_embedding = await embedding_service.embed_text("kubernetes pod restart")
    
    pipeline_inputs = {
        "vector_retriever": {
            "query_embedding": query_embedding,
            "top_k": 3,
            "filters": None
        },
        "prompt_builder": {
            "query": "kubernetes pod restart"
        }
    }
    
    if settings.rag_use_reranker:
        pipeline_inputs["reranker"] = {"query": "kubernetes pod restart"}
    
    print("Running pipeline...")
    result = pipeline.run(pipeline_inputs)
    
    print(f"\n=== Pipeline Result Structure ===")
    for key, value in result.items():
        print(f"\nKey: {key}")
        print(f"  Type: {type(value)}")
        
        if isinstance(value, dict):
            print(f"  Dict keys: {list(value.keys())}")
            for subkey, subvalue in value.items():
                if subkey == 'documents' and hasattr(subvalue, '__len__'):
                    print(f"    {subkey}: {len(subvalue)} documents")
                    for i, doc in enumerate(subvalue[:2]):  # Show first 2 docs
                        print(f"      Doc {i+1}: {type(doc)}, ID={getattr(doc, 'id', 'no-id')}")
                elif hasattr(subvalue, '__len__') and not isinstance(subvalue, str):
                    print(f"    {subkey}: {type(subvalue)} with {len(subvalue)} items")
                else:
                    print(f"    {subkey}: {type(subvalue)}")
        elif hasattr(value, '__len__') and not isinstance(value, str):
            print(f"  Length: {len(value)}")
        else:
            print(f"  Value: {str(value)[:100]}...")

if __name__ == "__main__":
    asyncio.run(debug_pipeline_result())