-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS aws_lambda CASCADE;

-- Create staging table for embedding queue
CREATE TABLE IF NOT EXISTS embedding_queue (
    listing_id BIGINT PRIMARY KEY,
    queued_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_embedding_queue_queued_at ON embedding_queue(queued_at);

-- Create trigger function
CREATE OR REPLACE FUNCTION queue_embedding_update()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO embedding_queue (listing_id)
    VALUES (NEW.id)
    ON CONFLICT (listing_id) DO UPDATE
    SET queued_at = NOW();
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger on relevant fields
DROP TRIGGER IF EXISTS car_listing_queue_embedding ON car_listings;

CREATE TRIGGER car_listing_queue_embedding
AFTER INSERT OR UPDATE OF description, price, year, manufacturer, model, type, 
                          condition, fuel, transmission, odometer, drive, 
                          paint_color, cylinders
ON car_listings
FOR EACH ROW
EXECUTE FUNCTION queue_embedding_update();
