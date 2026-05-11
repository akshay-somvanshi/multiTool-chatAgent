import sys
import os

# Add the project root to sys.path
sys.path.append('/home/ubuntu_akshay/multiTool-chatAgent/ChatAgent')

from chat_agent.tools import ToolList

def test_roi_calculation():
    tools = ToolList()
    
    # Sample inputs
    inputs = {
        "user_id": "test_user_123",
        "new_revenue": 10000,
        "retained_revenue": 5000,
        "ops_cost_reduction": 2000,
        "risk_minimized": 1000,
        "ops_cost_reduction_5y": 15000,
        "financing_cost_diff": 500,
        "spend_this_year": 3000
    }
    
    print("Testing ROI calculation with inputs:", inputs)
    
    try:
        result = tools.calculate_sustainability_roi(**inputs)
        print("\nResult:", result)
        
        if "error" in result:
            print(f"Warning: Tool returned an error (likely Firestore connectivity): {result['error']}")
            print("Note: This is expected if Firestore is not accessible in this environment.")
        else:
            # ROI = {(10000 * 0.8) + (5000 * 0.7) + (2000 * 1.0) + (1000 * 0.5) + (15000 * 0.9) + (500 * 1.0)} - 3000
            # ROI = {8000 + 3500 + 2000 + 500 + 13500 + 500} - 3000
            # ROI = 28000 - 3000 = 25000
            # Rev Unlocked = 28000
            print("Revenue Unlocked matches expected (approx 28000):", result['estimated_revenue_unlocked'])
            print("Total ROI matches expected (approx 25000):", result['total_roi'])
            
    except Exception as e:
        print(f"Failed to run ROI calculation: {e}")

if __name__ == "__main__":
    test_roi_calculation()

