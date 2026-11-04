"""Framework adapters: turn LangGraph / CrewAI runs into CloudSentinel OTel spans (and gate their tools).

    from cloudsentinel.adapters.langgraph import CloudSentinelCallback, guard   # pip install "cloudsentinel[langgraph]"
    from cloudsentinel.adapters.crewai import instrument                        # pip install "cloudsentinel[crewai]"

Each adapter only imports its framework when you import the adapter module.
"""
