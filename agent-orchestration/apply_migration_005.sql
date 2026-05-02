-- Apply migration 005: Add CLOUDOPS and SRE to RequestType enum
-- This script manually applies the migration since alembic is having issues

-- Add CLOUDOPS enum value if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum 
        WHERE enumlabel = 'CLOUDOPS' 
        AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'requesttype')
    ) THEN
        ALTER TYPE requesttype ADD VALUE 'CLOUDOPS';
        RAISE NOTICE 'Added CLOUDOPS to requesttype enum';
    ELSE
        RAISE NOTICE 'CLOUDOPS already exists in requesttype enum';
    END IF;
END$$;

-- Add SRE enum value if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum 
        WHERE enumlabel = 'SRE' 
        AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'requesttype')
    ) THEN
        ALTER TYPE requesttype ADD VALUE 'SRE';
        RAISE NOTICE 'Added SRE to requesttype enum';
    ELSE
        RAISE NOTICE 'SRE already exists in requesttype enum';
    END IF;
END$$;

-- Update alembic_version to mark migration 005 as applied
UPDATE alembic_version SET version_num = '005';

-- Verify the changes
SELECT enumlabel FROM pg_enum 
WHERE enumtypid = (SELECT oid FROM pg_type WHERE typname = 'requesttype')
ORDER BY enumlabel;

SELECT * FROM alembic_version;
