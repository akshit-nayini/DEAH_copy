from claude_agent_sdk import query
import anyio
 
async def main():
    async for message in query(prompt="What is Biryani?"):
        # Check if it's a ResultMessage
        if hasattr(message, 'result'):
            print(message.result)
            break  # Got the answer, stop
 
anyio.run(main)