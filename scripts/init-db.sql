-- AegisOps Database Initialization Script
-- Creates all required databases and extensions

-- Enable pgvector extension in main database
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";

-- Note: All services use the same 'aegisops' database
-- This simplifies deployment and allows for cross-service queries if needed
