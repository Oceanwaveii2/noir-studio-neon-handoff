"""Loopback-only, one-process runner for the isolated local model trial."""
from __future__ import annotations

from contextlib import suppress
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import time

from prose_engine.local_trial import CONTEXT, MAX_TOKENS, SCHEMA, SEED

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class LocalRuntimeError(RuntimeError):
    pass


def gpu_memory() -> tuple[int, int] | None:
    try:
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.total,memory.free", "--format=csv,noheader,nounits"],
            text=True, timeout=5, creationflags=NO_WINDOW,
        )
        total, free = [int(item.strip()) for item in output.splitlines()[0].split(",")]
        return total, free
    except (OSError, ValueError, subprocess.SubprocessError, IndexError):
        return None


def _windows_gpu_sampler(pid: int, path: Path):
    """Measure this child process only; nvidia-smi reports N/A per PID on WDDM."""
    if os.name != "nt":
        return None
    script = (
        r"Get-Counter '\GPU Process Memory(*)\Dedicated Usage' -SampleInterval 1 -Continuous | "
        "ForEach-Object { $mine = $_.CounterSamples | Where-Object "
        f"{{ $_.InstanceName -like 'pid_{pid}_*' }}; "
        "if ($mine) { [long](($mine | Measure-Object -Property CookedValue -Sum).Sum) } }"
    )
    try:
        with path.open("xb") as handle:
            shell = shutil.which("pwsh.exe") or "powershell.exe"
            return subprocess.Popen([shell, "-NoProfile", "-NonInteractive", "-Command", script],
                                    stdin=subprocess.DEVNULL, stdout=handle, stderr=subprocess.STDOUT,
                                    creationflags=NO_WINDOW)
    except OSError:
        return None


class LlamaRuntime:
    def __init__(self, executable: Path, weights: Path, log: Path, cpu: bool):
        self.executable = executable.resolve()
        self.weights = weights.resolve()
        self.log = log
        self.memory_log = log.with_name("runtime-dedicated-bytes.txt")
        self.cpu = cpu
        self.proc = None
        self.sampler = None
        self.api_key = secrets.token_hex(32)
        self.headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        self.cold_ms = None
        self.gpu_before = gpu_memory() if not cpu else None
        if not cpu and (self.gpu_before is None or self.gpu_before[1] < 3000):
            raise LocalRuntimeError("At least 3 GiB of free GPU memory is required for this trial.")

    def __enter__(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        env = {key: value for key, value in os.environ.items() if not key.startswith(("LLAMA_ARG_", "LLAMA_SERVER_"))}
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", LLAMA_API_KEY=self.api_key)
        command = [str(self.executable), "-m", str(self.weights), "--host", "127.0.0.1",
                   "--port", str(self.port), "--ctx-size", str(CONTEXT), "--parallel", "1",
                   "--threads", "6", "--batch-size", "256", "--ubatch-size", "128",
                   "--reasoning", "off", "--slots", "--cache-ram", "0", "--no-ui",
                   "--offline", "--log-verbosity", "4",
                   "--n-gpu-layers", "0" if self.cpu else "auto"]
        if not self.cpu:
            # Leave at least 1 GiB for other processes, or more to keep this
            # trial within 14 GiB of the device.
            margin = max(1024, self.gpu_before[0] - 14 * 1024)
            command.extend(["--fit", "on", "--fit-target", str(margin)])
        else:
            command.extend(["--device", "none"])
        start = time.perf_counter()
        try:
            with self.log.open("xb") as handle:
                self.proc = subprocess.Popen(command, cwd=self.executable.parent, env=env,
                                             stdin=subprocess.DEVNULL, stdout=handle,
                                             stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
            if not self.cpu:
                self.sampler = _windows_gpu_sampler(self.proc.pid, self.memory_log)
            end = start + 180
            while time.perf_counter() < end:
                if self.proc.poll() is not None:
                    raise LocalRuntimeError(f"Local runtime stopped during startup (exit {self.proc.returncode}).")
                try:
                    if self.request("/health", timeout=2).get("status") == "ok":
                        self.cold_ms = round((time.perf_counter() - start) * 1000, 2)
                        return self
                except (OSError, LocalRuntimeError, http.client.HTTPException):
                    pass
                time.sleep(.2)
            raise LocalRuntimeError("Local runtime did not start within 180 seconds.")
        except BaseException:
            self.close()
            raise

    def __exit__(self, *_):
        self.close()

    def close(self):
        for proc in (self.proc, self.sampler):
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)

    def request(self, path: str, body=None, timeout=75) -> dict | list:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            conn.request("GET" if body is None else "POST", path,
                         None if body is None else json.dumps(body).encode("utf-8"),
                         self.headers)
            response = conn.getresponse()
            if response.status != 200:
                # Do not print the body: some runtimes echo the user's prompt.
                response.read(4096)
                raise LocalRuntimeError(f"Local endpoint {path} returned HTTP {response.status}.")
            return json.load(response)
        finally:
            conn.close()

    @staticmethod
    def payload(messages, grammar, stream=False) -> dict:
        body = {"messages": messages, "temperature": 0, "seed": SEED, "max_tokens": MAX_TOKENS,
                "cache_prompt": False, "stream": stream,
                "chat_template_kwargs": {"enable_thinking": False}}
        if grammar:
            # b12211 reads schema from the OpenAI-style wrapper; with only
            # response_format.schema it silently falls back to any JSON object.
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "u7_span_proposal", "strict": True, "schema": SCHEMA},
            }
        return body

    def generate(self, messages, grammar=False) -> dict:
        response = self.request("/v1/chat/completions", self.payload(messages, grammar))
        choice = response["choices"][0]
        return {"raw": choice["message"].get("content") or "",
                "finish_reason": choice.get("finish_reason"),
                "completion_tokens": response.get("usage", {}).get("completion_tokens")}

    def schema_probe(self) -> dict[str, bool]:
        messages = [
            {"role": "user", "content": "Return the single bare token NOT_JSON. If the format requires a JSON object, "
                                        "set operation to keep and replacement to an empty string."},
        ]
        shape = {}
        for constrained in (False, True):
            raw = self.generate(messages, grammar=constrained)["raw"]
            try:
                value = json.loads(raw)
            except ValueError:
                value = None
            shape["grammar" if constrained else "strict"] = (
                isinstance(value, dict) and set(value) == {"operation", "replacement"}
                and value["operation"] in ("keep", "replace") and isinstance(value["replacement"], str)
            )
        return shape

    def cancel_probe(self) -> dict:
        messages = [
            {"role": "system", "content": "Write only the requested neutral number sequence."},
            {"role": "user", "content": "Write the integers 1 through 500 in order, separated by spaces."},
        ]
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=45)
        response = None
        saw_token = False
        try:
            conn.request("POST", "/v1/chat/completions",
                         json.dumps(self.payload(messages, False, True)).encode("utf-8"),
                         self.headers)
            response = conn.getresponse()
            if response.status != 200:
                raise LocalRuntimeError("The streaming cancellation request was rejected.")
            for line in response:
                if not line.startswith(b"data:"):
                    continue
                data = line[len(b"data:"):].strip()
                if data == b"[DONE]":
                    break
                choices = json.loads(data).get("choices") or []
                if choices and choices[0].get("delta", {}).get("content"):
                    saw_token = True
                    break
            # Observe the active slot while the response is still open.
            active = self.request("/slots", timeout=5)
            was_processing = any(row.get("is_processing") is True for row in active)
            start = time.perf_counter()
        finally:
            if conn.sock is not None:
                with suppress(OSError):
                    conn.sock.shutdown(socket.SHUT_RDWR)
            if response is not None:
                response.close()
            conn.close()
        if not saw_token or not was_processing:
            return {"status": "INCONCLUSIVE", "reason": "The runtime completed before an active slot was observed."}
        while (time.perf_counter() - start) < 12:
            slots = self.request("/slots", timeout=3)
            if all(row.get("is_processing") is False for row in slots) and slots:
                return {"status": "CANCELLED", "slot_release_ms": round((time.perf_counter()-start)*1000, 2)}
            time.sleep(.05)
        return {"status": "TIMEOUT", "reason": "The slot did not release within 12 seconds."}

    def allocation(self) -> dict:
        logs = self.log.read_text(encoding="utf-8", errors="replace")
        layers = re.findall(r"offloaded (\d+)/(\d+) layers", logs)
        buffers = [
            {"label": line.strip().split("=")[0].strip(), "mib": float(match[1])}
            for line in logs.splitlines()
            if (match := re.search(r"CUDA0\s+.+?buffer size\s*=\s*([\d.]+)\s+MiB", line))
        ]
        sampled = []
        if self.memory_log.is_file():
            sampled = [int(line) for line in self.memory_log.read_text(encoding="ascii", errors="ignore").splitlines()
                       if line.strip().isascii() and line.strip().isdecimal()]
        return {"offloaded_layers": list(map(int, layers[-1])) if layers else None,
                "reported_cuda_buffer_mib": round(sum(x["mib"] for x in buffers), 2) if buffers or self.cpu else None,
                "sampled_peak_dedicated_mib": round(max(sampled) / 2**20, 2) if sampled else None,
                "dedicated_samples": len(sampled),
                "buffers": buffers}
