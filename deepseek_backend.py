"""Bridge the official legacy Completion call to DeepSeek chat completion."""
import ast
import json
import time
from pathlib import Path

CONTINUATION_INSTRUCTION = """You complete Python programs for a simulated robot.
The user message is the ORIGINAL few-shot Python prompt, ending in a task comment.
Return ONLY the new Python code that continues it. Do not repeat the prompt,
examples, imports, object list or task comment. Do not use Markdown fences or
explanations. For a function-definition task, return its full def statement and
body. Reuse the APIs and conventions in the examples. Output executable code,
not prose. Do not begin with a comment. The runtime already supplies imports.
"""


class Backend:
    def __init__(self, api_key, log_dir, model="deepseek-flash", max_calls=12, client=None):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.model = model
        self.max_calls = max_calls
        self.calls = 0
        if client is None:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com",
                            timeout=60, max_retries=0)
        self.client = client

    def create(self, *, prompt, stop, temperature, engine, max_tokens):
        if self.calls >= self.max_calls:
            raise RuntimeError(f"API call limit reached ({self.max_calls}).")
        self.calls += 1
        path = self.log_dir / f"call_{self.calls:03d}.json"
        messages = [
            {"role": "system", "content": CONTINUATION_INSTRUCTION},
            {"role": "user", "content": prompt},
        ]
        record = {
            "call_id": self.calls, "requested_model": engine,
            "messages": messages, "stop": list(stop),
            "temperature": temperature, "max_tokens": max_tokens,
            "thinking": "disabled", "status": "started",
        }
        started = time.monotonic()
        def save():
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        save()
        try:
            print(f"[API {self.calls}/{self.max_calls}] requesting code...", flush=True)
            response = self.client.chat.completions.create(
                model=engine, messages=messages, stop=list(stop),
                temperature=temperature, max_tokens=max_tokens,
                extra_body={"thinking": {"type": "disabled"}},
            )
            choice = response.choices[0]
            raw = choice.message.content or ""
            record.update({
                "returned_model": response.model,
                "raw_output": raw, "finish_reason": choice.finish_reason,
                "usage": response.usage.model_dump() if response.usage else None,
            })
            code = raw.strip()
            # Remove only a complete outer fence; preserve the raw response in the log.
            if code.startswith("```") and code.endswith("```"):
                lines = code.splitlines()
                if lines[0].strip() in {"```", "```python", "```Python"}:
                    code = "\n".join(lines[1:-1]).strip()
            record["code"] = code
            if choice.finish_reason != "stop":
                raise RuntimeError(f"Incomplete model output: {choice.finish_reason}")
            if not code:
                raise RuntimeError("Empty code output; inspect the saved call log.")
            ast.parse(code)
            record["status"] = "ok"
            return {"choices": [{"text": code}]}
        except Exception as error:
            record["status"] = "error"
            record["error"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            record["elapsed_seconds"] = time.monotonic() - started
            save()

    def edit(self, **kwargs):
        raise NotImplementedError("Legacy automatic Edit calls are not enabled.")
