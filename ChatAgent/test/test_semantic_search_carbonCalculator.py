import sys
from google.cloud import bigquery
import os
from dotenv import load_dotenv

load_dotenv("chat_agent/.env")

def test_search(query_text):
    client = bigquery.Client(location="europe-west1")
    
    sql = """
    SELECT 
        query.content as input_text,
        base.full_description,
        base.factor,
        base.unit,
        base.category,
        distance
    FROM VECTOR_SEARCH(
        TABLE carbon_data.emission_factors,
        'embedding',
        (
            SELECT * FROM ML.GENERATE_EMBEDDING(
                MODEL carbon_data.embedding_model,
                (SELECT @text as content),
                STRUCT('RETRIEVAL_QUERY' AS task_type)
            )
        ),
        'ml_generate_embedding_result',
        top_k => 3
    )
    """
    
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("text", "STRING", query_text)
        ]
    )
    
    print(f"\nSearching for: '{query_text}'...")
    results = client.query(sql, job_config=job_config).result()
    
    print("-" * 80)
    for i, row in enumerate(results):
        print(f"Match #{i+1} (Distance: {row.distance:.4f})")
        print(f"  Description: {row.full_description}")
        print(f"  Category:    {row.category}")
        print(f"  Factor:      {row.factor} {row.unit}")
        print("-" * 80)

if __name__ == "__main__":
    test_query = sys.argv[1] if len(sys.argv) > 1 else "Flight from London to Paris"
    test_search(test_query)
