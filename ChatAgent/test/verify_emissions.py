import sys
from google.cloud import bigquery
import os
from dotenv import load_dotenv

load_dotenv("chat_agent/.env")

def verify_math(test_queries):
    client = bigquery.Client(location="europe-west1")
    
    for activity, amount, unit in test_queries:
        query_text = f"{activity} ({unit})"
        
        sql = """
        SELECT * FROM (
            SELECT 
                query.content as input_text,
                base.full_description as matched_factor,
                base.factor as conversion_factor,
                base.unit as factor_unit,
                ROW_NUMBER() OVER(ORDER BY distance) as rn
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
                top_k => 1000
            )
            WHERE (LOWER(base.unit) = LOWER(@unit) OR LOWER(base.unit) = 'passenger.' || LOWER(@unit))
            AND base.category NOT LIKE 'WTT-%'
        )
        WHERE rn = 1
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("text", "STRING", activity),
                bigquery.ScalarQueryParameter("unit", "STRING", unit)
            ]
        )
        
        print(f"\n=======================================================")
        print(f"VERIFICATION TEST:")
        print(f"Input: {amount} {unit} of '{activity}'")
        print(f"Semantic Query: '{query_text}'")
        print(f"-------------------------------------------------------")
        
        results = list(client.query(sql, job_config=job_config).result())
        
        if not results:
            print("No match found!")
            continue
            
        row = results[0]
        calculated_emissions = amount * row.conversion_factor
        
        print(f"Matched Factor:   {row.matched_factor}")
        print(f"Factor Unit:      {row.factor_unit}")
        print(f"Math:             {amount} * {row.conversion_factor}")
        print(f"Result:           {calculated_emissions:.4f} kgCO2e")
        print(f"=======================================================\n")

if __name__ == "__main__":
    tests = [
        ("Flights - Gatwick - Paris", 1000, "km"),
        ("Petrol for company car", 50, "litres"),
        ("Office Electricity", 2500, "kWh")
    ]
    verify_math(tests)
