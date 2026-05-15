import pandas as pd
import io
import json
from unittest.mock import patch
from chat_agent.tools import ToolList

# 1. Create a dummy multi-sheet Excel file
df_flights = pd.DataFrame({
    'Date': ['2026-05-15', '2026-05-16'],
    'Departure': ['London', 'New York'],
    'Destination': ['Paris', 'Los Angeles'],
    'Reason': ['Client Meeting', 'Conference'],
    'Kilometers': [344, 3940]
})

df_taxis = pd.DataFrame({
    'Date': ['2026-05-15', '2026-05-16'],
    'Route': ['LHR to Office', 'Office to Hotel'],
    'Distance': [25.5, 5.2]
})

output = io.BytesIO()
with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
    df_flights.to_excel(writer, sheet_name='Flights', index=False)
    df_taxis.to_excel(writer, sheet_name='Taxis', index=False)

dummy_excel_content = output.getvalue()

# 2. Test the ToolList processing
print("Starting test...", flush=True)

with patch.object(ToolList, '_download_from_gcs', return_value=dummy_excel_content):
    tools = ToolList()
    
    # We also need to patch _calculate_emissions_batch_bq to just return what it got, so we can inspect the generated activities
    # or let it run fully if the tables exist in the current project context.
    # We will let it run fully, but we want to intercept the activities to see what the LLM inferred.
    
    original_batch = tools._calculate_emissions_batch_bq
    
    def mock_batch(activities, user_id):
        print("\n--- LLM Inference Result ---")
        for act in activities:
            print(act)
        print("----------------------------\n")
        return original_batch(activities, user_id)
        
    with patch.object(tools, '_calculate_emissions_batch_bq', side_effect=mock_batch):
        result = tools._calculate_emissions_from_file_bq("gs://dummy/test.xlsx", "test_user")
        
        print("\n--- Final Output ---")
        print(json.dumps(result, indent=2))
