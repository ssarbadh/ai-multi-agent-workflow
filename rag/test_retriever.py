"""Test retriever directly."""
import asyncio
from app.services.haystack_store import get_document_store
from haystack_integrations.components.retrievers.pgvector import PgvectorEmbeddingRetriever
from app.services.embeddings import embedding_service

async def test():
    ds = get_document_store()
    retriever = PgvectorEmbeddingRetriever(document_store=ds)
    
    embedding_service.load_model()
    query_emb = await embedding_service.embed_text("template")
    
    result = retriever.run(query_embedding=query_emb, top_k=5)
    print(f"Retrieved: {len(result['documents'])} documents")
    
    if result['documents']:
        for i, doc in enumerate(result['documents'][:3]):
            print(f"\nDoc {i+1}:")
            print(f"  Score: {doc.score}")
            print(f"  Content: {doc.content[:100]}...")

asyncio.run(test())
