import os
from neo4j import GraphDatabase
from dotenv import load_dotenv
from langchain_google_genai import GoogleGenerativeAIEmbeddings

load_dotenv()

embedder = GoogleGenerativeAIEmbeddings(
    model="models/gemini-embedding-001"
)

class Memory:

    def __init__(self):

        self.driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI"),
            auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD"))
        )

        # Create vector index if not exists
        with self.driver.session() as s:
            s.run("""
            CREATE VECTOR INDEX msg_embeddings IF NOT EXISTS
            FOR (m:UserMessage)
            ON (m.embedding)
            OPTIONS {
             indexConfig: {
              `vector.dimensions`: 3072,
              `vector.similarity_function`: 'cosine'
             }
            }
            """)

    def save(self, user_id, user_msg, ai_msg):

        vec = embedder.embed_query(user_msg)

        with self.driver.session() as s:
            s.run("""

            MERGE (p:Person {id:$uid})

            CREATE (m:UserMessage {
                text:$um,
                ts:timestamp(),
                embedding:$vec
            })

            CREATE (a:AIMessage {
                text:$am,
                ts:timestamp()
            })

            MERGE (p)-[:SAID]->(m)
            MERGE (m)-[:ANSWERED_BY]->(a)

            WITH p,m
            MATCH (p)-[:SAID]->(prev)
            WHERE prev.ts < m.ts
            WITH prev,m ORDER BY prev.ts DESC LIMIT 1
            MERGE (prev)-[:NEXT]->(m)

            """,
            uid=user_id,
            um=user_msg,
            am=ai_msg,
            vec=vec)

    def recall(self, user_id, query):

        qvec = embedder.embed_query(query)

        with self.driver.session() as s:
            res = s.run("""
            CALL db.index.vector.queryNodes(
              'msg_embeddings',
              5,
              $qvec
            )
            YIELD node, score

            MATCH (p:Person {id:$uid})-[:SAID]->(node)-[:ANSWERED_BY]->(a)

            RETURN node.text AS u, a.text AS ai
            ORDER BY score DESC
            """,
            uid=user_id,
            qvec=qvec)

            return "\n".join([f"{r['u']} → {r['ai']}" for r in res])
