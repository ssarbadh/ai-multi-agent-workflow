-- Migration 006: Enhance message schema with agent type and parent linkage
-- Run this manually if alembic migration fails

-- Add new columns to messages table
ALTER TABLE messages ADD COLUMN IF NOT EXISTS agent_type VARCHAR;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS parent_message_id VARCHAR;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS metadata JSON;

-- Add foreign key for parent_message_id (self-referential)
ALTER TABLE messages 
ADD CONSTRAINT fk_messages_parent_message_id 
FOREIGN KEY (parent_message_id) 
REFERENCES messages(id) 
ON DELETE SET NULL;

-- Add indexes for better query performance
CREATE INDEX IF NOT EXISTS ix_messages_agent_type ON messages(agent_type);
CREATE INDEX IF NOT EXISTS ix_messages_parent_message_id ON messages(parent_message_id);

-- Add comments to explain the schema
COMMENT ON COLUMN messages.agent_type IS 
'Type of agent that generated the response: conversational, devops, cloudops, sre';

COMMENT ON COLUMN messages.parent_message_id IS 
'ID of the user message this response is replying to (for linking user input to agent response)';

COMMENT ON COLUMN messages.metadata IS 
'Additional metadata: model_name, tokens_used, generation_time_ms, temperature, etc.';

-- Update alembic version table
INSERT INTO alembic_version (version_num) VALUES ('006')
ON CONFLICT (version_num) DO NOTHING;

-- Verify the changes
SELECT 
    column_name, 
    data_type, 
    is_nullable
FROM information_schema.columns
WHERE table_name = 'messages'
AND column_name IN ('agent_type', 'parent_message_id', 'metadata')
ORDER BY column_name;
