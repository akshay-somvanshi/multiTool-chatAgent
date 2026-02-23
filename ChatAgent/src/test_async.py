import asyncio
import timeit
import sys
import os

# Ensure we can import from src
sys.path.append(os.path.join(os.getcwd(), 'src'))

from classifier import classifier

async def run_test():
    # These instructions usually come from app.py, but we mock them here for the test
    system_instruction_gen = "You are a generalist."
    system_instruction_plan = "You are a planner."
    system_instruction_act = "You are an action agent."

    print("Initializing Classifier...")
    c = classifier(
        system_instruction_gen=system_instruction_gen, 
        system_instruction_plan=system_instruction_plan, 
        system_instruction_act=system_instruction_act
    )

    query = "Who won the nobel prize in biology in 2025?"
    print(f"\nRunning Async Test with Query: {query}")
    
    start_time = timeit.default_timer()
    response = await c.ainvoke(query, "CORZZX0MxTQtGyAD7PSCI1HLp3y2")
    end_time = timeit.default_timer()
    
    print(f"\n[Test Result] Time taken: {end_time - start_time:.2f}s")
    print(f"Response: {response}")

if __name__ == "__main__":
    asyncio.run(run_test())
