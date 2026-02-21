-- Enable pg_cron extension in postgres database
\c postgres
CREATE EXTENSION IF NOT EXISTS pg_cron;

-- Switch to car_search to create the function
\c car_search

-- Create function to process embedding queue
CREATE OR REPLACE FUNCTION process_embedding_queue()
RETURNS void AS $$
DECLARE
    queue_depth INTEGER;
    num_batches INTEGER;
    batch_ids BIGINT[];
    lambda_arn aws_commons._lambda_function_arn_1;
    i INTEGER;
BEGIN
    SELECT COUNT(*) INTO queue_depth FROM embedding_queue;
    
    IF queue_depth = 0 THEN
        RETURN;
    END IF;
    
    num_batches := LEAST(CEIL(queue_depth / 96.0)::INTEGER, 10);
    lambda_arn := aws_commons.create_lambda_function_arn('car-search-embeddings', 'eu-west-2');
    
    FOR i IN 1..num_batches LOOP
        SELECT ARRAY_AGG(listing_id) INTO batch_ids
        FROM (
            SELECT listing_id 
            FROM embedding_queue 
            ORDER BY queued_at ASC 
            LIMIT 96
        ) subq;
        
        EXIT WHEN batch_ids IS NULL;
        
        PERFORM aws_lambda.invoke(
            lambda_arn,
            json_build_object('listing_ids', batch_ids)::json,
            'Event'
        );
        
        DELETE FROM embedding_queue WHERE listing_id = ANY(batch_ids);
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
