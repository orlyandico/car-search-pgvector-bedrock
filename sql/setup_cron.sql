-- Enable pg_cron extension in postgres database
\c postgres
CREATE EXTENSION IF NOT EXISTS pg_cron;

-- Switch to car_search to create the function
\c car_search

-- Create function to process embedding queue
CREATE OR REPLACE FUNCTION process_embedding_queue()
RETURNS void AS $$
DECLARE
    all_ids BIGINT[];
    batch_ids BIGINT[];
    lambda_arn aws_commons._lambda_function_arn_1;
    i INTEGER;
    start_idx INTEGER;
    end_idx INTEGER;
BEGIN
    -- Select up to 672 IDs
    SELECT ARRAY_AGG(listing_id ORDER BY queued_at ASC) INTO all_ids
    FROM (
        SELECT listing_id, queued_at
        FROM embedding_queue 
        ORDER BY queued_at ASC 
        LIMIT 672
    ) subq;
    
    IF all_ids IS NULL THEN
        RETURN;
    END IF;
    
    lambda_arn := aws_commons.create_lambda_function_arn('car-search-embeddings', 'eu-west-2');
    
    -- Invoke Lambda up to 7 times with slices of 96 IDs each
    FOR i IN 0..6 LOOP
        start_idx := i * 96 + 1;
        end_idx := (i + 1) * 96;
        
        EXIT WHEN start_idx > array_length(all_ids, 1);
        
        batch_ids := all_ids[start_idx:end_idx];
        
        PERFORM aws_lambda.invoke(
            lambda_arn,
            json_build_object('listing_ids', batch_ids)::json,
            'Event'
        );
        
        IF i < 6 THEN
            PERFORM pg_sleep(5);
        END IF;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- Switch back to postgres to schedule the job
\c postgres

-- Schedule pg_cron job to call the function
SELECT cron.schedule(
    'process-embedding-queue',
    '* * * * *',
    $$SELECT process_embedding_queue();$$
);

-- Update cron.database_name to run jobs in car_search database
UPDATE cron.job SET database = 'car_search' WHERE jobname = 'process-embedding-queue';

-- Verify the job was created
SELECT jobid, jobname, schedule, active, database 
FROM cron.job 
WHERE jobname = 'process-embedding-queue';
