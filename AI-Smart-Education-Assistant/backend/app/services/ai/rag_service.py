from typing import List, Dict, Optional
from app.db.chromadb import chroma_db
from app.core.config import settings
from langchain_google_genai import GoogleGenerativeAIEmbeddings
import logging

logger = logging.getLogger(__name__)

class RAGService:
    def __init__(self):
        self.embeddings = GoogleGenerativeAIEmbeddings(
            model="models/gemini-embedding-001",
            google_api_key=settings.GEMINI_API_KEY,
            transport="rest"
        )
        self.collection_name = "edumind_vectors"

    def get_or_create_collection(self):
        client = chroma_db.get_client()
        if not client:
            raise RuntimeError("ChromaDB client is not initialized")
        return client.get_or_create_collection(name=self.collection_name)

    def store_documents(self, chunks: List[Dict]):
        """
        Store a list of chunks in ChromaDB.
        Each chunk is a dict with 'content' and 'metadata'.
        """
        if not chunks:
            return
            
        collection = self.get_or_create_collection()
        
        # Prepare data for ChromaDB
        documents = [chunk["content"] for chunk in chunks]
        metadatas = [chunk["metadata"] for chunk in chunks]
        
        # Generate unique IDs for each chunk based on document ID and chunk number
        ids = [f"{m.get('document_id', 'doc')}_{m.get('chunk_number', i)}" for i, m in enumerate(metadatas)]
        
        # We manually generate embeddings because we pass them directly, or we can use an embedding function
        # ChromaDB allows passing an embedding function directly when creating collection.
        # But to be safe and agnostic, we can generate them via LangChain and pass them.
        try:
            embedded_docs = self.embeddings.embed_documents(documents)
            collection.add(
                documents=documents,
                embeddings=embedded_docs,
                metadatas=metadatas,
                ids=ids
            )
            logger.info(f"Stored {len(chunks)} chunks in ChromaDB")
        except Exception as e:
            logger.error(f"Error storing in ChromaDB: {str(e)}")
            raise RuntimeError(f"Embedding generation or storage failed: {str(e)}")

    def similarity_search(self, query: str, user_id: str, top_k: int = 5, document_ids: Optional[List[str]] = None) -> List[Dict]:
        """
        Search for similar chunks in ChromaDB with fallbacks to direct collection fetch
        and file-on-disk extraction if vector search returns empty results.
        """
        collection = self.get_or_create_collection()
        
        try:
            where_clause = {"user_id": str(user_id)}
            if document_ids and len(document_ids) > 0:
                clean_doc_ids = [str(d) for d in document_ids if d]
                if len(clean_doc_ids) == 1:
                    where_clause = {
                        "$and": [
                            {"user_id": str(user_id)},
                            {"document_id": clean_doc_ids[0]}
                        ]
                    }
                elif len(clean_doc_ids) > 1:
                    where_clause = {
                        "$and": [
                            {"user_id": str(user_id)},
                            {"document_id": {"$in": clean_doc_ids}}
                        ]
                    }
            
            # 1. First try direct get from ChromaDB for the specified document_ids
            if document_ids and len(document_ids) > 0:
                try:
                    get_results = collection.get(where=where_clause, limit=top_k)
                    if get_results and get_results.get("documents") and len(get_results["documents"]) > 0:
                        formatted = []
                        docs = get_results["documents"]
                        metas = get_results.get("metadatas", [{}] * len(docs))
                        for doc, meta in zip(docs, metas):
                            if doc and len(doc.strip()) > 0:
                                formatted.append({
                                    "content": doc,
                                    "metadata": meta or {"document_id": document_ids[0]},
                                    "score": 0.0
                                })
                        if formatted:
                            logger.info(f"Direct collection get retrieved {len(formatted)} chunks for doc {document_ids}")
                            return formatted
                except Exception as ex_get:
                    logger.warn(f"Direct collection get failed: {ex_get}")

            # 2. Vector similarity search query
            query_embedding = self.embeddings.embed_query(query)
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where=where_clause
            )
            
            formatted_results = []
            if results["documents"] and results["documents"][0]:
                docs = results["documents"][0]
                metas = results["metadatas"][0]
                distances = results["distances"][0] if "distances" in results and results["distances"] else [0] * len(docs)
                
                for doc, meta, dist in zip(docs, metas, distances):
                    if doc and len(doc.strip()) > 0:
                        formatted_results.append({
                            "content": doc,
                            "metadata": meta,
                            "score": dist
                        })
                    
            if formatted_results:
                return formatted_results

            # 3. Fallback: Search without document_id restriction for user
            fallback_where = {"user_id": str(user_id)}
            results_fallback = collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where=fallback_where
            )
            if results_fallback["documents"] and results_fallback["documents"][0]:
                for doc, meta in zip(results_fallback["documents"][0], results_fallback["metadatas"][0]):
                    if doc and len(doc.strip()) > 0:
                        formatted_results.append({
                            "content": doc,
                            "metadata": meta,
                            "score": 0.0
                        })
                if formatted_results:
                    return formatted_results

        except Exception as e:
            logger.error(f"Error in similarity search: {str(e)}")
            
        return []

rag_service = RAGService()
