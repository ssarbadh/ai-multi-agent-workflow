"""Custom reranker to fix CrossEncoder compatibility issues."""
import logging
from typing import List, Optional, Union, Any, Dict

from haystack import component, Document, default_from_dict, default_to_dict
from haystack.lazy_imports import LazyImport

logger = logging.getLogger(__name__)

with LazyImport(message="Run 'pip install sentence-transformers'") as sentence_transformers_import:
    from sentence_transformers import CrossEncoder


@component
class FixedSentenceTransformersSimilarityRanker:
    """
    Fixed version of SentenceTransformersSimilarityRanker that handles CrossEncoder parameter compatibility.
    
    This component ranks documents based on their similarity to a given query using a cross-encoder model.
    """

    def __init__(
        self,
        model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        device: Optional[str] = None,
        top_k: int = 10,
        query_prefix: str = "",
        document_prefix: str = "",
        meta_fields_to_embed: Optional[List[str]] = None,
        embedding_separator: str = "\n",
        trust_remote_code: bool = False,
    ):
        """
        Create a FixedSentenceTransformersSimilarityRanker component.

        :param model: The name or path of a cross-encoder model.
        :param device: The device on which the model is loaded. If `None`, the default device is automatically
            selected.
        :param top_k: The maximum number of documents to return.
        :param query_prefix: A string to add to the beginning of each query.
        :param document_prefix: A string to add to the beginning of each document.
        :param meta_fields_to_embed: List of meta fields that should be embedded along with the document text.
        :param embedding_separator: Separator used to concatenate the meta fields to the document text.
        :param trust_remote_code: Whether to trust remote code when loading the model.
        """
        sentence_transformers_import.check()

        self.model_name = model
        self.device = device
        self.top_k = top_k
        self.query_prefix = query_prefix
        self.document_prefix = document_prefix
        self.meta_fields_to_embed = meta_fields_to_embed or []
        self.embedding_separator = embedding_separator
        self.trust_remote_code = trust_remote_code

        # Initialize the model with fixed parameters
        try:
            # CrossEncoder in sentence-transformers 3.x accepts model as first positional argument only
            # Other parameters like device and trust_remote_code may not be supported in __init__
            self.model = CrossEncoder(self.model_name)
            
            # Set device after initialization if needed
            if self.device:
                self.model.model.to(self.device)
            
            logger.info(f"Loaded cross-encoder model: {self.model_name}")
        except Exception as e:
            logger.error(f"Failed to load cross-encoder model {self.model_name}: {e}")
            raise

    def _prepare_texts_to_rank(self, query: str, documents: List[Document]) -> List[str]:
        """
        Prepare the texts to rank by concatenating the query and document texts.
        """
        texts_to_rank = []
        for doc in documents:
            meta_values_to_embed = [
                str(doc.meta[key]) for key in self.meta_fields_to_embed if key in doc.meta and doc.meta[key] is not None
            ]
            text_to_embed = self.embedding_separator.join([*meta_values_to_embed, doc.content or ""])
            text_to_embed = self.document_prefix + text_to_embed
            texts_to_rank.append([self.query_prefix + query, text_to_embed])
        return texts_to_rank

    @component.output_types(documents=List[Document])
    def run(
        self,
        query: str,
        documents: List[Document],
        top_k: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Use the cross-encoder model to re-rank the list of documents based on the query.

        :param query: Query string.
        :param documents: List of Documents to rerank starting with the most relevant document.
        :param top_k: The maximum number of documents to return per query.
            If not provided, the default top_k value specified during initialization is used.

        :return: A dictionary with the following keys:
            - `documents`: Reranked list of Documents.
        """
        if not documents:
            return {"documents": []}

        top_k = top_k or self.top_k
        texts_to_rank = self._prepare_texts_to_rank(query, documents)

        # Get similarity scores
        similarity_scores = self.model.predict(texts_to_rank)

        # Create list of (document, score) pairs
        docs_with_scores = list(zip(documents, similarity_scores))
        
        # Sort by score (descending) and take top_k
        docs_with_scores.sort(key=lambda x: x[1], reverse=True)
        docs_with_scores = docs_with_scores[:top_k]

        # Update document scores and return
        ranked_docs = []
        for doc, score in docs_with_scores:
            doc.score = float(score)
            ranked_docs.append(doc)

        return {"documents": ranked_docs}

    def to_dict(self) -> Dict[str, Any]:
        """
        Serializes the component to a dictionary.
        """
        return default_to_dict(
            self,
            model=self.model_name,
            device=self.device,
            top_k=self.top_k,
            query_prefix=self.query_prefix,
            document_prefix=self.document_prefix,
            meta_fields_to_embed=self.meta_fields_to_embed,
            embedding_separator=self.embedding_separator,
            trust_remote_code=self.trust_remote_code,
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FixedSentenceTransformersSimilarityRanker":
        """
        Deserializes the component from a dictionary.
        """
        return default_from_dict(cls, data)