"""Embedding service using sentence-transformers."""
import logging
from typing import List, Optional
import numpy as np
from sentence_transformers import SentenceTransformer
import torch

from app.core.config import settings
from app.services.cache import cache_manager

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Service for generating text embeddings."""
    
    def __init__(self):
        self.model: Optional[SentenceTransformer] = None
        self.model_name = settings.rag_embedding_model
        self.device = settings.rag_embedding_device
        self.batch_size = settings.rag_batch_size
        self.max_seq_length = settings.rag_max_seq_length
        
    def load_model(self):
        """Load the embedding model."""
        if self.model is not None:
            return
        
        try:
            logger.info(f"Loading embedding model: {self.model_name}")
            self.model = SentenceTransformer(self.model_name, device=self.device)
            self.model.max_seq_length = self.max_seq_length
            
            # Verify embedding dimension
            test_embedding = self.model.encode("test", show_progress_bar=False)
            actual_dim = len(test_embedding)
            
            if actual_dim != settings.rag_embedding_dim:
                logger.warning(
                    f"Embedding dimension mismatch: expected {settings.rag_embedding_dim}, "
                    f"got {actual_dim}. Update RAG_EMBEDDING_DIM in .env"
                )
            
            logger.info(
                f"Embedding model loaded successfully (dim={actual_dim}, device={self.device})"
            )
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            raise
    
    async def embed_text(self, text: str, use_cache: bool = True) -> List[float]:
        """Generate embedding for a single text."""
        if not text or not text.strip():
            return [0.0] * settings.rag_embedding_dim
        
        # Check cache first
        if use_cache:
            cached = await cache_manager.get_embedding(text, self.model_name)
            if cached is not None:
                return cached
        
        # Generate embedding
        self.load_model()
        try:
            embedding = self.model.encode(
                text,
                show_progress_bar=False,
                convert_to_numpy=True,
                normalize_embeddings=True,
            )
            embedding_list = embedding.tolist()
            
            # Cache the result
            if use_cache:
                await cache_manager.set_embedding(text, self.model_name, embedding_list)
            
            return embedding_list
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            raise
    
    async def embed_batch(
        self, texts: List[str], use_cache: bool = True, show_progress: bool = False
    ) -> List[List[float]]:
        """Generate embeddings for a batch of texts."""
        if not texts:
            return []
        
        self.load_model()
        
        # Check cache for each text
        results = []
        texts_to_embed = []
        indices_to_embed = []
        
        for i, text in enumerate(texts):
            if not text or not text.strip():
                results.append([0.0] * settings.rag_embedding_dim)
                continue
            
            if use_cache:
                cached = await cache_manager.get_embedding(text, self.model_name)
                if cached is not None:
                    results.append(cached)
                    continue
            
            # Need to embed this text
            results.append(None)  # Placeholder
            texts_to_embed.append(text)
            indices_to_embed.append(i)
        
        # Embed uncached texts
        if texts_to_embed:
            try:
                embeddings = self.model.encode(
                    texts_to_embed,
                    batch_size=self.batch_size,
                    show_progress_bar=show_progress,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                )
                
                # Place embeddings in results and cache them
                for idx, embedding, text in zip(indices_to_embed, embeddings, texts_to_embed):
                    embedding_list = embedding.tolist()
                    results[idx] = embedding_list
                    
                    if use_cache:
                        await cache_manager.set_embedding(text, self.model_name, embedding_list)
                        
            except Exception as e:
                logger.error(f"Failed to generate batch embeddings: {e}")
                raise
        
        return results
    
    def get_embedding_dim(self) -> int:
        """Get the embedding dimension."""
        return settings.rag_embedding_dim
    
    def unload_model(self):
        """Unload the model to free memory."""
        if self.model is not None:
            del self.model
            self.model = None
            if self.device == "cuda":
                torch.cuda.empty_cache()
            logger.info("Embedding model unloaded")


# Global embedding service instance
embedding_service = EmbeddingService()
