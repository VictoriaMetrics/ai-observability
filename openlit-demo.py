import json
import os
import time
import traceback
import urllib.request

import openlit
from openai import OpenAI
from opentelemetry import trace

openlit.init(
    otlp_endpoint="http://localhost:4318",
    application_name="openlit_demo",
    environment="prod",
    capture_message_content=True,
)

tracer = trace.get_tracer("openlit-demo")

client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"],
    base_url=os.environ.get("OPENAI_BASE_URL") or None,
)

def get_random_joke(tool_call_id: str | None = None) -> dict:
    # Add tool call with tracing instrumentation to enrich emitted telemetry.
    # https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/
    with tracer.start_as_current_span("execute_tool get_random_joke") as span:
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", "get_random_joke")
        span.set_attribute("gen_ai.tool.type", "function")
        if tool_call_id:
            span.set_attribute("gen_ai.tool.call.id", tool_call_id)

        url = "https://official-joke-api.appspot.com/random_joke"
        span.set_attribute("http.url", url)
        with urllib.request.urlopen(url, timeout=10) as resp:
            joke = json.load(resp)
        span.set_attribute("joke.id", joke.get("id", -1))
        span.set_attribute("joke.type", joke.get("type", ""))
        return {"setup": joke["setup"], "punchline": joke["punchline"]}


def run() -> None:
    with tracer.start_as_current_span("joke-explainer-app"):
        messages = [
            {
                "role": "system",
                "content": (
                    "You fetch a joke using the provided tool, then explain "
                    "why it is funny in 2-3 sentences."
                ),
            },
            {"role": "user", "content": "Find a random joke and explain its humor."},
        ]

        first = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools= [{
                "type": "function",
                "function": {
                    "name": "get_random_joke",
                    "description": "Fetch one random joke (setup + punchline) from a public joke API.",
                    "parameters": {"type": "object", "properties": {}},
                },
            }],
            tool_choice="auto",
        )
        assistant_msg = first.choices[0].message
        messages.append(assistant_msg.model_dump(exclude_none=True))

        for call in assistant_msg.tool_calls or []:
            if call.function.name == "get_random_joke":
                result = get_random_joke(tool_call_id=call.id)
            else:
                result = {"error": f"unknown tool: {call.function.name}"}
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result),
                }
            )

        second = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
        )
        print(second.choices[0].message.content)


if __name__ == "__main__":
    while True:
        print("------", flush=True)
        try:
            run()
        except KeyboardInterrupt:
            raise
        except Exception:
            traceback.print_exc()
        time.sleep(5)
