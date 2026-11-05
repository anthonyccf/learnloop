"""Local, scoped exact cosine search using sqlite-vec (no vector server)."""

import math

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert
from sqlite_vec import serialize_float32

from learnloop.core.errors import ServiceError
from learnloop.persistence.database import ChunkEmbedding, make_engine


class SQLiteVectors:
    def __init__(self, settings):
        self.settings = settings
        self.engine = make_engine(settings.database_url.get_secret_value())

    def check(self):
        with self.engine.connect() as connection:
            version = connection.scalar(select(func.vec_version()))
            connection.execute(select(ChunkEmbedding.chunk_id).limit(1))
            incompatible = connection.scalar(
                select(ChunkEmbedding.chunk_id)
                .where(
                    (ChunkEmbedding.dimensions != self.settings.embedding_dimensions)
                    | (ChunkEmbedding.model != self.settings.ollama_embedding_model)
                )
                .limit(1)
            )
        if incompatible:
            raise ServiceError(
                "collection_mismatch",
                "Stored vectors use another embedding model or dimension. Rebuild the index first.",
                False,
            )
        return {
            "status": "ok",
            "dimensions": self.settings.embedding_dimensions,
            "extension": version,
        }

    def upsert(self, chunk, owner_id, vector):
        if (
            len(vector) != self.settings.embedding_dimensions
            or not all(type(x) in (float, int) and math.isfinite(x) for x in vector)
            or not any(vector)
        ):
            raise ServiceError("invalid_embedding", "Invalid vector dimensions or values.", False)
        try:
            packed = serialize_float32(vector)
        except (OverflowError, ValueError) as exc:
            raise ServiceError(
                "invalid_embedding", "Vector exceeds float32 limits.", False
            ) from exc
        # Embedding generation is deliberately outside this short write transaction.
        values = {
            "chunk_id": chunk["id"],
            "owner_id": owner_id,
            "course_id": chunk["course_id"],
            "document_id": chunk["document_id"],
            "model": self.settings.ollama_embedding_model,
            "dimensions": self.settings.embedding_dimensions,
            "vector": packed,
        }
        statement = insert(ChunkEmbedding).values(**values)
        with self.engine.begin() as connection:
            connection.execute(
                statement.on_conflict_do_update(index_elements=["chunk_id"], set_=values)
            )

    def search(self, vector, owner_id, course_id, document_ids, limit):
        if not document_ids or limit <= 0:
            return []
        distance = func.vec_distance_cosine(ChunkEmbedding.vector, serialize_float32(vector))
        # Scope BEFORE ranking/limiting, so another course cannot crowd out results.
        query = (
            select(ChunkEmbedding.chunk_id)
            .where(
                ChunkEmbedding.owner_id == owner_id,
                ChunkEmbedding.course_id == course_id,
                ChunkEmbedding.document_id.in_(document_ids),
                ChunkEmbedding.model == self.settings.ollama_embedding_model,
                ChunkEmbedding.dimensions == self.settings.embedding_dimensions,
            )
            .order_by(distance, ChunkEmbedding.chunk_id)
            .limit(limit)
        )
        with self.engine.connect() as connection:
            return list(connection.scalars(query))
